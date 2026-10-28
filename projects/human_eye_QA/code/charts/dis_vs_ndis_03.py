import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_03")].iloc[0]
sub = values[values.panel_id.eq(panel.panel_id)]

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

groups = [panel.left_label, panel.right_label]
colors = [panel.left_color, panel.right_color]
positions = [0, 1]

# Connect paired subjects across the two groups
for sid, g in sub.groupby("subject_id"):
    if len(g) == 2:
        ys = [g[g.group_label.eq(gl)].value.iloc[0] for gl in groups]
        ax.plot(positions, ys, color="0.78", lw=0.8, zorder=1)

# Subject-level points and group mean +/- SEM
for pos, gl, c in zip(positions, groups, colors):
    pts = sub[sub.group_label.eq(gl)]
    ax.scatter(
        [pos] * len(pts),
        pts.value,
        s=18,
        color=c,
        edgecolor="white",
        linewidth=0.4,
        zorder=2,
    )
    mean = pts.value.mean()
    sem = pts.value.std(ddof=1) / len(pts) ** 0.5
    ax.errorbar(
        pos,
        mean,
        yerr=sem,
        color="black",
        capsize=3,
        marker="s",
        markersize=4,
        zorder=3,
    )

ax.set_xlim(-0.5, 1.5)
ax.set_xticks(positions)
ax.set_xticklabels(groups)
ax.set_ylabel(panel.ylabel)
ax.set_title(panel.title)

try:
    p_text = f"p = {float(panel.p_value):.3g}"
except (TypeError, ValueError):
    p_text = str(panel.p_value)
ax.text(0.5, 1.0, p_text, transform=ax.transAxes, ha="center", va="bottom")

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
