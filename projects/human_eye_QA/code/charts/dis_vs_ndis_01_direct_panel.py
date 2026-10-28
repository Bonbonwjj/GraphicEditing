import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel_id = "02_dis_vs_ndis_01"
panel = panels[panels.panel_id.eq(panel_id)].iloc[0]
pv = values[values.panel_id.eq(panel_id)].copy()

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

# One row per subject: connect the left and right condition values.
pivot = pv.pivot_table(index="subject_id", columns="group_label", values="value", aggfunc="first")
left_label = str(panel.left_label)
right_label = str(panel.right_label)
left_color = str(panel.left_color)
right_color = str(panel.right_color)

# Map each subject to its group for line coloring (colorblind-friendly palette).
groups = sorted(pv.group_label.astype(str).unique())
palette = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
group_color = {g: palette[i % len(palette)] for i, g in enumerate(groups)}

x_left, x_right = 0.0, 1.0
for subject_id, row in pivot.iterrows():
    if left_label not in row.index or right_label not in row.index:
        continue
    y0, y1 = row[left_label], row[right_label]
    if pd.isna(y0) or pd.isna(y1):
        continue
    g = str(pv.loc[pv.subject_id.eq(subject_id), "group_label"].iloc[0])
    ax.plot([x_left, x_right], [y0, y1], color=group_color[g], lw=1.0, alpha=0.8, zorder=2)
    ax.scatter([x_left], [y0], s=18, color=left_color, edgecolor="white", lw=0.4, zorder=3)
    ax.scatter([x_right], [y1], s=18, color=right_color, edgecolor="white", lw=0.4, zorder=3)

# Group means as thicker markers.
for x, label, color in ((x_left, left_label, left_color), (x_right, right_label, right_color)):
    if label in pivot.columns:
        mean_y = pivot[label].mean()
        ax.scatter([x], [mean_y], s=70, marker="D", color=color, edgecolor="black", lw=0.6, zorder=4)

ax.set_xticks([x_left, x_right])
ax.set_xticklabels([left_label, right_label])
ax.set_xlim(-0.35, 1.35)
ax.set_ylabel(panel.ylabel)

p_raw = panel.p_value
try:
    p_txt = f"p = {float(p_raw):.3g}"
except (TypeError, ValueError):
    p_txt = f"p = {p_raw}"
ax.set_title(f"{panel.title}\n{p_txt}")

handles = [plt.Line2D([], [], color=group_color[g], lw=1.5, label=g) for g in groups]
if handles:
    ax.legend(handles=handles, frameon=False, fontsize=8, loc="best")

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
