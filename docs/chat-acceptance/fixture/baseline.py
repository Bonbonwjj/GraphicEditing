import os
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from shared_draw import draw_series
project = Path(os.environ['CHART_PROJECT_DIR'])
data = pd.read_csv(project / 'data' / 'plot.csv')
fig, ax = plt.subplots(figsize=(6, 4))
draw_series(ax, data, 'Obs', '#336699')
draw_series(ax, data, 'Control', '#cc6600')
ax.set_xlabel('Time (s)', fontsize=12)
ax.set_ylabel('Score', fontsize=12)
ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), fontsize=10)
fig.subplots_adjust(right=0.72, left=0.14, bottom=0.18)
fig.savefig(os.environ['CHART_OUTPUT'], dpi=120)
plt.close(fig)
