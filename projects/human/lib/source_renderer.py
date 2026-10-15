"""Render the complete figure set using only CSV files in ../csv.

Run from any working directory:
    /opt/anaconda3/bin/python render_figures_from_csv.py
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import patheffects
from matplotlib.patches import Rectangle
from matplotlib.ticker import MaxNLocator


PACKAGE = Path(__file__).resolve().parents[1]
CSV = PACKAGE / "data"
OUT = PACKAGE / "figures"

BLACK = "#111111"
AXIS, BOX, MEDIAN, TICK, SIG = 3.4, 3.2, 3.1, 2.8, 2.6
AXIS_LABEL_SIZE, X_CATEGORY_LABEL_SIZE = 17.5, 16.25

plt.rcParams.update({"font.family": ["STHeiti", "DejaVu Sans"], "axes.unicode_minus": False})


def stars(p_value: float) -> str:
    return "***" if p_value < .001 else "**" if p_value < .01 else "*"


def wrapped_ylabel(label: str) -> str:
    if "\n" in label:
        return label
    lines = textwrap.wrap(label, width=34, break_long_words=False, break_on_hyphens=False)
    if len(lines) >= 2:
        final_words, previous_words = lines[-1].split(), lines[-2].split()
        if len(final_words) < 2 and len(previous_words) >= 2:
            lines[-2] = " ".join(previous_words[:-1])
            lines[-1] = f"{previous_words[-1]} {lines[-1]}"
    return "\n".join(lines)


def style(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_linewidth(AXIS)
    ax.spines["left"].set_position(("outward", -8))
    ax.spines["bottom"].set_position(("outward", 3))
    ax.tick_params(width=TICK, length=6, labelsize=19.5, pad=5)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontweight("black")
    for label in ax.get_xticklabels():
        label.set_fontsize(X_CATEGORY_LABEL_SIZE)


def apply_ylabel(ax: plt.Axes, ylabel: str) -> None:
    ax.set_ylabel(wrapped_ylabel(ylabel), fontsize=AXIS_LABEL_SIZE, fontweight="black", labelpad=9)
    ax.yaxis.label.set_path_effects([patheffects.withStroke(linewidth=.75, foreground=BLACK)])


def whisker_limits(values: np.ndarray) -> tuple[float, float]:
    q1, q3 = np.percentile(values, [25, 75])
    iqr = q3 - q1
    kept = values[(values >= q1 - 1.5 * iqr) & (values <= q3 + 1.5 * iqr)]
    return float(kept.min()), float(kept.max())


def draw_panel(ax: plt.Axes, panel: pd.Series, values: pd.DataFrame) -> None:
    labels = [panel.left_label, panel.right_label]
    colors = [panel.left_color, panel.right_color]
    groups = [values[values.group_label.eq(label)].value.to_numpy(float) for label in labels]
    pos, width = [.82, 1.18], .25 * (2 / 3) * (2 / 3) * 1.2
    is_mean_sem = stars(float(panel.p_value)) == "*"

    if is_mean_sem:
        means = [group.mean() for group in groups]
        sems = [group.std(ddof=1) / np.sqrt(len(group)) for group in groups]
        lo, hi = min(m - e for m, e in zip(means, sems)), max(m + e for m, e in zip(means, sems))
        for x, group, color, label in zip(pos, groups, colors, labels):
            sem = group.std(ddof=1) / np.sqrt(len(group))
            filled = label != "NDIS"
            ax.errorbar(x, group.mean(), yerr=sem, fmt="none", ecolor=color, elinewidth=BOX,
                        capsize=8, capthick=BOX, zorder=2)
            ax.scatter(x, group.mean(), s=400, facecolor=color if filled else "white",
                       edgecolor="none" if filled else color, linewidth=BOX if not filled else 0, zorder=3)
    else:
        lows, highs = zip(*(whisker_limits(group) for group in groups))
        lo, hi = min(lows), max(highs)
        bp = ax.boxplot(groups, positions=pos, widths=width, patch_artist=True, showfliers=False,
                        boxprops=dict(edgecolor=BLACK, linewidth=BOX),
                        whiskerprops=dict(color=BLACK, linewidth=BOX),
                        capprops=dict(color=BLACK, linewidth=BOX),
                        medianprops=dict(color=BLACK, linewidth=MEDIAN))
        right_filled = labels[1] != "NDIS"
        for patch, color, filled in zip(bp["boxes"], colors, [True, right_filled]):
            patch.set_facecolor(color if filled else "white")
            patch.set_edgecolor(BLACK if filled else color)
        if labels[1] == "NDIS":
            for artist in bp["whiskers"][2:] + bp["caps"][2:] + [bp["medians"][1]]:
                artist.set_color(colors[1])

    span = max(hi - lo, .08)
    pad = span * (.13 if is_mean_sem else .22)
    bracket_y = hi + pad * .65
    ax.plot([pos[0], pos[0], pos[1], pos[1]], [bracket_y - pad * .12, bracket_y, bracket_y, bracket_y - pad * .12], color=BLACK, lw=SIG, clip_on=False)
    ax.text(1, bracket_y + pad * .04, stars(float(panel.p_value)), ha="center", va="bottom", fontsize=17, fontweight="bold")
    ax.set_xlim(.55, 1.45)
    ax.set_xticks(pos, labels)
    apply_ylabel(ax, panel.ylabel)
    style(ax)
    ax.spines["bottom"].set_bounds(pos[0], pos[1])
    left_box_edge = pos[0] - width / 2
    ax.spines["left"].set_position(("data", (.55 + left_box_edge) / 2))
    candidates = MaxNLocator(nbins=4, min_n_ticks=3).tick_values(lo, bracket_y + pad * .28)
    bottom, top = candidates[candidates <= lo][-1], candidates[candidates >= hi][0]
    ticks = candidates[(candidates >= bottom - 1e-10) & (candidates <= top + 1e-10)]
    ax.set_ylim(bottom, top)
    ax.set_yticks(ticks)
    ax.spines["left"].set_bounds(ticks[0], ticks[-1])


def draw_timecourse(ax: plt.Axes, plot_id: str, values: pd.DataFrame, metadata: pd.DataFrame) -> None:
    meta = metadata.set_index("plot_id").loc[plot_id]
    data = values[values.plot_id.eq(plot_id)]
    bounds: list[float] = []
    group_rows = list(data[["group_label", "color", "legend_label"]].drop_duplicates().itertuples(index=False))
    for group in group_rows:
        part = data[data.group_label.eq(group.group_label)]
        summary = part.groupby(["stage_order", "stage_label"], sort=True).value.agg(["mean", "sem"]).reset_index()
        x, means, sems = summary.stage_order.to_numpy(float), summary["mean"].to_numpy(float), summary["sem"].to_numpy(float)
        ax.errorbar(x, means, yerr=sems, fmt="none", ecolor=group.color, elinewidth=BOX, capsize=8, capthick=BOX, zorder=2)
        ax.plot(x, means, color=group.color, linewidth=BOX, zorder=2)
        ax.scatter(x, means, s=400, facecolor=group.color, edgecolor="none", zorder=3, label=group.legend_label)
        bounds.extend((means - sems).tolist() + (means + sems).tolist())
    labels = data[["stage_order", "stage_label"]].drop_duplicates().sort_values("stage_order")
    x = labels.stage_order.to_numpy(float)
    lo, hi = min(bounds), max(bounds)
    span = max(hi - lo, .1)
    if isinstance(meta.star_stages, str) and meta.star_stages:
        for index, stage in enumerate(map(int, meta.star_stages.split("|"))):
            ax.text(stage, hi + span * (.15 - index * .09), meta.stars, ha="center", va="bottom", fontsize=21, fontweight="black")
    ax.set_xlim(x.min() - .35, x.max() + .35)
    ax.set_xticks(x, labels.stage_label)
    apply_ylabel(ax, meta.ylabel)
    style(ax)
    candidates = MaxNLocator(nbins=4, min_n_ticks=3).tick_values(lo, hi + span * .08)
    bottom, top = candidates[candidates <= lo][-1], candidates[candidates >= hi][0]
    ticks = candidates[(candidates >= bottom) & (candidates <= top)]
    ax.set_ylim(bottom, top)
    ax.set_yticks(ticks)
    ax.spines["bottom"].set_bounds(x.min(), x.max())
    ax.spines["left"].set_bounds(bottom, top)
    ax.spines["left"].set_position(("data", ((x.min() - .35) + x.min()) / 2))
    ax.legend(loc="upper center", bbox_to_anchor=(.5, 1.31 if len(x) == 4 else 1.08), ncol=2, frameon=False, fontsize=16 if len(x) == 4 else 14)


def save_individual(panels: pd.DataFrame, values: pd.DataFrame) -> None:
    for panel in panels.sort_values(["collection", "order"]).itertuples(index=False):
        fig, ax = plt.subplots(figsize=(5.4, 4.8))
        draw_panel(ax, panel, values[values.panel_id.eq(panel.panel_id)])
        ax.set_position([.34, .23, .60, .66])
        fig.savefig(OUT / f"{panel.panel_id}.png", dpi=300, bbox_inches="tight")
        plt.close(fig)


def save_timecourses(time_values: pd.DataFrame, time_meta: pd.DataFrame) -> None:
    for plot_id, filename, figsize in [
        ("03_obs_vs_nobs_score_relevance", "03_obs_vs_nobs_score_relevance_initial_final_sem.png", (5.4, 4.8)),
        ("05_obs_vs_disd_noticed_dimensions", "01_obs_vs_disd_noticed_dimensions_timecourse_sem.png", (7.2, 4.8)),
    ]:
        fig, ax = plt.subplots(figsize=figsize)
        draw_timecourse(ax, plot_id, time_values, time_meta)
        fig.tight_layout(pad=1.4)
        fig.savefig(OUT / filename, dpi=300, bbox_inches="tight")
        plt.close(fig)


def draw_heatmap(heatmap_id: str, heat_meta: pd.DataFrame) -> None:
    meta = heat_meta.set_index("heatmap_id").loc[heatmap_id]
    matrix_long = pd.read_csv(CSV / f"heatmap_{heatmap_id}_matrix.csv")
    stats = pd.read_csv(CSV / f"heatmap_{heatmap_id}_diagonal_stats.csv")
    dims, classes = ["A", "B", "C", "D", "E"], ["sofa", "table", "carpet", "plant", "painting"]
    display = {"sofa": "Sofa", "table": "Table", "carpet": "Carpet", "plant": "Plant", "painting": "Painting"}
    matrix = matrix_long.pivot(index="fds_dimension", columns="fixated_class", values="mean_value").reindex(index=dims, columns=classes).to_numpy(float)
    limit = float(np.nanmax(np.abs(matrix))) or 1e-9
    vmin, vmax = (-limit, limit) if bool(meta.symmetric) else (float(np.nanmin(matrix)), float(np.nanmax(matrix)))
    fig, ax = plt.subplots(figsize=(8.4, 7.8), dpi=300)
    for side in ax.spines.values():
        side.set_linewidth(3.4)
    ax.tick_params(width=2.8, labelsize=19.5, length=6)
    image = ax.imshow(matrix, cmap="RdBu_r", vmin=vmin, vmax=vmax)
    ax.set_xticks(range(5), [display[c] for c in classes], rotation=25, ha="right", fontsize=19.5)
    ax.set_yticks(range(5), [f"{dim}: {display[classes[i]]}" for i, dim in enumerate(dims)], fontsize=19.5)
    ax.set_xlabel("Viewed Task Dimension", fontsize=22, fontweight="bold", color=BLACK)
    ax.set_ylabel("DIS Dimension", fontsize=22, fontweight="bold", color=BLACK)
    star_map = stats.set_index("metric_key").stars.to_dict()
    for i, dim in enumerate(dims):
        ax.add_patch(Rectangle((i - .5, i - .5), 1, 1, fill=False, edgecolor=BLACK, linewidth=3.2))
        if star_map.get(dim, "n.s.") not in {"n.s.", "n/a"}:
            ax.text(i, i, star_map[dim], ha="center", va="center", fontsize=30, color=BLACK, fontweight="bold")
    bar = fig.colorbar(image, ax=ax, fraction=.046, pad=.04)
    bar.set_label(meta.colorbar_label, fontsize=17, fontweight="bold", color=BLACK)
    bar.ax.tick_params(labelsize=15)
    fig.tight_layout()
    fig.savefig(os.environ["CHART_OUTPUT"], dpi=300, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panels = pd.read_csv(CSV / "direct_panel_metadata.csv")
    values = pd.read_csv(CSV / "direct_panel_subject_values.csv")
    time_values = pd.read_csv(CSV / "timecourse_subject_values.csv")
    time_meta = pd.read_csv(CSV / "timecourse_metadata.csv")
    heat_meta = pd.read_csv(CSV / "heatmap_metadata.csv")
    save_individual(panels, values)
    save_timecourses(time_values, time_meta)
    for heatmap_id in heat_meta.heatmap_id:
        draw_heatmap(heatmap_id, heat_meta)


if __name__ == "__main__":
    main()
