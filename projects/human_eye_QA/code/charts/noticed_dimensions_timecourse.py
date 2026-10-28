import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ['CHART_PROJECT_DIR'])
plot_id = '05_obs_vs_disd_noticed_dimensions'

values = pd.read_csv(project / 'data' / 'timecourse_subject_values.csv')
values = values[values['plot_id'] == plot_id].copy()
metadata = pd.read_csv(project / 'data' / 'timecourse_metadata.csv')
meta = metadata[metadata['plot_id'] == plot_id].iloc[0]

apply_style()

fig, ax = plt.subplots(figsize=(7.2, 4.8))

stages = sorted(values['stage_order'].unique())
stage_labels = (
    values.drop_duplicates('stage_order')
    .set_index('stage_order')['stage_label']
    .to_dict()
)

for group_label, g in values.groupby('group_label', sort=False):
    color = g['color'].iloc[0]
    legend_label = g['legend_label'].iloc[0]
    means = g.groupby('stage_order')['value'].mean().reindex(stages)
    sems = g.groupby('stage_order')['value'].sem().reindex(stages)
    ax.errorbar(
        stages,
        means,
        yerr=sems,
        color=color,
        label=legend_label,
        marker='o',
        markersize=3.5,
        linewidth=1.2,
        capsize=2,
    )

ax.set_xticks(stages)
ax.set_xticklabels([str(stage_labels[s]) for s in stages])
ax.set_ylabel(str(meta['ylabel']))

stars = '' if pd.isna(meta['stars']) else str(meta['stars'])
star_stages = '' if pd.isna(meta['star_stages']) else str(meta['star_stages'])
if stars and star_stages:
    ymin, ymax = ax.get_ylim()
    span = ymax - ymin
    y_pos = ymax + 0.05 * span
    for token in star_stages.replace(';', ',').split(','):
        token = token.strip()
        if not token:
            continue
        try:
            stage_val = float(token)
        except ValueError:
            continue
        stage_val = min(stages, key=lambda s: abs(s - stage_val))
        ax.text(stage_val, y_pos, stars, ha='center', va='bottom', fontsize=8)
    ax.set_ylim(ymin, y_pos + 0.12 * span)

ax.legend(frameon=False, fontsize=8)
ax.set_title('Noticed dimensions over time', fontsize=9)

fig.tight_layout(pad=1.4)
finish_figure(fig, os.environ['CHART_OUTPUT'])
