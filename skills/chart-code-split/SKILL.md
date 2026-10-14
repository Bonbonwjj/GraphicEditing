---
name: chart-code-split
description: Split uploaded Python plotting programs into independent Chart Studio chart scripts. Use when one source file may create multiple figures or outputs and each result must become separately editable.
---

# Chart Code Split

Turn the supplied source into one standalone Python script per intended figure. Preserve the scientific meaning, calculations, labels, ordering, and data selection. Do not invent columns, values, or charts.

Return exactly one JSON object and no commentary:

```json
{"charts":[{"name":"short_snake_case_name","code":"complete Python source"}]}
```

Each `code` value must:

- create exactly one intended figure;
- read only the supplied project data below `Path(os.environ["CHART_PROJECT_DIR"]) / "data"`;
- write exactly once to `os.environ["CHART_OUTPUT"]`;
- run without depending on another generated chart script;
- avoid network access, subprocesses, shell commands, dynamic code execution, secrets, and interactive `show()` calls.

If the original source creates one figure, return one normalized chart. If figure boundaries are ambiguous, prefer the smallest faithful split supported by explicit save/show/figure calls. Never return an empty `charts` list.
