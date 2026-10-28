import os
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_08")].iloc[0]
pv = values[values.panel_id.eq(panel.panel_id)]

left_label = str(panel.left_label)
right_label = str(panel.right_label)
groups = [left_label, right_label]
colors = [str(panel.left_color), str(panel.right_color)]

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

# Paired subject lines (same subject in both groups)
for _, grp in pv.groupby("subject_id"):
    if len(grp) == 2:
        yl = grp[grp.group_label.eq(left_label)].value
        yr = grp[grp.group_label.eq(right_label)].value
        if len(yl) == 1 and len(yr) == 1:
            ax.plot([0, 1], [yl.iloc[0], yr.iloc[0]], color="0.78", lw=0.8, zorder=1)

# Individual subject points and group means
for i, (g, c) in enumerate(zip(groups, colors)):
    pts = pv[pv.group_label.eq(g)]
    ax.scatter([i] * len(pts), pts.value, s=18, color=c, zorder=2, edgecolors="none")
    mean = pts.value.mean()
    ax.plot([i - 0.15, i + 0.15], [mean, mean], color=c, lw=2.0, zorder=3)

ax.set_xlim(-0.5, 1.5)
ax.set_xticks([0, 1])
ax.set_xticklabels(groups)
ax.set_ylabel(panel.ylabel)
ax.set_title(panel.title)

# Significance annotation from metadata p_value
p = float(panel.p_value)
if p < 0.001:
    stars = "***"
elif p < 0.01:
    stars = "**"
elif p < 0.05:
    stars = "*"
else:
    stars = "n.s."
ax.text(0.5, 1.02, f"p = {p:.3g} ({stars})", transform=ax.transAxes,
        ha="center", va="bottom", fontsize=8)

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
