# Large local inputs

plot_data may contain only headers or bounded samples. source_row_count=null means
unknown. Hashes identify complete files; sample length is never the full sample size.

For palette, linewidth, markers, legends and typography, preserve the full local
reader and adjust existing artists. Never embed sampled rows as replacement arrays.

Value-dependent edits use complete arrays/readers in the local code. Never compute
means, fits, filters, distributions or significance from prompt samples. Request the
reader/grouping implementation if unavailable and identify the exact missing input.
Do not ask users to upload gigabytes just because the prompt contains a sample.

Describe actual input paths, columns/keys and roles; a complete hash alone does not
establish which columns are plotted or make a sampled table complete.

Use exact plot_data.path values for references, including their snapshot prefix.
For the host's customize-only preserve_existing route, raw rows and per-file schemas
may be omitted entirely: keep inherited readers untouched and return an empty
reference list with data_access:preserve_existing. Do not manufacture missing paths,
column names or hashes. If the task needs numeric input changes, request the relevant
implementation context so the host can restore data schemas on the normal route.
