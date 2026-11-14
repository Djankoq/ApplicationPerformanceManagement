"""Plot actual MemoryMXBean samples and completed pauses from the GC log."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools/python"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

reports = ROOT / "reports"
data = json.loads((reports / "gc-experiment.json").read_text(encoding="utf-8"))
samples = data["samples"]
pauses = data["gc_pauses"]
fig, axis = plt.subplots(figsize=(12, 6), layout="constrained")
axis.plot([s["uptime_seconds"] for s in samples],
          [s["heap_used_bytes"] / 2**20 for s in samples],
          label="Heap used (MemoryMXBean, ~1 s)", color="#2563eb", linewidth=1.7)
axis.plot([s["uptime_seconds"] for s in samples],
          [s["retained_bytes"] / 2**20 for s in samples],
          label="Retained byte[] payload (static list)", color="#d97706", linewidth=1.7)
for full, color, marker, label in (
        (False, "#059669", ".", "After GC pause (gc.log, integer MiB)"),
        (True, "#dc2626", "x", "After Full GC (gc.log)")):
    selected = [p for p in pauses if p["kind"].startswith("Pause Full") == full]
    axis.scatter([p["uptime_seconds"] for p in selected],
                 [p["after_mib"] for p in selected], color=color, marker=marker,
                 label=label, zorder=4)
axis.axhline(samples[0]["heap_max_bytes"] / 2**20, color="#6b7280",
             linestyle="--", label="Heap limit (128 MiB)")
axis.set(title="Artificial memory leak | Java 21 / G1 / -Xms128m -Xmx128m",
         xlabel="JVM uptime, seconds", ylabel="Memory, MiB", ylim=(0, 138))
axis.grid(alpha=0.2)
axis.spines[["top", "right"]].set_visible(False)
axis.legend(loc="upper left", frameon=True, facecolor="white", framealpha=0.95,
            edgecolor="none", fontsize=9)
fig.supxlabel("Measured data from one local run. Heap samples exclude the last fraction "
              "of a second before OOM. No VisualVM session was used.", fontsize=9)
fig.savefig(reports / "gc-heap.png", dpi=150)
plt.close(fig)
print(reports / "gc-heap.png")
