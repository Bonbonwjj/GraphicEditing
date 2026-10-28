import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_14")].iloc[0]
sub = values[values.panel_id.eq(panel.panel_id)]

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

groups = [
    (panel["left_label"], panel["left_color"]),
    (panel["right_label"], panel["right_color"]),
]

rng = np.random.default_rng(0)
x_positions = [0, 1]

for x, (label, color) in zip(x_positions, groups):
    vals = sub[sub.group_label.eq(label)]["value"].to_numpy()
    if vals.size == 0:
        continue
    jitter = rng.uniform(-0.12, 0.12, size=vals.size)
    ax.scatter(
        x + jitter,
        vals,
        s=14,
        color=color,
        alpha=0.75,
        edgecolors="none",
        zorder=2,
    )
    mean = float(np.mean(vals))
    sd = float(np.std(vals, ddof=1)) if vals.size > 1 else 0.0
    ax.errorbar(
        x,
        mean,
        yerr=sd,
        fmt="o",
        color="black",
        markersize=4,
        capsize=3,
        linewidth=1,
        zorder=3,
    )

ax.set_xticks(x_positions)
ax.set_xticklabels([g[0] for g in groups])
ax.set_xlim(-0.5, 1.5)
ax.set_ylabel(panel["ylabel"])
ax.set_title(panel["title"])

p_value = float(panel["p_value"])
if p_value < 0.001:
    stars = "***"
elif p_value < 0.01:
    stars = "**"
elif p_value < 0.05:
    stars = "*"
else:
    stars = "ns"

y_min, y_max = ax.get_ylim()
span = y_max - y_min
bar_y = y_max + 0.06 * span
ax.plot([0, 1], [bar_y, bar_y], color="black", linewidth=1)
ax.text(0.5, bar_y + 0.02 * span, stars, ha="center", va="bottom")
ax.set_ylim(y_min, y_max + 0.18 * span)

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
