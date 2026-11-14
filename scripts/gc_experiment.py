"""Run the opt-in leak in a bounded child JVM and preserve measured evidence."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def main():
    jar = ROOT / "target/apm-lab.jar"
    if not jar.is_file():
        raise SystemExit("Build target/apm-lab.jar with mvnw verify first")
    java = shutil.which("java")
    if not java:
        raise SystemExit("Java 21+ is required")
    # Windows PATH may point to Oracle's launcher, which spawns another process.
    # Start the real JVM directly so PID, timeout and cleanup refer to the JVM.
    settings = subprocess.run([java, "-XshowSettings:properties", "-version"],
                              capture_output=True, text=True, check=True)
    java_home = re.search(r"^\s*java\.home\s*=\s*(.+)$", settings.stderr, re.MULTILINE)
    if not java_home:
        raise SystemExit("Cannot resolve java.home")
    java = str(Path(java_home[1].strip()) / "bin" /
               ("java.exe" if sys.platform == "win32" else "java"))
    REPORTS.mkdir(exist_ok=True)
    command = [
        java, "-Xms128m", "-Xmx128m", "-XX:+UseG1GC",
        "-XX:+ExitOnOutOfMemoryError",
        "-Xlog:gc*,safepoint:file=gc.log:time,uptime,level,tags:filecount=0",
        "-jar", str(jar), "--spring.profiles.active=gc-leak",
        "--server.address=127.0.0.1", "--server.port=18080",
        "--gc.leak.metrics=heap.csv",
    ]
    started = datetime.now(timezone.utc).isoformat()
    clock_start = time.monotonic()
    timed_out = False
    # The files describe one run; fail early rather than mix old and new samples.
    for name in ("gc.log", "heap.csv", "gc-experiment.json", "gc-heap.png"):
        (REPORTS / name).unlink(missing_ok=True)
    with (REPORTS / "gc-application.log").open("w", encoding="utf-8") as output:
        process = subprocess.Popen(command, cwd=REPORTS, stdout=output,
                                   stderr=subprocess.STDOUT)
        print(f"Leak JVM PID={process.pid}; heap limit=128 MiB; deadline=150 s", flush=True)
        try:
            deadline = clock_start + 150
            next_status = clock_start + 20
            while process.poll() is None:
                now = time.monotonic()
                if now >= deadline:
                    timed_out = True
                    process.terminate()
                    break
                if now >= next_status:
                    print(f"Running: {now - clock_start:.0f} s; see reports/heap.csv", flush=True)
                    next_status += 20
                time.sleep(0.5)
            exit_code = process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    duration = time.monotonic() - clock_start
    application_log = (REPORTS / "gc-application.log").read_text(encoding="utf-8")
    gc_log = (REPORTS / "gc.log").read_text(encoding="utf-8")
    # Only completed GC pause summaries, excluding start lines and phase timings.
    pattern = re.compile(
        r"\[(?P<uptime>\d+\.\d+)s\]\[info\s*\]\[gc\s*\] "
        r"GC\((?P<id>\d+)\) (?P<kind>Pause .+?) "
        r"(?P<before>\d+)M->(?P<after>\d+)M\((?P<capacity>\d+)M\) "
        r"(?P<duration>\d+\.\d+)ms")
    pauses = []
    for line in gc_log.splitlines():
        match = pattern.search(line)
        if match:
            pauses.append({
                "id": int(match["id"]), "uptime_seconds": float(match["uptime"]),
                "kind": match["kind"], "before_mib": int(match["before"]),
                "after_mib": int(match["after"]),
                "capacity_mib": int(match["capacity"]),
                "duration_ms": float(match["duration"]), "log_line": line,
            })
    samples = []
    if (REPORTS / "heap.csv").is_file():
        with (REPORTS / "heap.csv").open(encoding="utf-8", newline="") as source:
            samples = [{key: float(value) if key == "uptime_seconds" else int(value)
                        for key, value in row.items()} for row in csv.DictReader(source)]
    oom = "java.lang.OutOfMemoryError: Java heap space" in application_log
    load_seconds = (samples[-1]["uptime_seconds"] - samples[0]["uptime_seconds"]
                    if samples else 0)
    full_gc = [pause for pause in pauses if pause["kind"].startswith("Pause Full")]
    successful = (not timed_out and exit_code != 0 and oom and bool(full_gc)
                  and 60 <= duration <= 120 and len(samples) >= 2
                  and samples[-1]["retained_bytes"] > samples[0]["retained_bytes"])
    result = {
        "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
        "java_version": subprocess.run([java, "-version"], capture_output=True,
                                       text=True, check=True).stderr,
        "command": command, "cwd": str(REPORTS), "pid": process.pid,
        "wall_seconds": duration, "sampled_load_seconds": load_seconds,
        "exit_code": exit_code, "timed_out": timed_out, "heap_oom": oom,
        "expected_outcome_observed": successful,
        "allocation": {"block_bytes": 128 * 1024, "sleep_ms": 100,
                       "nominal_mib_per_second": 1.25},
        "samples": samples, "gc_pauses": pauses,
        "full_gc_count": len(full_gc),
    }
    (REPORTS / "gc-experiment.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exit={exit_code}; OOM={oom}; {duration:.2f} s; "
          f"samples={len(samples)}; GC pauses={len(pauses)}; Full GC={len(full_gc)}")
    if not successful:
        raise SystemExit("Expected 60-120 s leak/OOM scenario not observed; inspect reports/gc-*.log")


if __name__ == "__main__":
    main()
