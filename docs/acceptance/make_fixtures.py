"""Create source, CSV and original preview for the normalization acceptance fixtures.

This generates inputs and baseline images only; it does not normalize or judge charts.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent / "fixtures"
HEADER = '''from pathlib import Path
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
with (HERE / "data.csv").open(newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
'''


def fixture(name: str, columns: list[str], rows: list[tuple], drawing: str,
            extra_files: dict[str, str] | None = None) -> None:
    folder = ROOT / name
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "data.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    (folder / "source.py").write_text(HEADER + "\n" + dedent(drawing).strip() + "\n", encoding="utf-8")
    for filename, content in (extra_files or {}).items():
        (folder / filename).write_text(dedent(content).lstrip(), encoding="utf-8")
    subprocess.run([sys.executable, "source.py"], cwd=folder, check=True,
                   env={**os.environ, "MPLBACKEND": "Agg", "PYTHONDONTWRITEBYTECODE": "1"})


BOX_SOURCE = '''
values = [[float(r["value"]) for r in rows if r["group"] == group] for group in ("A", "B")]
fig, ax = plt.subplots(figsize=(4.2, 3.2))
ax.boxplot(values, tick_labels=["A", "B"], widths=0.45)
ax.set(xlabel="Group", ylabel="Response (a.u.)", title="Original box chart")
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
'''
fixture("box_dataset_a", ["group", "value"],
        [(group, value) for group, values in (("A", [3.0, 3.2, 3.4, 3.7, 4.0, 4.1]),
                                               ("B", [4.2, 4.4, 4.6, 4.8, 5.0, 5.2])) for value in values],
        BOX_SOURCE)
fixture("box_dataset_b", ["group", "value"],
        [(group, value) for group, values in (("A", [6.1, 6.2, 6.5, 6.9, 7.0, 7.3]),
                                               ("B", [7.4, 7.7, 8.0, 8.3, 8.7, 9.0])) for value in values],
        BOX_SOURCE)

fixture("p_boundaries", ["comparison", "p", "mean_a", "mean_b"],
        [("lt_001", 0.0009, 2.0, 3.0), ("eq_001", 0.001, 2.4, 3.4),
         ("eq_01", 0.01, 2.7, 3.7), ("eq_05", 0.05, 3.0, 4.0)], '''
fig, ax = plt.subplots(figsize=(7, 3.4))
for i, row in enumerate(rows):
    ax.bar([i * 2, i * 2 + 0.7], [float(row["mean_a"]), float(row["mean_b"])], width=0.55)
    ax.text(i * 2 + 0.35, 4.3, "p=" + row["p"], ha="center", fontsize=8)
ax.set_xticks([i * 2 + 0.35 for i in range(4)], [r["comparison"] for r in rows])
ax.set(ylabel="Mean", title="Four p-value boundaries")
ax.set_ylim(0, 4.8)
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')

fixture("line_explicit_error", ["x", "mean", "sem"],
        [(0, 1.0, 0.11), (1, 1.5, 0.14), (2, 1.7, 0.10), (3, 2.2, 0.18)], '''
x = [float(r["x"]) for r in rows]
y = [float(r["mean"]) for r in rows]
fig, ax = plt.subplots(figsize=(5.2, 3.3))
ax.plot(x, y, "o-", color="steelblue", label="A")
ax.set(xlabel="Time", ylabel="Mean", title="Line without drawn SEM")
ax.legend()
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')

fixture("line_replicates", ["x", "series", "replicate", "value"],
        [(x, series, rep, round(base + x * 0.3 + (rep - 2) * 0.14, 3))
         for series, base in (("A", 1.0), ("B", 1.6)) for x in range(4) for rep in (1, 2, 3)], '''
fig, ax = plt.subplots(figsize=(5.2, 3.3))
for series in ("A", "B"):
    x = sorted({int(r["x"]) for r in rows if r["series"] == series})
    means = [np.mean([float(r["value"]) for r in rows
                      if r["series"] == series and int(r["x"]) == item]) for item in x]
    ax.plot(x, means, "o-", label=series)
ax.set(xlabel="Time", ylabel="Mean", title="Replicate means without SEM")
ax.legend()
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')

fixture("line_aggregate_sem", ["x", "series", "mean", "sd", "n", "error_kind"],
        [(x, series, round(base + x * 0.3, 3), 0.6, 9, "SEM")
         for series, base in (("A", 1.0), ("B", 1.6)) for x in range(4)], '''
# error_kind explicitly records that SEM is intended. SD and n describe each mean.
fig, ax = plt.subplots(figsize=(5.2, 3.3))
for series in ("A", "B"):
    selected = [r for r in rows if r["series"] == series]
    ax.plot([float(r["x"]) for r in selected], [float(r["mean"]) for r in selected], "o-", label=series)
ax.set(xlabel="Time", ylabel="Mean", title="Prepared means and SD/n; SEM not drawn")
ax.legend()
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')

fixture("line_missing_error", ["x", "mean"],
        [(0, 1.0), (1, 1.2), (2, 1.4), (3, 1.8)], '''
fig, ax = plt.subplots(figsize=(5.2, 3.3))
ax.plot([float(r["x"]) for r in rows], [float(r["mean"]) for r in rows], "o-")
ax.set(xlabel="Time", ylabel="Mean", title="No uncertainty data")
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')

SCATTER_ROWS = [(0.2, 0.5), (0.6, 1.0), (1.0, 1.0), (1.5, 1.8), (1.9, 2.0), (2.4, 2.6)]
fixture("scatter_existing_fit", ["x", "y"], SCATTER_ROWS, '''
x = np.array([float(r["x"]) for r in rows])
y = np.array([float(r["y"]) for r in rows])
fig, ax = plt.subplots(figsize=(4.1, 3.2))
ax.scatter(x, y)
slope, intercept = np.polyfit(x, y, 1)
ax.plot(x, slope * x + intercept, color="purple", label="Existing linear fit")
ax.set(xlabel="Dose", ylabel="Response", title="Scatter with fit")
ax.legend()
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')
fixture("scatter_without_fit", ["x", "y"], SCATTER_ROWS, '''
x = [float(r["x"]) for r in rows]
y = [float(r["y"]) for r in rows]
fig, ax = plt.subplots(figsize=(4.1, 3.2))
ax.scatter(x, y)
ax.set(xlabel="Dose", ylabel="Response", title="Scatter without fit")
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')

fixture("violin_quartiles", ["group", "value"],
        [(group, value) for group, values in (("A", [1.0, 1.2, 1.3, 1.5, 1.8, 2.0, 2.1, 2.3]),
                                               ("B", [1.5, 1.7, 1.8, 2.1, 2.3, 2.5, 2.8, 3.0])) for value in values], '''
values = [[float(r["value"]) for r in rows if r["group"] == group] for group in ("A", "B")]
fig, ax = plt.subplots(figsize=(4.2, 3.2))
ax.violinplot(values, showmeans=False, showmedians=False)
ax.set_xticks([1, 2], ["A", "B"])
ax.set(ylabel="Response", title="Violin without inner quartiles")
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')

fixture("heatmap_7x4", ["row", "column", "value", "p"],
        [(r, c, round((r - 1.5) * 0.4 + (c - 3) * 0.2, 3),
          0.0009 if (r, c) == (0, 5) else 0.02 if (r, c) == (2, 1) else "")
         for r in range(4) for c in range(7)], '''
matrix = np.empty((4, 7))
for row in rows:
    matrix[int(row["row"]), int(row["column"])] = float(row["value"])
fig, ax = plt.subplots(figsize=(7, 4.5))
image = ax.imshow(matrix, cmap="viridis")
fig.colorbar(image, ax=ax)
ax.set_xticks(range(7), [f"C{i+1}" for i in range(7)])
ax.set_yticks(range(4), [f"R{i+1}" for i in range(4)])
ax.set(xlabel="Column", ylabel="Row", title="Seven by four heatmap")
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')

fixture("composite_paired", ["subject", "before", "after"],
        [(1, 1.0, 1.5), (2, 1.2, 1.8), (3, 1.4, 1.7), (4, 1.6, 2.0), (5, 1.8, 2.3)], '''
before = [float(r["before"]) for r in rows]
after = [float(r["after"]) for r in rows]
fig, ax = plt.subplots(figsize=(4.6, 3.5))
ax.boxplot([before, after], widths=0.42)
for a, b in zip(before, after):
    ax.plot([1, 2], [a, b], color="gray", alpha=0.55)
ax.scatter([1] * len(before) + [2] * len(after), before + after, color="coral", zorder=4)
ax.set_xticks([1, 2], ["Before", "After"])
ax.set(ylabel="Score", title="Paired box, dots and connectors")
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')

fixture("unknown_polar", ["theta", "radius"],
        [(0, 1.0), (0.8, 1.4), (1.6, 0.9), (2.4, 1.5), (3.2, 1.2), (4.0, 1.8), (5.2, 1.1)], '''
fig, ax = plt.subplots(subplot_kw={"projection": "polar"}, figsize=(4.1, 4.1))
ax.plot([float(r["theta"]) for r in rows], [float(r["radius"]) for r in rows], "o-")
ax.set_title("Polar source chart")
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''')

fixture("shared_helper", ["x", "series", "value"],
        [(x, series, round(base + slope * x, 2))
         for series, base, slope in (("A", 1.0, 0.2), ("B", 2.0, -0.1)) for x in range(4)], '''
from shared_draw import draw_series
fig, ax = plt.subplots(figsize=(4.8, 3.1))
draw_series(ax, rows, "A")
ax.set(xlabel="Time", ylabel="A value", title="Chart A uses shared helper")
fig.savefig(HERE / "original.png", dpi=120)
plt.close(fig)
''', {"shared_draw.py": '''
def draw_series(ax, rows, series):
    selected = [row for row in rows if row["series"] == series]
    ax.plot([float(row["x"]) for row in selected],
            [float(row["value"]) for row in selected], "o-", linewidth=1.5)
''', "companion.py": HEADER + '''
from shared_draw import draw_series
fig, ax = plt.subplots(figsize=(4.8, 3.1))
draw_series(ax, rows, "B")
ax.set(xlabel="Time", ylabel="B value", title="Chart B uses shared helper")
fig.savefig(HERE / "companion_original.png", dpi=120)
plt.close(fig)
'''})
subprocess.run([sys.executable, "companion.py"], cwd=ROOT / "shared_helper", check=True,
               env={**os.environ, "MPLBACKEND": "Agg", "PYTHONDONTWRITEBYTECODE": "1"})

lock = {"schema_version": "1.0", "fixtures": {}}
for folder in sorted(ROOT.iterdir()):
    if not folder.is_dir():
        continue
    files = {}
    for item in sorted(folder.iterdir()):
        if item.is_file() and item.suffix in (".py", ".csv", ".png"):
            files[item.name] = hashlib.sha256(item.read_bytes()).hexdigest()
    lock["fixtures"][folder.name] = files
(ROOT.parent / "fixtures.lock.json").write_text(
    json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(f"Created {len(list(ROOT.iterdir()))} acceptance fixture directories in {ROOT}")
