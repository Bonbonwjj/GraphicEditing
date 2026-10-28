import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_19")].iloc[0]
pv = values[values.panel_id.eq(panel.panel_id)]

left_label = str(panel.left_label)
right_label = str(panel.right_label)
left_color = str(panel.left_color)
right_color = str(panel.right_color)

left = pv[pv.group_label.eq(left_label)].set_index("subject_id")["value"].dropna()
right = pv[pv.group_label.eq(right_label)].set_index("subject_id")["value"].dropna()

apply_style()
fig, ax = plt.subplots(figsize=(5.4, 4.8))

# Connect subjects measured in both groups
common = left.index.intersection(right.index)
for sid in common:
    ax.plot([0, 1], [left.loc[sid], right.loc[sid]], color="0.78", lw=0.8, zorder=1)

# Subject-level points with small deterministic jitter
rng = np.random.default_rng(0)
jitter = 0.04
for x, vals, color in ((0, left, left_color), (1, right, right_color)):
    xs = x + rng.uniform(-jitter, jitter, len(vals))
    ax.scatter(xs, vals.to_numpy(), s=14, color=color, edgecolors="none", zorder=2)
    ax.hlines(vals.mean(), x - 0.12, x + 0.12, color="black", lw=1.4, zorder=3)

ax.set_xlim(-0.5, 1.5)
ax.set_xticks([0, 1])
ax.set_xticklabels([left_label, right_label])
ax.set_ylabel(panel.ylabel)
ax.set_title(panel.title)

# Significance annotation from the panel's p-value
p = float(panel.p_value)
if p < 0.001:
    stars = "***"
elif p < 0.01:
    stars = "**"
elif p < 0.05:
    stars = "*"
else:
    stars = "n.s."
y_top = max(left.max(), right.max())
ax.text(0.5, y_top, f"{stars}\np = {p:.3g}", ha="center", va="bottom", fontsize=8)

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
