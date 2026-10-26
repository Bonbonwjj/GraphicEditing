"""Horizontal position versus time."""
import csv
import os
from pathlib import Path
import matplotlib.pyplot as plt
from studio_style import apply_style, finish_figure

apply_style()
project = Path(os.environ["CHART_PROJECT_DIR"])
with (project / "data" / "trajectories.csv").open(newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

t = [float(r["time_s"]) for r in rows]
fig, ax = plt.subplots(figsize=(4.5, 3.2))
ax.scatter(t, [float(r["target_x"]) for r in rows], label="Target", s=24, color='green')
ax.scatter(t, [float(r["hand_x"]) for r in rows], label="Hand", s=24)
ax.set(xlabel="Time (s)", ylabel="Horizontal position (a.u.)", title="Interception timing")
ax.legend(frameon=False)
finish_figure(fig, os.environ["CHART_OUTPUT"])
fig.show()

