import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_13")].iloc[0]
pv = values[values.panel_id.eq(panel.panel_id)]

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

groups = [str(panel.left_label), str(panel.right_label)]
colors = [str(panel.left_color), str(panel.right_color)]

rng = np.random.default_rng(0)
for i, (group, color) in enumerate(zip(groups, colors)):
    gv = pv[pv.group_label.eq(group)].sort_values("subject_id")["value"].to_numpy(dtype=float)
    x = np.full(gv.size, i, dtype=float) + rng.uniform(-0.08, 0.08, gv.size)
    ax.scatter(x, gv, s=14, color=color, alpha=0.75, edgecolors="none", zorder=2)
    mean = float(np.mean(gv))
    sd = float(np.std(gv, ddof=1)) if gv.size > 1 else 0.0
    ax.errorbar(i, mean, yerr=sd, fmt="o", color=color, markersize=5,
                capsize=3, linewidth=1.2, zorder=3)

ax.set_xticks([0, 1])
ax.set_xticklabels(groups)
ax.set_xlim(-0.5, 1.5)
ax.set_ylabel(str(panel.ylabel))
ax.set_title(str(panel.title))
try:
    p_text = f"p = {float(panel.p_value):.3g}"
except (TypeError, ValueError):
    p_text = str(panel.p_value)
ax.text(0.5, 1.02, p_text, transform=ax.transAxes, ha="center", va="bottom")

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
