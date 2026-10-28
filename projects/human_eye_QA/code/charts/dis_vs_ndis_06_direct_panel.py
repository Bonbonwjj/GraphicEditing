import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("02_dis_vs_ndis_06")].iloc[0]
panel_values = values[values.panel_id.eq(panel.panel_id)]

left_label = str(panel["left_label"])
right_label = str(panel["right_label"])
left_color = str(panel["left_color"])
right_color = str(panel["right_color"])

# Map the two groups in the subject values to the panel's left/right labels.
groups = list(dict.fromkeys(panel_values["group_label"].tolist()))
if left_label in groups and right_label in groups:
    left_group, right_group = left_label, right_label
elif len(groups) >= 2:
    left_group, right_group = groups[0], groups[1]
else:
    left_group = right_group = groups[0] if groups else None

left_vals = panel_values[panel_values.group_label.eq(left_group)].set_index("subject_id")["value"]
right_vals = panel_values[panel_values.group_label.eq(right_group)].set_index("subject_id")["value"]

subjects = [s for s in left_vals.index if s in right_vals.index]

apply_style()
fig, ax = plt.subplots(figsize=(5.4, 4.8))

# Paired lines between the two conditions per subject.
for s in subjects:
    ax.plot([0, 1], [left_vals[s], right_vals[s]], color="0.75", linewidth=0.8, zorder=1)

ax.scatter([0] * len(subjects), [left_vals[s] for s in subjects], s=18, color=left_color, zorder=2, label=left_label)
ax.scatter([1] * len(subjects), [right_vals[s] for s in subjects], s=18, color=right_color, zorder=2, label=right_label)

ax.set_xlim(-0.4, 1.4)
ax.set_xticks([0, 1])
ax.set_xticklabels([left_label, right_label])
ax.set_ylabel(str(panel["ylabel"]))
ax.set_title(str(panel["title"]), fontsize=9)

p_value = panel["p_value"]
try:
    p_text = f"p = {float(p_value):.3g}"
except (TypeError, ValueError):
    p_text = str(p_value)
ax.text(0.5, 1.02, p_text, transform=ax.transAxes, ha="center", va="bottom", fontsize=8)

ax.legend(frameon=False, fontsize=8, loc="best")
ax.set_position([0.34, 0.23, 0.60, 0.66])

finish_figure(fig, os.environ["CHART_OUTPUT"])
