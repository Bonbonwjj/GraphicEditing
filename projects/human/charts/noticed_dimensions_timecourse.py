import os
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
from studio_style import finish_figure
from projects.human.lib import source_renderer as renderer

project=Path(os.environ['CHART_PROJECT_DIR'])
values=pd.read_csv(project/'data/timecourse_subject_values.csv')
metadata=pd.read_csv(project/'data/timecourse_metadata.csv')
fig,ax=plt.subplots(figsize=(7.2, 4.8))
renderer.draw_timecourse(ax,'05_obs_vs_disd_noticed_dimensions',values,metadata)
fig.tight_layout(pad=1.4)
finish_figure(fig,os.environ['CHART_OUTPUT'])
