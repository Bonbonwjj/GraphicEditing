import os
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
from studio_style import finish_figure
from projects.human.lib import source_renderer as renderer

project=Path(os.environ['CHART_PROJECT_DIR'])
panels=pd.read_csv(project/'data/direct_panel_metadata.csv')
values=pd.read_csv(project/'data/direct_panel_subject_values.csv')
panel=panels[panels.panel_id.eq('03_obs_vs_nobs_01')].iloc[0]
fig,ax=plt.subplots(figsize=(5.4,4.8))
renderer.draw_panel(ax,panel,values[values.panel_id.eq(panel.panel_id)])
ax.set_position([.34,.23,.60,.66])
finish_figure(fig,os.environ['CHART_OUTPUT'])
