import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure

apply_style()

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("01_obs_vs_disd_02")].iloc[0]
sub = values[values.panel_id.eq(panel.panel_id)].copy()

left_label = str(panel.left_label)
right_label = str(panel.right_label)
left_color = str(panel.left_color)
right_color = str(panel.right_color)

left = sub[sub.group_label.eq(left_label)].set_index("subject_id")["value"]
right = sub[sub.group_label.eq(right_label)].set_index("subject_id")["value"]

fig, ax = plt.subplots(figsize=(5.4, 4.8))

x_left, x_right = 0.0, 1.0

# Paired subject lines (subjects present in both groups)
shared = left.index.intersection(right.index)
for sid in shared:
    ax.plot([x_left, x_right], [left[sid], right[sid]],
            color="0.75", linewidth=0.8, zorder=1)

# Group points
ax.scatter([x_left] * len(left), left.values, s=18, color=left_color,
           zorder=2, label=left_label)
ax.scatter([x_right] * len(right), right.values, s=18, color=right_color,
           zorder=2, label=right_label)

# Group means
ax.plot([x_left - 0.08, x_left + 0.08], [left.mean(), left.mean()],
        color=left_color, linewidth=1.6, zorder=3)
ax.plot([x_right - 0.08, x_right + 0.08], [right.mean(), right.mean()],
        color=right_color, linewidth=1.6, zorder=3)

ax.set_xlim(-0.4, 1.4)
ax.set_xticks([x_left, x_right])
ax.set_xticklabels([left_label, right_label])
ax.set_ylabel(str(panel.ylabel))

# Significance stars above the chart (derived from the existing p-value)
p_value = float(panel.p_value)
if p_value < 0.001:
    star_text = "***"
elif p_value < 0.01:
    star_text = "**"
elif p_value < 0.05:
    star_text = "*"
else:
    star_text = "n.s."
ax.text(0.5, 1.02, star_text, transform=ax.transAxes,
        ha="center", va="bottom", fontsize=10)

ax.legend(frameon=False, fontsize=8, loc="best")

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
