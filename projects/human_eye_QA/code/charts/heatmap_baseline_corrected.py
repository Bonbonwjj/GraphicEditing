import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ['CHART_PROJECT_DIR'])

metadata = pd.read_csv(project / 'data' / 'heatmap_metadata.csv')
meta = metadata[metadata['heatmap_id'] == 'baseline_corrected'].iloc[0]
colorbar_label = str(meta['colorbar_label'])
symmetric = bool(meta['symmetric'])

matrix = pd.read_csv(project / 'data' / 'heatmap_baseline_corrected_matrix.csv')

# Preserve the original row/column ordering of the source data.
dim_order = matrix['fds_dimension'].drop_duplicates().tolist()
class_order = matrix['fixated_class'].drop_duplicates().tolist()

pivot = matrix.pivot(index='fds_dimension', columns='fixated_class', values='mean_value')
pivot = pivot.reindex(index=dim_order, columns=class_order)

values = pivot.to_numpy(dtype=float)

apply_style()

fig, ax = plt.subplots(figsize=(4.2, 3.4))

if symmetric:
    vmax = np.nanmax(np.abs(values))
    if not np.isfinite(vmax) or vmax == 0:
        vmax = 1.0
    vmin = -vmax
    cmap = 'RdBu_r'
else:
    vmin = np.nanmin(values)
    vmax = np.nanmax(values)
    cmap = 'viridis'

im = ax.imshow(values, aspect='auto', cmap=cmap, vmin=vmin, vmax=vmax, origin='upper')

cbar = fig.colorbar(im, ax=ax)
cbar.set_label(colorbar_label, fontsize=8)
cbar.ax.tick_params(labelsize=8)

ax.set_xticks(range(len(class_order)))
ax.set_xticklabels(class_order, fontsize=8)
ax.set_yticks(range(len(dim_order)))
ax.set_yticklabels(dim_order, fontsize=8)
ax.set_xlabel('Fixated class', fontsize=8)
ax.set_ylabel('FDS dimension', fontsize=8)

finish_figure(fig, os.environ['CHART_OUTPUT'])
