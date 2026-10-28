import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ['CHART_PROJECT_DIR'])
panels = pd.read_csv(project / 'data' / 'direct_panel_metadata.csv')
values = pd.read_csv(project / 'data' / 'direct_panel_subject_values.csv')

panel = panels[panels.panel_id.eq('01_obs_vs_disd_01')].iloc[0]
panel_values = values[values.panel_id.eq(panel.panel_id)]

left_label = str(panel['left_label'])
right_label = str(panel['right_label'])
left_color = str(panel['left_color'])
right_color = str(panel['right_color'])

order = [left_label, right_label]
colors = {left_label: left_color, right_label: right_color}

groups = {}
for label in order:
    sub = panel_values[panel_values.group_label.eq(label)]
    groups[label] = sub.sort_values('subject_id')['value'].to_numpy(dtype=float)

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

bp = ax.boxplot([groups[label] for label in order], positions=[0, 1],
                widths=0.4, patch_artist=True, showfliers=True,
                medianprops={'color': 'white', 'linewidth': 1.5},
                boxprops={'linewidth': 1.0},
                whiskerprops={'linewidth': 1.0},
                capprops={'linewidth': 1.0}, zorder=2)
for patch, label in zip(bp['boxes'], order):
    patch.set_facecolor(colors[label])
    patch.set_alpha(0.75)
    patch.set_edgecolor(colors[label])

# paired lines between subjects present in both groups
left_ids = panel_values[panel_values.group_label.eq(left_label)].set_index('subject_id')['value']
right_ids = panel_values[panel_values.group_label.eq(right_label)].set_index('subject_id')['value']
common = left_ids.index.intersection(right_ids.index)
for sid in common:
    ax.plot([0, 1], [left_ids[sid], right_ids[sid]], color='0.75',
            linewidth=0.6, alpha=0.6, zorder=1)

p_value = float(panel['p_value'])
if p_value < 0.001:
    stars = '***'
elif p_value < 0.01:
    stars = '**'
elif p_value < 0.05:
    stars = '*'
else:
    stars = 'ns'
all_values = np.concatenate([groups[label] for label in order])
star_y = all_values.max() + 0.05 * (all_values.max() - all_values.min())
ax.text(0.5, star_y, stars, ha='center', va='bottom', fontsize=12)

ax.set_xticks([0, 1])
ax.set_xticklabels(order)
ax.set_xlim(-0.5, 1.5)
ax.set_ylabel(str(panel['ylabel']))

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ['CHART_OUTPUT'])
