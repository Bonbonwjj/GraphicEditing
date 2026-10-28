import os
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
from studio_style import apply_style, finish_figure

project = Path(os.environ["CHART_PROJECT_DIR"])
panels = pd.read_csv(project / "data" / "direct_panel_metadata.csv")
values = pd.read_csv(project / "data" / "direct_panel_subject_values.csv")

panel = panels[panels.panel_id.eq("01_obs_vs_disd_04")].iloc[0]
pv = values[values.panel_id.eq(panel.panel_id)]

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

left_label = str(panel.left_label)
right_label = str(panel.right_label)
left_color = str(panel.left_color)
right_color = str(panel.right_color)

# Reshape subject values to paired (wide) form: one row per subject,
# one column per group label.
wide = pv.pivot_table(index="subject_id", columns="group_label", values="value")
wide = wide.reindex(columns=[left_label, right_label])
wide = wide.dropna(how="any")

x_left, x_right = 0.0, 1.0

# Paired subject lines
for _, row in wide.iterrows():
    ax.plot([x_left, x_right], [row[left_label], row[right_label]],
            color="0.75", linewidth=0.8, zorder=1)

# Group point clouds
ax.scatter([x_left] * len(wide), wide[left_label], s=18, color=left_color,
           edgecolors="white", linewidths=0.4, zorder=2, label=left_label)
ax.scatter([x_right] * len(wide), wide[right_label], s=18, color=right_color,
           edgecolors="white", linewidths=0.4, zorder=2, label=right_label)

# Group means
ax.plot([x_left - 0.08, x_left + 0.08],
        [wide[left_label].mean()] * 2, color="black", linewidth=1.4, zorder=3)
ax.plot([x_right - 0.08, x_right + 0.08],
        [wide[right_label].mean()] * 2, color="black", linewidth=1.4, zorder=3)

# Significance annotation from the panel metadata p-value
p_value = float(panel.p_value)
if p_value < 0.001:
    p_text = "p < 0.001"
else:
    p_text = "p = {:.3f}".format(p_value)
ax.text(0.5, 1.02, p_text, transform=ax.transAxes,
        ha="center", va="bottom", fontsize=8)

ax.set_xlim(-0.4, 1.4)
ax.set_xticks([x_left, x_right])
ax.set_xticklabels([left_label, right_label])
ax.set_ylabel(str(panel.ylabel))
ax.set_title(str(panel.title), fontsize=9)

ax.set_position([0.34, 0.23, 0.60, 0.66])
finish_figure(fig, os.environ["CHART_OUTPUT"])
