import os
from pathlib import Path
project = Path(os.environ['CHART_PROJECT_DIR'])
"""Export every value required by the reproducible figure renderer.

This script is a one-time provenance exporter.  It reads the existing analysis
outputs and writes self-contained CSV files into ../csv.  The companion
render_figures_from_csv.py deliberately reads only those exported CSV files.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd


PACKAGE = Path(__file__).resolve().parents[1]
CSV = PACKAGE / "csv"
ROOT = PACKAGE.parent

ORANGE = "#E67E28"
PURPLE = "#8657BE"
YELLOW = "#F7BA00"


def add_panel(
    metadata: list[dict], values: list[dict], *, panel_id: str, collection: str,
    order: int, title: str, ylabel: str, p_value: float, left: pd.DataFrame,
    right: pd.DataFrame, left_label: str, right_label: str, left_color: str,
    right_color: str,
) -> None:
    metadata.append({
        "panel_id": panel_id, "collection": collection, "order": order,
        "title": title, "ylabel": ylabel, "p_value": p_value,
        "left_label": left_label, "right_label": right_label,
        "left_color": left_color, "right_color": right_color,
    })
    for frame, label in ((left, left_label), (right, right_label)):
        for row in frame.itertuples(index=False):
            values.append({
                "panel_id": panel_id, "subject_id": str(row.subject_id),
                "group_label": label, "value": float(row.value),
            })


def metric_values(data: pd.DataFrame, metric: str, group: str) -> pd.DataFrame:
    part = data[(data.level.eq("subject")) & (data.metric.eq(metric)) & (data.group.eq(group))]
    return part[["subject_id", "value"]].dropna().copy()


def export_direct_panels() -> None:
    metadata: list[dict] = []
    values: list[dict] = []

    stats = pd.read_csv(ROOT / "Obs vs DisFDS/unified_output_nearestcentroid_fixdur200/obs_vs_disfds_stats.csv")
    data = pd.read_csv(ROOT / "Obs vs DisFDS/unified_output_nearestcentroid_fixdur200/obs_vs_disfds_data_long.csv")
    labels = {
        "dimensions_seen_count": "Gaze-covered\ndimensions count",
        "images_seen_count": "Gaze-covered images count",
        "revisit_rate": "Gaze revisit rate",
        "revisit_region_share": "Revisited-region ratio",
    }
    for order, row in enumerate(stats[stats.p_value < .05].itertuples(index=False), start=1):
        add_panel(
            metadata, values, panel_id=f"01_obs_vs_disd_{order:02d}", collection="01_obs_vs_disd",
            order=order, title=row.metric_label, ylabel=labels.get(row.metric, row.metric_label),
            p_value=row.p_value, left=metric_values(data, row.metric, "observation"),
            right=metric_values(data, row.metric, "disrupt_fds"), left_label="Obs", right_label="DIS-D",
            left_color=ORANGE, right_color=PURPLE,
        )

    cov = pd.read_csv(ROOT / "Experiment 2 代码复用整理/眼动分析/Obs_vs_DISD_注视覆盖面积/outputs_nearestcentroid_fixdur200_no_baseline/obs_disfds_subject_means_alltrials.csv")
    cov_stats = pd.read_csv(ROOT / "Experiment 2 代码复用整理/眼动分析/Obs_vs_DISD_注视覆盖面积/outputs_nearestcentroid_fixdur200_no_baseline/obs_disfds_gaze_coverage_statistics.csv").iloc[1]
    add_panel(
        metadata, values, panel_id="01_obs_vs_disd_05", collection="01_obs_vs_disd", order=5,
        title="Fixation coverage area", ylabel="Gaze-coverage area (deg²)",
        p_value=cov_stats.holm_adjusted_p_two_windows,
        left=cov[cov.group.eq("observation")][["subject_id", "mean_sample_hull_area_deg2"]].rename(columns={"mean_sample_hull_area_deg2": "value"}),
        right=cov[cov.group.eq("disrupt_FDS")][["subject_id", "mean_sample_hull_area_deg2"]].rename(columns={"mean_sample_hull_area_deg2": "value"}),
        left_label="Obs", right_label="DIS-D", left_color=ORANGE, right_color=PURPLE,
    )
    speed = pd.read_csv(ROOT / "Experiment 2 代码复用整理/眼动分析/Obs_vs_DisFDS_平均扫视速度/outputs_nearestcentroid_fixdur200_no_baseline/obs_vs_disfds_subject_saccade_proxy_speed.csv")
    speed_stats = pd.read_csv(ROOT / "Experiment 2 代码复用整理/眼动分析/Obs_vs_DisFDS_平均扫视速度/outputs_nearestcentroid_fixdur200_no_baseline/obs_vs_disfds_saccade_proxy_speed_statistics.csv").iloc[0]
    add_panel(
        metadata, values, panel_id="01_obs_vs_disd_06", collection="01_obs_vs_disd", order=6,
        title="Fixation-centre shift speed", ylabel="Gaze-shift speed (deg/s)", p_value=speed_stats.p_value,
        left=speed[speed.group.eq("observation")][["subject_id", "mean_saccade_proxy_speed_deg_s"]].rename(columns={"mean_saccade_proxy_speed_deg_s": "value"}),
        right=speed[speed.group.eq("disrupt_fds")][["subject_id", "mean_saccade_proxy_speed_deg_s"]].rename(columns={"mean_saccade_proxy_speed_deg_s": "value"}),
        left_label="Obs", right_label="DIS-D", left_color=ORANGE, right_color=PURPLE,
    )

    stats = pd.read_csv(ROOT / "FDS vs NFDS/unified_output_no_baseline_nearestcentroid_fixdur200_full/fds_vs_nfds_stats.csv")
    data = pd.read_csv(ROOT / "FDS vs NFDS/unified_output_no_baseline_nearestcentroid_fixdur200_full/fds_vs_nfds_data_long.csv")
    labels = {
        "scanned_task_dim_count": "Gaze-covered task\ndimensions count",
        "raw_gaze_path_length_px": "Gaze path length (px)",
        "scanpath_length_px": "Gaze scanpath length (px)",
        "scanpath_length_per_s": "Gaze scanpath speed (px/s)",
        "dimension_switch_frequency_per_s": "Inter-dimensional gaze-switch rate (per s)",
        "scanned_image_count": "Gaze-covered images count",
        "mean_dwell_per_scanned_image_ms": "Mean gaze duration per covered image (ms)",
        "mean_single_fixation_duration_ms": "Mean fixation duration (ms)",
        "top1_dwell_share": "Gaze dwell share: top-1 dimension",
        "other_dwell_share": "Gaze dwell share: other dimensions",
        "top1_fixcount_share": "Gaze fixation-count share:\ntop-1 dimension",
        "other_fixcount_share": "Gaze fixation-count share:\nother dimensions",
        "switch_rate_per_min_corrected": "Corrected gaze-switch rate (per min)",
        "noise_to_noise_share_corrected": "Corrected noise-to-noise gaze-switch share",
        "switch_same_E_painting": "Gaze-switch share: E (painting)",
        "noise_attractor_noise_other": "Gaze-switch share: other noise",
        "entropy_corrected": "Corrected gaze-switch destination entropy",
    }
    selected = stats[stats.comparison.str.startswith("FDS_vs_nonFDS", na=False) & (stats.p_value_fdr < .05)]
    for order, row in enumerate(selected.itertuples(index=False), start=1):
        panel_id = f"02_dis_vs_ndis_{order:02d}"
        if row.metric_key == "raw_gaze_path_length_per_s":
            proxy = pd.read_csv(ROOT / "Experiment 2 代码复用整理/眼动分析/Obs_vs_DisFDS_平均扫视速度/outputs_nearestcentroid_fixdur200_no_baseline/dis_ndis_subject_saccade_proxy_speed.csv")
            proxy_stats = pd.read_csv(ROOT / "Experiment 2 代码复用整理/眼动分析/Obs_vs_DisFDS_平均扫视速度/outputs_nearestcentroid_fixdur200_no_baseline/dis_ndis_saccade_proxy_speed_statistics.csv").iloc[0]
            left = pd.DataFrame({"subject_id": range(len(proxy)), "value": proxy.DIS})
            right = pd.DataFrame({"subject_id": range(len(proxy)), "value": proxy.NDIS})
            title, ylabel, p_value = "Gaze-shift speed", "Gaze-shift speed (deg/s)", proxy_stats.wilcoxon_p_two_sided
        else:
            wide = data[(data.metric.eq(row.metric_key)) & data.level.isin(["subject", "subject_migrated"])]
            wide = wide.pivot_table(index="subject_id", columns="condition", values="value", aggfunc="first").dropna(subset=["FDS", "nonFDS"])
            left = wide[["FDS"]].reset_index().rename(columns={"FDS": "value"})
            right = wide[["nonFDS"]].reset_index().rename(columns={"nonFDS": "value"})
            title, ylabel, p_value = row.metric_label, labels[row.metric_key], row.p_value_fdr
        add_panel(metadata, values, panel_id=panel_id, collection="02_dis_vs_ndis", order=order,
                  title=title, ylabel=ylabel, p_value=p_value, left=left, right=right,
                  left_label="DIS", right_label="NDIS", left_color=PURPLE, right_color=PURPLE)

    coverage = pd.read_csv(ROOT / "Experiment 2 代码复用整理/眼动分析/DIS_vs_NDIS_注视覆盖面积/outputs_nearestcentroid_fixdur200_no_baseline/subject_DIS_NDIS_paired_means.csv")
    coverage_stats = pd.read_csv(ROOT / "Experiment 2 代码复用整理/眼动分析/DIS_vs_NDIS_注视覆盖面积/outputs_nearestcentroid_fixdur200_no_baseline/DIS_NDIS_gaze_coverage_statistics.csv").iloc[0]
    add_panel(metadata, values, panel_id="02_dis_vs_ndis_19", collection="02_dis_vs_ndis", order=19,
              title="Gaze-coverage area", ylabel="Gaze-coverage area (deg²)", p_value=coverage_stats.wilcoxon_p,
              left=coverage[["subject_id", "DIS"]].rename(columns={"DIS": "value"}),
              right=coverage[["subject_id", "NDIS"]].rename(columns={"NDIS": "value"}),
              left_label="DIS", right_label="NDIS", left_color=PURPLE, right_color=PURPLE)

    pre = pd.read_csv(ROOT / "Experiment 2 代码复用整理/眼动分析/Obs_vs_NObs_实验前注视覆盖维度数/outputs/extended_object_dimension_count_subject_level.csv")
    pre_stats = pd.read_csv(ROOT / "Experiment 2 代码复用整理/眼动分析/Obs_vs_NObs_实验前注视覆盖维度数/outputs/extended_object_dimension_count_statistics.csv").iloc[0]
    add_panel(metadata, values, panel_id="03_obs_vs_nobs_01", collection="03_obs_vs_nobs", order=1,
              title="Pre-experiment dimensions viewed", ylabel="Pre-experiment gaze-covered dimensions count", p_value=pre_stats.fdr_bh_p_eight_metrics,
              left=pre[pre.group.eq("observation")][["subject_id", "extended_object_dimension_count"]].rename(columns={"extended_object_dimension_count": "value"}),
              right=pre[pre.group.eq("non_observation")][["subject_id", "extended_object_dimension_count"]].rename(columns={"extended_object_dimension_count": "value"}),
              left_label="Obs", right_label="NObs", left_color=ORANGE, right_color=YELLOW)
    notice = pd.read_csv(ROOT / "Experiment 2 代码复用整理/问卷分析/Obs_vs_NObs_初始注意到维度数量/outputs/initial_noticed_dimensions_subject_level_0724.csv")
    notice_stats = pd.read_csv(ROOT / "Experiment 2 代码复用整理/问卷分析/Obs_vs_NObs_初始注意到维度数量/outputs/initial_noticed_dimensions_statistics_0724.csv").iloc[0]
    add_panel(metadata, values, panel_id="03_obs_vs_nobs_02", collection="03_obs_vs_nobs", order=2,
              title="Initially noticed dimensions", ylabel="Early-Phase Noticed Dimensions count", p_value=notice_stats.mannwhitney_p,
              left=notice[notice.group.eq("observation")][["subject_id", "initial_noticed_dimension_count"]].rename(columns={"initial_noticed_dimension_count": "value"}),
              right=notice[notice.group.eq("non_observation")][["subject_id", "initial_noticed_dimension_count"]].rename(columns={"initial_noticed_dimension_count": "value"}),
              left_label="Obs", right_label="NObs", left_color=ORANGE, right_color=YELLOW)

    pd.DataFrame(metadata).to_csv(CSV / "direct_panel_metadata.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(values).to_csv(CSV / "direct_panel_subject_values.csv", index=False, encoding="utf-8-sig")


def export_timecourses() -> None:
    rows: list[dict] = []
    meta: list[dict] = []
    d = pd.read_csv(ROOT / "Experiment 2 代码复用整理/问卷分析/Obs vs. NObs评分相关维度数_初期最终组内变化/source_data/analysis_dataset.csv")
    for group, label, color, legend in [("observation", "Obs", ORANGE, "Obs (*)"), ("non_observation", "NObs", YELLOW, "NObs (n.s.)")]:
        for order, (stage, col) in enumerate([(1, "initial_relevant_dimension_count"), (2, "final_relevant_dimension_count")], start=1):
            for row in d[d.group.eq(group)][["subject", "group", col]].dropna().itertuples(index=False):
                rows.append({"plot_id": "03_obs_vs_nobs_score_relevance", "subject_id": str(row.subject), "group_label": label, "color": color, "legend_label": legend, "stage_order": order, "stage_label": ["Initial", "Final"][order - 1], "value": float(getattr(row, col))})
    meta.append({"plot_id": "03_obs_vs_nobs_score_relevance", "ylabel": "Score-relevant\ndimensions count", "stars": "", "star_stages": ""})

    d = pd.read_csv(ROOT.parents[1] / "问卷分析/results_subject_level.csv")
    cols = ["注意到元素数_观察后", "注意到元素数_前期", "注意到元素数_中期", "注意到元素数_后期"]
    labels = ["Post-obs.", "Early", "Mid", "Late"]
    for group, label, color in [("observation", "Obs", ORANGE), ("disrupt FDS", "DIS-D", PURPLE)]:
        for order, (col, stage_label) in enumerate(zip(cols, labels), start=1):
            for row in d[d.group.eq(group)][["subject_id", "group", col]].dropna().itertuples(index=False):
                rows.append({"plot_id": "05_obs_vs_disd_noticed_dimensions", "subject_id": str(row.subject_id), "group_label": label, "color": color, "legend_label": label, "stage_order": order, "stage_label": stage_label, "value": float(getattr(row, col))})
    meta.append({"plot_id": "05_obs_vs_disd_noticed_dimensions", "ylabel": "Noticed Dimensions count", "stars": "**", "star_stages": "3|4"})
    pd.DataFrame(meta).to_csv(CSV / "timecourse_metadata.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(CSV / "timecourse_subject_values.csv", index=False, encoding="utf-8-sig")


def export_heatmaps() -> None:
    source = ROOT / "FDS vs NFDS"
    for source_dir, stem in [
        (source / "unified_output_nearestcentroid_fixdur200", "baseline_corrected"),
        (source / "unified_output_no_baseline_nearestcentroid_fixdur200", "no_baseline"),
    ]:
        shutil.copy2(source_dir / "fds_attention_heatmap_matrix_long.csv", CSV / f"heatmap_{stem}_matrix.csv")
        shutil.copy2(source_dir / "fds_attention_heatmap_diagonal_stats.csv", CSV / f"heatmap_{stem}_diagonal_stats.csv")
    pd.DataFrame([
        {"heatmap_id": "baseline_corrected", "colorbar_label": "Change in Gaze Dwell-Time Proportion from Baseline", "symmetric": True},
        {"heatmap_id": "no_baseline", "colorbar_label": "Gaze Dwell-Time Proportion", "symmetric": False},
    ]).to_csv(CSV / "heatmap_metadata.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    CSV.mkdir(parents=True, exist_ok=True)
    export_direct_panels()
    export_timecourses()
    export_heatmaps()


if __name__ == "__main__":
    main()

plt.savefig(os.environ['CHART_OUTPUT'], dpi=300, bbox_inches='tight')
