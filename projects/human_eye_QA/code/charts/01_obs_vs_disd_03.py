import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure

apply_style()

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("01_obs_vs_disd_03")].iloc[0]
panel_values = values[values.panel_id.eq(panel.panel_id)]

left_label = str(panel["left_label"])
right_label = str(panel["right_label"])
left_color = str(panel["left_color"])
right_color = str(panel["right_color"])

left_vals = panel_values[panel_values.group_label.eq(left_label)].set_index("subject_id")["value"]
right_vals = panel_values[panel_values.group_label.eq(right_label)].set_index("subject_id")["value"]

# Subjects observed in both groups define the paired connections.
shared = left_vals.index.intersection(right_vals.index)
left_only = left_vals.index.difference(right_vals.index)
right_only = right_vals.index.difference(left_vals.index)

fig, ax = plt.subplots(figsize=(5.4, 4.8))

x_left, x_right = 0.0, 1.0

# Paired subjects: connecting lines plus endpoint markers.
for subject in shared:
    ax.plot(
        [x_left, x_right],
        [left_vals[subject], right_vals[subject]],
        color="0.75",
        linewidth=0.8,
        zorder=1,
    )

jitter = 0.015
rng_positions = {"left": [], "right": []}

def scatter_side(subjects, x, color, side):
    xs, ys = [], []
    for i, subject in enumerate(subjects):
        # Deterministic small jitter to reduce overplotting.
        offset = ((i % 5) - 2) * jitter
        xs.append(x + offset)
        ys.append((left_vals if side == "left" else right_vals)[subject])
    ax.scatter(xs, ys, s=14, color=color, edgecolors="white", linewidths=0.3, zorder=2)

scatter_side(shared, x_left, left_color, "left")
scatter_side(shared, x_right, right_color, "right")
scatter_side(list(left_only), x_left, left_color, "left")
scatter_side(list(right_only), x_right, right_color, "right")

ax.set_xlim(-0.35, 1.35)
ax.set_xticks([x_left, x_right])
ax.set_xticklabels([left_label, right_label])
ax.tick_params(axis="x", length=0)

ax.set_ylabel(str(panel["ylabel"]))
ax.set_title(str(panel["title"]), fontsize=9)

# Significance annotation between the two groups.
p_value = float(panel["p_value"])
if p_value < 0.001:
    p_text = "p < 0.001"
else:
    p_text = f"p = {p_value:.3f}"
ax.text(0.5, 1.02, p_text, transform=ax.transAxes, ha="center", va="bottom", fontsize=8)

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
