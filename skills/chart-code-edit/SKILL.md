---
name: chart-code-edit
description: Modify one existing Chart Studio Python chart from a natural-language request while preserving its data and unrelated visual behavior.
---

# Chart Code Edit

Edit the supplied complete Python chart. Make the smallest change that fully satisfies the request and preserve calculations, data filters, labels, and unrelated styling.

Return only the complete replacement Python source, without Markdown fences or explanation.

Requirements:

- use only files and columns present in the supplied data inventory;
- preserve `CHART_PROJECT_DIR` for project data and `CHART_OUTPUT` for the single output;
- keep the script deterministic and non-interactive;
- do not add network access, subprocesses, shell commands, dynamic code execution, credential access, or new dependencies;
- do not fabricate data when the request cannot be supported by the inventory.
