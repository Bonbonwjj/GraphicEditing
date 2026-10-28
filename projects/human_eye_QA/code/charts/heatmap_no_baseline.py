import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])

metadata = pd.read_csv(project / "data" / "heatmap_metadata.csv")
matrix = pd.read_csv(project / "data" / "heatmap_no_baseline_matrix.csv")

row = metadata[metadata["heatmap_id"] == "no_baseline"].iloc[0]

# Preserve the ordering of dimensions and classes exactly as given in the data file.
dims = matrix["fds_dimension"].drop_duplicates().tolist()
classes = matrix["fixated_class"].drop_duplicates().tolist()
pivot = matrix.pivot(index="fds_dimension", columns="fixated_class", values="mean_value")
pivot = pivot.reindex(index=dims, columns=classes)

values = pivot.values
if bool(row["symmetric"]):
    vmax = np.nanmax(np.abs(values))
    vmin = -vmax
else:
    vmin = np.nanmin(values)
    vmax = np.nanmax(values)

apply_style()

fig, ax = plt.subplots(figsize=(4.0, 3.2))
im = ax.imshow(values, cmap="RdBu_r", vmin=vmin, vmax=vmax, aspect="auto")

ax.set_xticks(range(len(classes)))
ax.set_xticklabels(classes)
ax.set_yticks(range(len(dims)))
ax.set_yticklabels(dims)
ax.set_xlabel("Fixated class")
ax.set_ylabel("FDS dimension")

cbar = fig.colorbar(im, ax=ax)
cbar.set_label(row["colorbar_label"])

finish_figure(fig, os.environ["CHART_OUTPUT"])
