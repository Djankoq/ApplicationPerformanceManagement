"""Closed-loop HTTP load; throughput is calculated only from Actuator COUNT."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import platform
import threading
import time
import urllib.parse
import urllib.request


def utc(timestamp=None):
    return datetime.fromtimestamp(timestamp or time.time(), timezone.utc).isoformat()


def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def snapshot(base_url, mode):
    query = urllib.parse.urlencode([
        ("tag", f"uri:/work/{mode}"), ("tag", "method:GET")])
    url = f"{base_url}/actuator/metrics/http.server.requests?{query}"
    begin, wall = time.perf_counter(), time.time()
    raw = get_json(url)
    end = time.perf_counter()
    measures = {m["statistic"]: m["value"] for m in raw["measurements"]}
    return {"url": url, "utc": utc(wall + (end - begin) / 2),
            "epoch": wall + (end - begin) / 2,
            "monotonic_midpoint": (begin + end) / 2,
            "read_duration_seconds": end - begin,
            "count": measures["COUNT"], "total_time_seconds": measures["TOTAL_TIME"],
            "raw": raw}


def measure(args, mode, phase):
    uri = f"/work/{mode}"
    probe = get_json(f"{args.base_url}{uri}?delayMs={args.delay_ms}")
    if probe["virtual"] != (mode == "virtual"):
        raise RuntimeError(f"Wrong worker type: {probe}")
    stop = threading.Event()
    gate = threading.Barrier(args.concurrency + 1)
    address = urllib.parse.urlsplit(args.base_url)
    started = time.time()

    def worker(index):
        statuses, transport_errors = Counter(), []
        connection = http.client.HTTPConnection(address.hostname, address.port or 80, timeout=30)
        sequence = index
        gate.wait()
        try:
            while not stop.is_set():
                fail = phase == "errors" and sequence % 10 == 0
                sequence += 1
                path = f"{uri}?delayMs={args.delay_ms}&fail={str(fail).lower()}"
                try:
                    connection.request("GET", path)
                    response = connection.getresponse()
                    response.read()
                    statuses[str(response.status)] += 1
                    if response.status != (503 if fail else 200):
                        transport_errors.append(f"unexpected HTTP {response.status}")
                except (OSError, http.client.HTTPException) as error:
                    transport_errors.append(str(error))
                    connection.close()
                    stop.set()
        finally:
            connection.close()
        return statuses, transport_errors

    print(f"START {phase}/{mode}: {args.concurrency} clients, {args.delay_ms} ms", flush=True)
    with ThreadPoolExecutor(max_workers=args.concurrency) as clients:
        futures = [clients.submit(worker, index) for index in range(args.concurrency)]
        gate.wait()
        try:
            time.sleep(args.warmup)
            first = snapshot(args.base_url, mode)
            # Schedule the second snapshot relative to the first read's midpoint.
            time.sleep(max(0, first["monotonic_midpoint"] + args.seconds - time.perf_counter()))
            second = snapshot(args.base_url, mode)
        finally:
            stop.set()
        # Drain outstanding requests before starting the other mode.
        completed = [future.result() for future in futures]
    elapsed = second["monotonic_midpoint"] - first["monotonic_midpoint"]
    count = second["count"] - first["count"]
    if count <= 0:
        raise RuntimeError("COUNT did not increase, or the application restarted")
    statuses, failures = Counter(), []
    for client_statuses, client_errors in completed:
        statuses.update(client_statuses)
        failures.extend(client_errors)
    if failures:
        raise RuntimeError(f"Load generator errors: {failures[:5]}")
    result = {
        "phase": phase, "mode": mode, "uri": uri, "concurrency": args.concurrency,
        "delay_ms": args.delay_ms, "warmup_seconds": args.warmup,
        "target_window_seconds": args.seconds, "actual_window_seconds": elapsed,
        "first": first, "second": second, "completed_in_window": count,
        "requests_per_second": count / elapsed,
        "requests_per_second_nominal": count / args.seconds,
        "server_mean_duration_seconds":
            (second["total_time_seconds"] - first["total_time_seconds"]) / count,
        "probe": probe, "client_statuses_entire_phase_including_warmup_and_drain": dict(statuses),
        "transport_errors": failures, "started_epoch": started, "finished_epoch": time.time()
    }
    print(f"RESULT {phase}/{mode}: ({second['count']:.0f} - {first['count']:.0f}) / "
          f"{elapsed:.6f} s = {count / elapsed:.3f} req/s; "
          f"mean={result['server_mean_duration_seconds']:.3f} s", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--delay-ms", type=int, default=500)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--warmup", type=float, default=6)
    parser.add_argument("--with-errors", action="store_true",
                        help="Additional, separate phases with 10%% injected HTTP 503")
    parser.add_argument("--output", default="reports/benchmark.json")
    args = parser.parse_args()
    if not (1 <= args.concurrency <= 512 and 1 <= args.delay_ms <= 5000
            and args.seconds > 0 and args.warmup >= 0):
        parser.error("Invalid load settings")
    if urllib.parse.urlsplit(args.base_url).scheme != "http":
        parser.error("--base-url must use http")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = {"started_utc": utc(), "started_epoch": time.time(),
                "client_environment": platform.platform(), "results": []}
    try:
        for phase in (["baseline", "errors"] if args.with_errors else ["baseline"]):
            for mode in ["platform", "virtual"]:
                document["results"].append(measure(args, mode, phase))
                output.write_text(json.dumps(document, indent=2), encoding="utf-8")
                time.sleep(3)  # Separate phases in the RED graphs.
    finally:
        document["finished_utc"] = utc()
        document["finished_epoch"] = time.time()
        document["grafana_url"] = (
            "http://127.0.0.1:3000/d/apm-red?from="
            f"{int((document['started_epoch'] - 5) * 1000)}&to="
            f"{int((document['finished_epoch'] + 5) * 1000)}&refresh=")
        output.write_text(json.dumps(document, indent=2), encoding="utf-8")
    baseline = [item for item in document["results"] if item["phase"] == "baseline"]
    if len(baseline) == 2:
        print(f"Virtual/platform throughput: "
              f"{baseline[1]['requests_per_second'] / baseline[0]['requests_per_second']:.3f}x")
    print(f"Saved: {output}")
    print(document["grafana_url"])


if __name__ == "__main__":
    main()
