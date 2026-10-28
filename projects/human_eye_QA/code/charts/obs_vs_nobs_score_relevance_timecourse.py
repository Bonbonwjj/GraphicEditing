import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
values = pd.read_csv(project / "data" / "timecourse_subject_values.csv")
metadata = pd.read_csv(project / "data" / "timecourse_metadata.csv")

plot_id = "03_obs_vs_nobs_score_relevance"
meta = metadata[metadata["plot_id"] == plot_id].iloc[0]
sub = values[values["plot_id"] == plot_id].copy()

stages = (
    sub[["stage_order", "stage_label"]]
    .drop_duplicates()
    .sort_values("stage_order")
    .reset_index(drop=True)
)
x = np.arange(len(stages))
stage_labels = stages["stage_label"].tolist()

groups = sub[["group_label", "color", "legend_label"]].drop_duplicates()

apply_style()
fig, ax = plt.subplots(figsize=(5.4, 4.8))

for _, g in groups.iterrows():
    gvals = sub[sub["group_label"] == g["group_label"]]
    means = []
    sems = []
    for _, s in stages.iterrows():
        v = gvals[gvals["stage_order"] == s["stage_order"]]["value"].to_numpy()
        means.append(float(np.mean(v)))
        sems.append(float(np.std(v, ddof=1) / np.sqrt(len(v))) if len(v) > 1 else 0.0)
    ax.errorbar(
        x,
        means,
        yerr=sems,
        color=g["color"],
        label=g["legend_label"],
        marker="o",
        markersize=3,
        linewidth=1.2,
        capsize=2,
    )

ax.set_xticks(x)
ax.set_xticklabels(stage_labels)
ax.set_ylabel(meta["ylabel"])

stars = str(meta["stars"]) if pd.notna(meta["stars"]) else ""
star_stages_raw = str(meta["star_stages"]) if pd.notna(meta["star_stages"]) else ""
if stars.strip() and star_stages_raw.strip():
    star_stages = [s.strip() for s in star_stages_raw.split(";") if s.strip()]
    ymin, ymax = ax.get_ylim()
    span = ymax - ymin
    if ymax > 0:
        ax.set_ylim(top=ymax + 0.10 * span)
        star_y = ymax + 0.04 * span
    else:
        star_y = ymax
    for label in star_stages:
        if label in stage_labels:
            ax.text(stage_labels.index(label), star_y, stars, ha="center", va="bottom", fontsize=8)

ax.legend(frameon=False, fontsize=8)
fig.tight_layout(pad=1.4)
finish_figure(fig, os.environ["CHART_OUTPUT"])
