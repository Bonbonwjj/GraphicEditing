import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("03_obs_vs_nobs_01")].iloc[0]
pv = values[values.panel_id.eq(panel.panel_id)]

groups = [panel.left_label, panel.right_label]
colors = [panel.left_color, panel.right_color]

apply_style()
fig, ax = plt.subplots(figsize=(5.4, 4.8))

# Paired subject lines across the two conditions
wide = pv.pivot_table(index="subject_id", columns="group_label", values="value")
for _, row in wide.iterrows():
    if row.notna().all():
        ax.plot([0, 1], row.values, color="0.78", lw=0.8, zorder=1)

# Individual subject values and group means
for i, (g, c) in enumerate(zip(groups, colors)):
    gv = pv[pv.group_label.eq(g)]["value"].dropna()
    ax.scatter([i] * len(gv), gv, s=18, color=c, zorder=2,
               edgecolor="white", linewidth=0.3)
    ax.scatter([i], [gv.mean()], marker="D", s=30, color=c, zorder=3,
               edgecolor="black", linewidth=0.5)

ax.set_xlim(-0.5, 1.5)
ax.set_xticks([0, 1])
ax.set_xticklabels(groups)
ax.set_ylabel(panel.ylabel)
ax.set_title(panel.title)
try:
    p_txt = f"p = {float(panel.p_value):.3g}"
except (TypeError, ValueError):
    p_txt = str(panel.p_value)
ax.annotate(p_txt, xy=(0.5, 1.0), xycoords="axes fraction",
            ha="center", va="bottom")

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
