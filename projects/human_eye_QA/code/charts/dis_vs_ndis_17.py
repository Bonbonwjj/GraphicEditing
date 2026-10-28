import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])

panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_17")].iloc[0]
data = values[values.panel_id.eq(panel.panel_id)]

left_label = str(panel.left_label)
right_label = str(panel.right_label)
left_color = str(panel.left_color)
right_color = str(panel.right_color)

# Fall back to the observed group labels if metadata labels do not match.
observed = list(dict.fromkeys(data.group_label.tolist()))
if left_label not in observed and len(observed) >= 2:
    left_label, right_label = observed[0], observed[1]

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

left = data[data.group_label.eq(left_label)].set_index("subject_id")["value"]
right = data[data.group_label.eq(right_label)].set_index("subject_id")["value"]

# Light lines connecting paired subjects across the two conditions.
common = left.index.intersection(right.index)
for sid in common:
    ax.plot([0, 1], [left[sid], right[sid]], color="0.78", lw=0.8, zorder=1)

for x, label, color in ((0.0, left_label, left_color), (1.0, right_label, right_color)):
    sub = data[data.group_label.eq(label)]
    ax.scatter([x] * len(sub), sub["value"], s=18, color=color,
               edgecolors="none", zorder=2)
    mean = sub["value"].mean()
    ax.scatter([x], [mean], s=60, marker="D", color=color,
               edgecolors="black", linewidths=0.5, zorder=3)

ax.set_xlim(-0.5, 1.5)
ax.set_xticks([0, 1])
ax.set_xticklabels([left_label, right_label])
ax.set_ylabel(panel.ylabel)
ax.set_title(panel.title)

p = float(panel.p_value) if pd.notna(panel.p_value) else float("nan")
if pd.notna(p):
    ptxt = "p < 0.001" if p < 0.001 else f"p = {p:.3f}"
    ax.text(0.5, 1.02, ptxt, transform=ax.transAxes,
            ha="center", va="bottom", fontsize=8)

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
