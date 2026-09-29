"""Correlation between target and hand positions."""
import csv
import os
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
from studio_style import apply_style, finish_figure

apply_style()
project = Path(os.environ["CHART_PROJECT_DIR"])
with (project / "data" / "trajectories.csv").open(newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

target_x = [float(r["target_x"]) for r in rows]
target_y = [float(r["target_y"]) for r in rows]
hand_x = [float(r["hand_x"]) for r in rows]
hand_y = [float(r["hand_y"]) for r in rows]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.5, 3.2))

# X position correlation
corr_x = np.corrcoef(target_x, hand_x)[0,1]
ax1.scatter(target_x, hand_x, s=20, alpha=0.7)
ax1.plot([min(target_x), max(target_x)], [min(target_x), max(target_x)], 'k--', alpha=0.5, linewidth=1)
ax1.set(xlabel="Target X position (a.u.)", ylabel="Hand X position (a.u.)",
       title=f"X position correlation\n(r = {corr_x:.3f})")

# Y position correlation
corr_y = np.corrcoef(target_y, hand_y)[0,1]
ax2.scatter(target_y, hand_y, s=20, alpha=0.7)
ax2.plot([min(target_y), max(target_y)], [min(target_y), max(target_y)], 'k--', alpha=0.5, linewidth=1)
ax2.set(xlabel="Target Y position (a.u.)", ylabel="Hand Y position (a.u.)",
       title=f"Y position correlation\n(r = {corr_y:.3f})")

plt.tight_layout()
finish_figure(fig, os.environ["CHART_OUTPUT"])
