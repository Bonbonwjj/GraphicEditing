---
name: chart-package-import
description: Convert uploaded Python plotting code and tabular data into a Chart Studio project. Use when code and data must be grouped by project, split into independently editable charts, or normalized to Chart Studio paths and output conventions.
---

# Chart Package Import

Create one project per supplied project name. Preserve uploaded source under `data/uploads/<project-id>/` and generate editable output under `projects/<project-id>/`.

Inventory Python and data files, parse Python without executing it, and inspect CSV headers. Reject path traversal, unsupported types, missing project names, duplicate projects, and oversized files.

Prefer a package-specific adapter. Otherwise treat each plotting file as a chart candidate, copy tabular inputs, and normalize it to read from `CHART_PROJECT_DIR/data` and write exactly one artifact to `CHART_OUTPUT`. Split multi-output programs into one chart per output and retain shared helpers under project-local `lib/`.

Parse every generated chart and render it before reporting success. Return per-file errors instead of claiming failed charts were converted.

Read [references/project-schema.md](references/project-schema.md) when creating or validating output.
