import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_09")].iloc[0]
panel_values = values[values.panel_id.eq(panel.panel_id)]

left_label = str(panel.left_label)
right_label = str(panel.right_label)
left_color = str(panel.left_color)
right_color = str(panel.right_color)

left_vals = panel_values[panel_values.group_label.eq(left_label)].sort_values("subject_id")
right_vals = panel_values[panel_values.group_label.eq(right_label)].sort_values("subject_id")

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

n_pairs = min(len(left_vals), len(right_vals))
for i in range(n_pairs):
    ax.plot(
        [0, 1],
        [left_vals.value.iloc[i], right_vals.value.iloc[i]],
        color="0.75",
        linewidth=0.8,
        zorder=1,
    )

ax.scatter(
    [0] * len(left_vals),
    left_vals.value,
    s=18,
    color=left_color,
    edgecolor="white",
    linewidth=0.4,
    zorder=2,
    label=left_label,
)
ax.scatter(
    [1] * len(right_vals),
    right_vals.value,
    s=18,
    color=right_color,
    edgecolor="white",
    linewidth=0.4,
    zorder=2,
    label=right_label,
)

left_mean = left_vals.value.mean()
right_mean = right_vals.value.mean()
ax.scatter(
    [0, 1],
    [left_mean, right_mean],
    s=60,
    marker="D",
    color=[left_color, right_color],
    edgecolor="black",
    linewidth=0.6,
    zorder=3,
)

ax.set_xlim(-0.4, 1.4)
ax.set_xticks([0, 1])
ax.set_xticklabels([left_label, right_label])
ax.set_ylabel(str(panel.ylabel))
ax.set_title(str(panel.title))

p_text = str(panel.p_value)
ax.text(0.5, 1.02, p_text, transform=ax.transAxes, ha="center", va="bottom")

ax.legend(frameon=False, loc="best")

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
