import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from studio_style import apply_style, finish_figure

apply_style()

project = Path(os.environ['CHART_PROJECT_DIR'])
panels = pd.read_csv(project / 'data' / 'direct_panel_metadata.csv')
values = pd.read_csv(project / 'data' / 'direct_panel_subject_values.csv')

panel = panels[panels.panel_id.eq('03_obs_vs_nobs_02')].iloc[0]
panel_values = values[values.panel_id.eq(panel.panel_id)]

# Determine group order: left then right, falling back to order of appearance.
group_labels = []
for label in (panel.left_label, panel.right_label):
    if (panel_values.group_label == label).any() and label not in group_labels:
        group_labels.append(label)
for label in panel_values.group_label:
    if label not in group_labels:
        group_labels.append(label)

colors = [panel.left_color, panel.right_color]

fig, ax = plt.subplots(figsize=(5.4, 4.8))

rng = np.random.default_rng(0)
for i, (label, color) in enumerate(zip(group_labels, colors)):
    vals = panel_values.loc[panel_values.group_label == label, 'value'].to_numpy(dtype=float)
    x_jitter = i + rng.uniform(-0.12, 0.12, size=vals.size)
    ax.scatter(x_jitter, vals, s=14, color=color, alpha=0.65, edgecolors='none', zorder=2)

    mean = float(np.mean(vals))
    sd = float(np.std(vals, ddof=1)) if vals.size > 1 else 0.0
    n = vals.size
    sem = sd / np.sqrt(n) if n > 1 else 0.0
    ci = 1.96 * sem
    ax.errorbar(i, mean, yerr=ci, fmt='o', color=color, markersize=5,
                capsize=4, linewidth=1.2, zorder=3)

# Significance annotation between the two groups.
p_value = float(panel.p_value)
p_text = 'p < 0.001' if p_value < 0.001 else f'p = {p_value:.3f}'
x0, x1 = 0, len(group_labels) - 1
y_all = panel_values.value.to_numpy(dtype=float)
y_min, y_max = float(np.min(y_all)), float(np.max(y_all))
span = y_max - y_min if y_max > y_min else 1.0
bracket_y = y_max + 0.08 * span
ax.plot([x0, x0, x1, x1], [bracket_y - 0.02 * span, bracket_y, bracket_y, bracket_y - 0.02 * span],
        color='black', linewidth=1.0)
ax.text((x0 + x1) / 2, bracket_y + 0.015 * span, p_text,
        ha='center', va='bottom', fontsize=8)

ax.set_xticks(range(len(group_labels)))
ax.set_xticklabels(group_labels)
ax.set_xlim(-0.5, len(group_labels) - 0.5)
ax.set_ylim(y_min - 0.08 * span, bracket_y + 0.10 * span)
ax.set_ylabel(panel.ylabel)
ax.set_title(panel.title, fontsize=9)

ax.set_position([.34, .23, .60, .66])
finish_figure(fig, os.environ['CHART_OUTPUT'])
