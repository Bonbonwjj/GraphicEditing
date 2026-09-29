# Chart Studio project schema

```text
projects/<project-id>/
├── project.json
├── data/
├── charts/
├── lib/
└── history/
```

`project.json` contains `name` and `description`. IDs use letters, digits, `_`, and `-`.

Every chart reads inputs below `Path(os.environ["CHART_PROJECT_DIR"]) / "data"` and writes one figure to `os.environ["CHART_OUTPUT"]`. It must not use network, shell, credentials, absolute source paths, or interactive `plt.show()`.

Original uploads stay grouped under:

```text
data/uploads/<project-id>/<batch-id>/
├── code/
└── csv/
```
