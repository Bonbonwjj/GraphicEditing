---
name: chart-code-repair
description: Repair a rejected chart-code or chart-splitting response using a concrete parser, policy, or rendering error. Use only after an earlier model result fails validation.
---

# Chart Code Repair

Correct only the supplied validation failure while retaining the original request and all already-correct behavior. Treat the validator error as authoritative. Do not evade a safety rule or remove required chart content merely to pass validation.

Use the output format requested by the original task: complete raw Python for a chart edit, or one JSON object for chart splitting. Return no explanation, Markdown fence, or extra keys.
