# v0.2.2 offline checks

Use Python 3.11 with `requirements.txt`, UTF-8 mode (`python -X utf8`), and Node.js.

```sh
python -X utf8 tests/run_offline.py tests.test_component_editor tests.test_component_groups tests.test_generic_component_groups tests.test_point_components tests.test_sparse_style tests.test_fast_interactive_preview tests.test_layout_preservation tests.test_desktop_launcher
node tests/test_connection_groups.cjs
```

The offline runner uses temporary settings and a fake credential vault, and blocks external socket connections. The full legacy suite has known failures; see the release notes.

Optional browser tests require Playwright (`npm install playwright`) and its Chromium browser (`npx playwright install chromium`). Start `python -X utf8 test_server_local.py`, then run `node test-browser-point-groups.cjs` and `node test-browser-connections.cjs`. The server creates only a temporary demo workspace on port 18765; keep it separate from the normal app. To use another Playwright installation or Chrome executable, set `PLAYWRIGHT_MODULE` or `CHROME_EXECUTABLE` respectively.

`tools/release_v022.py` and `.github/workflows/release-v022.yml` document the Windows package assembly, verified old runtime, pinned cloudpickle addition, independent launch checks and SHA256 files. No model service is called by these checks.
