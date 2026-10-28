import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure
from projects.human.lib import source_renderer as renderer

project = Path(os.environ["CHART_PROJECT_DIR"])

panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_07")].iloc[0]

apply_style()
fig, ax = plt.subplots(figsize=(5.4, 4.8))
renderer.draw_panel(ax, panel, values[values.panel_id.eq(panel.panel_id)])
ax.set_position([0.34, 0.23, 0.60, 0.66])

finish_figure(fig, os.environ["CHART_OUTPUT"])
