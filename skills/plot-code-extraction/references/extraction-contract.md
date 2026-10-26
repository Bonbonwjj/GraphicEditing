# Plot-data extraction contract

Read this reference when producing `<source_stem>_export.py`, `render_plot.py`, or validating a returned plot-data package.

## Package boundary

The plot-data package is a read-only handoff between scientific processing and presentation. It contains only the values and local assets required to reproduce declared figures. It does not contain executable Python, arbitrary pickles, credentials, absolute source paths, or a copy of the raw-data tree.

Recommended layout:

```text
plot-data/
├── manifest.json
├── tables/
├── arrays/
├── metadata/
├── assets/
└── validation/
```

The generated renderer remains a separate reviewed source file. The package may be stored as a directory or a lossless archive of this layout.

## Manifest

`manifest.json` is UTF-8 JSON and contains at least:

```json
{
  "schema_version": "1.0",
  "producer": {
    "program": "analysis_export.py",
    "source_sha256": "hex digest",
    "python": "major.minor.micro"
  },
  "figures": [
    {
      "figure_id": "eta_summary",
      "renderer": "render_eta_summary",
      "artifacts": ["tables/eta.parquet", "metadata/eta.json"],
      "expected_outputs": 1
    }
  ],
  "artifacts": [
    {
      "path": "tables/eta.parquet",
      "format": "parquet",
      "sha256": "hex digest",
      "bytes": 1234,
      "role": "plot_values"
    }
  ],
  "validation": {
    "plot_input_reference": "validation/plot-inputs.json",
    "numeric_rtol": 0.0,
    "numeric_atol": 0.0
  }
}
```

All paths are normalized relative POSIX paths below the package root. Reject absolute paths, `..`, duplicate normalized paths, symlinks, unsupported formats, missing artifacts, size mismatches, and hash mismatches. Extra undeclared files are not renderer inputs.

`source_sha256` binds the package to the generated export program or to a host-supplied source-set digest. If several sources determine the result, include a sorted `source_files` array of relative path and SHA-256 pairs.

## Serialization

Choose a safe, lossless representation that preserves the values consumed by plotting:

- tables: Parquet when available; CSV is an interoperable fallback and must record encoding, delimiter, column order, dtypes, index handling, and missing-value representation;
- dense numeric arrays: NPZ with `allow_pickle=False` on read;
- scalars, strings, labels, parameters, and mappings: JSON;
- local raster assets: PNG, JPEG, or WebP;
- local vector assets: SVG only when the platform's existing SVG safety policy permits it.

Do not use pickle, dill, joblib object serialization, Python source serialization, or object-dtype NPZ arrays. Preserve categorical order, time zones, timedeltas, NaN/inf semantics, array shape, numeric dtype when material, table column order, and stable IDs.

Separate packages by run or logical group when that keeps upload size and figure selection manageable. Do not shard a single logical array or table unless the renderer contract declares the shards and their deterministic order.

## Minimum dependency closure

For each figure, trace backwards from explicit and implicit output sites such as `savefig`, `show`, returned `Figure` objects, and project-specific save helpers. Capture every value that affects visible artists or their meaning, including:

- plotted coordinates and matrices;
- grouping, ordering, facets, and category labels;
- error bars, intervals, sample sizes, p-values, and annotation positions;
- axis limits, tick values, units, transforms, normalization bounds, and color mapping inputs;
- deterministic random state used for visible jitter or bootstrap presentation;
- local images, masks, geometry, or font-independent path data required by the figure.

Do not capture values used only by unrelated analysis branches, logging, caches, non-plotted reports, or later raw-data exploration. Shared dependencies may be stored once and referenced by several figures.

Static analysis is insufficient when dependencies are created dynamically, retrieved through unknown plugins, or hidden behind runtime reflection. In those cases, the generated export program may add explicit capture calls at known plot boundaries, but it must not serialize the entire local or global namespace. If the required names still cannot be enumerated, stop with `needs_context`.

## Export program

The export program is a complete runnable source file, not a patch description. It must:

1. preserve the original processing path and defaults unless an output-directory parameter is required;
2. create a new package directory without modifying raw inputs;
3. write artifacts atomically where practical;
4. compute hashes after writes complete;
5. write `manifest.json` last so an incomplete run cannot appear complete;
6. reject an existing nonempty destination unless the user explicitly selected overwrite behavior;
7. avoid network, credential, shell, and dynamic-code operations introduced by the extraction;
8. report the package path and declared figure IDs after success.

Do not claim that adding capture code preserves behavior merely because the source parses. The local run and validation gate are required.

## Renderer isolation

`render_plot.py` reads only the package root, its manifest, declared artifacts, and the requested output path. It must:

- verify the manifest schema and requested figure ID;
- resolve every artifact path below the package root;
- verify artifact size and SHA-256 before use;
- load only formats permitted above;
- avoid importing the original analysis package or reading environment-specific absolute paths;
- avoid network access, subprocesses, shell commands, credentials, dynamic code execution, and interactive UI calls;
- be deterministic for identical package, figure ID, renderer source, and style overrides;
- create exactly one output for each `render` call and close figure resources afterwards.

Use a registry such as:

```python
RENDERERS = {
    "eta_summary": render_eta_summary,
    "fate_summary": render_fate_summary,
}
```

`list_figures(bundle_dir)` returns manifest order. It must not discover figures by importing arbitrary files.

## Validation evidence

Validation has two stages.

### Before the local run

- both generated sources parse;
- generated paths are workspace-relative;
- the export program has explicit capture points and a manifest writer;
- the renderer has no prohibited imports or calls and no raw-data references;
- every discovered figure has a stable ID and renderer mapping.

Passing these checks produces `pending_local_run`, never `ready`.

### After package upload

- manifest and artifact integrity checks pass;
- every declared figure renders in an isolated project snapshot;
- original and exported plotting inputs have the same keys, shapes, table columns, ordering, missingness, and values;
- exact values are compared exactly; floating-point values use only the manifest's justified tolerances;
- the rendered figure set and per-call output count match the declaration;
- undeclared raw-data access and writes outside the requested output are absent.

Store a bounded validation report below `validation/` or in platform project metadata. The report records pass, fail, or unverified for each figure. An image or artist-structure comparison can detect extraction mistakes, but a similar-looking image does not prove numeric equivalence.

If a rarely used branch has no runnable example or reference output, keep its code and manifest declaration only when its dependency closure is established. Mark the branch `unverified` and block an overall `ready` result until the user supplies validation evidence or explicitly excludes that figure from the package.

## Failure reporting

Return actionable failures with:

- the affected figure ID;
- unresolved variable, helper, file, or dynamic dependency;
- workspace-relative source location when known;
- whether more source, a local asset, a representative run, or user selection is required;
- confirmation that no incomplete extraction was reported as ready.

Never compensate for a missing dependency with fabricated data, a placeholder chart, or a silent fallback to the original raw-data pipeline.
