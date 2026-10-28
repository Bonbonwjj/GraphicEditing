import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_05")].iloc[0]
panel_values = values[values.panel_id.eq(panel.panel_id)]

groups = list(dict.fromkeys(panel_values.group_label))
left_label = str(panel.left_label)
right_label = str(panel.right_label)

# Keep the metadata ordering (left group first, right group second) when present.
ordered = [g for g in (left_label, right_label) if g in groups]
ordered += [g for g in groups if g not in ordered]

color_map = {
    left_label: str(panel.left_color),
    right_label: str(panel.right_color),
}

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

rng = np.random.default_rng(0)
positions = np.arange(len(ordered))

for pos, group in zip(positions, ordered):
    vals = panel_values.loc[
        panel_values.group_label.eq(group), "value"
    ].to_numpy(dtype=float)

    color = color_map.get(group, "#4C72B0")

    # Jittered subject-level points.
    jitter = rng.uniform(-0.12, 0.12, size=vals.size)
    ax.scatter(
        np.full(vals.size, pos) + jitter,
        vals,
        s=14,
        color=color,
        alpha=0.55,
        linewidths=0,
        zorder=2,
    )

    # Mean and 95% CI of the mean.
    mean = float(np.mean(vals))
    sd = float(np.std(vals, ddof=1)) if vals.size > 1 else 0.0
    sem = sd / np.sqrt(vals.size) if vals.size > 0 else 0.0
    ci = 1.96 * sem

    ax.errorbar(
        pos,
        mean,
        yerr=ci,
        fmt="o",
        color="black",
        markersize=5,
        capsize=4,
        linewidth=1.2,
        zorder=3,
    )

ax.set_xticks(positions)
ax.set_xticklabels(ordered)
ax.set_ylabel(str(panel.ylabel))
ax.set_title(str(panel.title))

p_value = panel.p_value
try:
    p_text = f"p = {float(p_value):.3g}"
except (TypeError, ValueError):
    p_text = str(p_value)
ax.text(
    0.02,
    0.98,
    p_text,
    transform=ax.transAxes,
    ha="left",
    va="top",
    fontsize=8,
)

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
