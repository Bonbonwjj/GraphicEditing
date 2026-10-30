# GraphicEditing merged

This clean source tree uses `GraphicEditing-lc` as its base and integrates the
token-saving batch-planning changes from `GraphicEditing`.

Included optimizations:

- AST-based single/multi-figure detection; single-figure imports avoid an LLM call.
- Compact split prompts and non-duplicating repair prompts.
- Bounded tabular schema metadata in split requests.
- Best-fit batch grouping to reduce retransmission of shared source dependencies.
- Compact JSON serialization for preparation model requests.
- Cloud-model data minimization: source code and schema metadata may be sent,
  while original table rows, JSON values, binary data, and chart images remain local.
- On-demand preview, universal/native decomposition, panel editing, cleanup, and
  current UI improvements from `GraphicEditing-lc`.
- Figure-local adapters now expose their exact drawing section, source reference,
  and direct inputs while delegating unrelated computation to the frozen source.
- No-model interactive controls for axes border width/color and legend position/
  label mapping, with normal render validation and version history.

Deliberately excluded from this clean merge:

- user projects and backups;
- API/OAuth/private-project configuration;
- Git and collaboration working copies;
- virtual environments, caches, generated logs, and local font caches.

Create a fresh environment from `requirements.txt`, then run `python launch.py`.

## Data-protection mode

ChatGPT and other configured models may process drawing code and user requests.
Original CSV/TSV/JSON values, binary artifacts, and chart images are never added
to model requests. Models receive only bounded schema metadata such as file name,
column names, format, row count, and content hash. Numeric correctness and final
rendering continue to be checked locally against the complete data.
