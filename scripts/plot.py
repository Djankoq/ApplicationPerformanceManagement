"""Export Grafana panel time-series data as a standalone PNG (not a UI screenshot)."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools/python"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

reports = ROOT / "reports"
monitoring = json.loads((reports / "monitoring.json").read_text(encoding="utf-8"))
benchmark = json.loads((reports / "benchmark.json").read_text(encoding="utf-8"))
specifications = [
    ("Rate — completed requests/s", "Rate", "requests / s"),
    ("Errors — HTTP 5xx/s", "Errors", "HTTP 5xx / s"),
    ("Duration — mean, including queue", "Duration: mean", "seconds"),
    ("Duration — p95 (histogram)", "Duration: p95", "seconds"),
    ("Errors — HTTP 5xx (%)", "Error ratio", "%"),
    ("Application scrape health", "Prometheus scrape health", "up"),
]
colors = {"/work/platform": "#2563eb", "/work/virtual": "#d97706"}
fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True, layout="constrained")
start = benchmark["started_epoch"] - 5
end = benchmark["finished_epoch"] + 3
grid = [start + 2 * index for index in range(int((end - start) / 2) + 1)]
for axis, (key, title, unit) in zip(axes.flat, specifications):
    result = monitoring["ranges"][key]["data"]["result"]
    for series in result:
        uri = series["metric"].get("uri", "apm-lab")
        samples = {round(float(t) * 1000): float(v) for t, v in series["values"]}
        times = [datetime.fromtimestamp(t, timezone.utc) for t in grid]
        # Prometheus omits undefined samples. Insert NaN so idle gaps remain gaps,
        # matching Grafana's spanNulls=false rather than drawing invented lines.
        values = [samples.get(round(t * 1000), math.nan) for t in grid]
        values = [v if math.isfinite(v) else math.nan for v in values]
        axis.plot(times, values, label=uri.rsplit("/", 1)[-1],
                  color=colors.get(uri, "#059669"), linewidth=1.8)
    for phase in benchmark["results"]:
        left = datetime.fromtimestamp(phase["first"]["epoch"], timezone.utc)
        right = datetime.fromtimestamp(phase["second"]["epoch"], timezone.utc)
        axis.axvspan(left, right, color=colors[phase["uri"]], alpha=0.07)
    axis.set_title(title, loc="left", weight="bold")
    axis.set_ylabel(unit)
    axis.grid(alpha=0.2)
    axis.set_ylim(bottom=0)
    axis.legend(loc="upper right", frameon=False, fontsize=8)
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=timezone.utc))
    axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=6))
    axis.spines[["top", "right"]].set_visible(False)
for axis in axes[-1]:
    axis.set_xlabel("UTC")
first = benchmark["results"][0]
fig.suptitle(
    f"RED: platform pool (16) vs virtual threads | {first['concurrency']} clients, "
    f"{first['delay_ms']} ms blocking work\n"
    "Phases: baseline platform / baseline virtual / 10% errors platform / 10% errors virtual",
    fontsize=13, weight="bold")
fig.supxlabel("Data exported through Grafana's Prometheus datasource; rate window 8 s. "
               "Shading marks the 10 s Actuator measurement windows.", fontsize=9)
fig.savefig(reports / "red-metrics.png", dpi=150)
plt.close(fig)
print(reports / "red-metrics.png")
