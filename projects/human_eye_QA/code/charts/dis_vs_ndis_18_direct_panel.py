import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_18")].iloc[0]
sub = values[values.panel_id.eq(panel.panel_id)]

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

left = sub[sub.group_label.eq(panel.left_label)].set_index("subject_id")["value"]
right = sub[sub.group_label.eq(panel.right_label)].set_index("subject_id")["value"]
subjects = left.index.intersection(right.index)

x0, x1 = 0.0, 1.0
for s in subjects:
    ax.plot([x0, x1], [left[s], right[s]], color="0.78", lw=0.8, zorder=1)

ax.scatter([x0] * len(subjects), left[subjects].values, s=18,
           color=panel.left_color, zorder=2)
ax.scatter([x1] * len(subjects), right[subjects].values, s=18,
           color=panel.right_color, zorder=2)

ax.plot([x0, x1], [left[subjects].mean(), right[subjects].mean()],
        color="black", lw=1.5, zorder=3)

ax.set_xticks([x0, x1])
ax.set_xticklabels([panel.left_label, panel.right_label])
ax.set_xlim(-0.4, 1.4)
ax.set_ylabel(panel.ylabel)
ax.set_title(panel.title)

if pd.notna(panel.p_value):
    ax.text(0.5, 1.02, f"p = {float(panel.p_value):.3g}",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=8)

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
