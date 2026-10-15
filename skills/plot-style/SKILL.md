---
name: plot-style
description: Shared rules for reproducible scientific charts in this workspace.
---

# Plot style

Each chart is a Python file under `projects/<project>/charts/`. Read tabular inputs only from the project's `data/*.csv` files. Save the final figure to the path in `CHART_OUTPUT`; do not call `plt.show()`.

Use `from studio_style import apply_style, finish_figure` and call `apply_style()` before creating a plot. The default body, tick, and legend text is 8 pt; labels are 8 pt; titles are 9 pt. Use SVG or PDF for publication export and PNG for preview. Keep axes readable, label quantities and units, and avoid redundant decoration. Use colorblind-friendly colors and a white background.

Keep plotting code deterministic. Resolve data paths using `CHART_PROJECT_DIR`, never the current working directory. Do not download data, execute shell commands, or read secrets from the plotting script.

When editing a chart, preserve its data columns and intended scientific meaning. If the requested change requires missing data, explain the missing column rather than inventing values.
