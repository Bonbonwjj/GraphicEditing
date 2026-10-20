import os
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
from studio_style import finish_figure
from projects.human.lib import source_renderer as renderer

project=Path(os.environ['CHART_PROJECT_DIR'])
metadata=pd.read_csv(project/'data/heatmap_metadata.csv')
renderer.draw_heatmap('baseline_corrected',metadata)
