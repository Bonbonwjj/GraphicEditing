import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from studio_style import apply_style, finish_figure

apply_style()

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("01_obs_vs_disd_06")].iloc[0]
panel_values = values[values.panel_id.eq(panel.panel_id)]

left_label = str(panel["left_label"])
right_label = str(panel["right_label"])
left_color = str(panel["left_color"])
right_color = str(panel["right_color"])

groups = [
    (left_label, left_color, 0),
    (right_label, right_color, 1),
]

fig, ax = plt.subplots(figsize=(5.4, 4.8))

rng = np.random.default_rng(0)

for label, color, x in groups:
    vals = panel_values[panel_values.group_label.eq(label)]["value"].to_numpy(dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        continue
    jitter = rng.uniform(-0.12, 0.12, size=vals.size)
    ax.scatter(
        np.full(vals.size, x) + jitter,
        vals,
        s=14,
        color=color,
        alpha=0.65,
        linewidths=0,
        zorder=2,
    )
    mean = float(np.mean(vals))
    sd = float(np.std(vals, ddof=1)) if vals.size > 1 else 0.0
    sem = sd / np.sqrt(vals.size) if vals.size > 0 else 0.0
    ax.errorbar(
        x,
        mean,
        yerr=sem,
        fmt="o",
        markersize=5,
        color=color,
        ecolor="black",
        elinewidth=1.0,
        capsize=3,
        zorder=3,
    )

ax.set_xticks([0, 1])
ax.set_xticklabels([left_label, right_label])
ax.set_xlim(-0.5, 1.5)
ax.set_ylabel(str(panel["ylabel"]))
ax.set_title(str(panel["title"]), fontsize=9)

p_value = panel["p_value"]
try:
    p_text = f"p = {float(p_value):.3g}"
except (TypeError, ValueError):
    p_text = str(p_value)
ax.text(0.5, 1.02, p_text, transform=ax.transAxes, ha="center", va="bottom", fontsize=8)

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
