"""Target and hand trajectories from a single CSV."""
import csv
import os
from pathlib import Path
import matplotlib.pyplot as plt
from studio_style import apply_style, finish_figure

apply_style()
project = Path(os.environ["CHART_PROJECT_DIR"])
with (project / "data" / "trajectories.csv").open(newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

fig, ax = plt.subplots(figsize=(4.5, 3.2))
for prefix, label, marker, color in [("target", "Target", "o", "green"), ("hand", "Hand", "s", None)]:
    ax.plot([float(r[f"{prefix}_x"]) for r in rows],
            [float(r[f"{prefix}_y"]) for r in rows],
            marker=marker, markersize=3, linewidth=1.4, label=label, color=color)
ax.set(xlabel="Horizontal position (a.u.)", ylabel="Vertical position (a.u.)",
       title="Moving target interception", xlim=(0, .7), ylim=(0, .8))
ax.legend(frameon=False)
finish_figure(fig, os.environ["CHART_OUTPUT"])
