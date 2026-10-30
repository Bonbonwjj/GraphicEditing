# Native and universal adapters

Detect type from the explicit entry constant, not its filename.
For UNIVERSAL_FIGURE, style in customize(figure). Drawing changes use
UNIVERSAL_SOURCE_EDITS = {'relative/module.py': [{'old': exact, 'new': replacement}]}.
Keep render_original(UNIVERSAL_FIGURE, customize, UNIVERSAL_SOURCE_EDITS).
Paths are relative to the root shown after lib/universal/source/ in excerpts.

There are two path namespaces: UNIVERSAL_SOURCE_EDITS keys are relative to the
original source root; read_data_refs paths use the complete supplied plot_data.path,
including lib/universal/source/ where present. Runtime universal-work paths and
original absolute machine paths are not data references. The host accepts an exact
source-root-relative data alias only when the registry maps it to one snapshot file;
basename search is not an identity check.

For cosmetic adapter requests, prefer only customize-body changes using existing
artists, without imports or data reads. If data_access_policy permits it, return
data_access:preserve_existing and read_data_refs:[] instead of listing inherited
CSV readers. Keep all other adapter statements and prior patches unchanged. If a
requested effect needs earlier plotting logic, ask for that exact implementation
range and use full data references when changing it. The fast route cannot authorize
scientific changes or claim the renderer succeeded.

For NATIVE_FIGURE, style in customize(figure) using explicit panel_axes labels. Drawing
changes use NATIVE_SOURCE_EDITS and prepare_native(..., source_edits=NATIVE_SOURCE_EDITS).
Paths follow lib/native/<figure-id>/ in excerpts.

Modules remain read-only. Preserve earlier patches; new anchors must occur exactly once
in effective source after prior edits. Do not replace the patch map with only the latest
edit, invent anchors from omitted code, or include data writes. Patches apply only to a
disposable copy. Preserve original data readers, entry IDs, output selection and checks.
For ordinary chart code use its own existing hooks, not unrelated adapter APIs.
