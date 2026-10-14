"""Central plotting conventions used by every chart script."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import json
from pathlib import Path

NORMALIZATION_PROFILE = Path(__file__).resolve().parent / "skills" / "chart-normalization" / "assets" / "style-profile.v1.json"

PALETTE = ["#2855a5", "#d66b30", "#23866e", "#9b70ae", "#c0a13a"]


def apply_style():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8,
        "axes.labelsize": 8,
        "axes.titlesize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.prop_cycle": plt.cycler(color=PALETTE),
        "savefig.dpi": 180,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })


def finish_figure(fig, output):
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def _normalization_profile():
    return json.loads(NORMALIZATION_PROFILE.read_text(encoding="utf-8"))


def apply_normalization_style():
    """Apply fixed global drawing tokens without changing the chart type."""
    from font_policy import register_platform_font
    global_style = _normalization_profile()["global"]
    if not register_platform_font():
        raise RuntimeError("Platform chart font " + global_style["font_family"] + " is unavailable")
    plt.rcParams.update({
        "font.family": global_style["font_family"],
        "font.size": global_style["category_tick_font_size_pt"],
        "axes.labelsize": global_style["axis_title_font_size_pt"],
        "xtick.labelsize": global_style["category_tick_font_size_pt"],
        "ytick.labelsize": global_style["numeric_tick_font_size_pt"],
        "figure.facecolor": global_style["background"],
        "axes.facecolor": global_style["axes_facecolor"],
        "savefig.dpi": global_style["png_dpi"],
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })


def normalize_figure_geometry(fig, chart_type=None):
    """Apply safe fixed geometry, returning limitations instead of guessing a template.

    This does not infer statistical summaries, artist identity, or chart type. The
    candidate producer applies artist-specific rules after reading the source.
    """
    from matplotlib.ticker import MaxNLocator, FixedLocator
    from matplotlib.collections import QuadMesh
    from matplotlib.category import StrCategoryConverter
    from matplotlib import font_manager
    from font_policy import audit_figure_fonts
    import numpy as np

    profile = _normalization_profile()
    style = profile["global"]
    data_axes = [ax for ax in fig.axes if ax.get_label() != "<colorbar>"]
    requested = profile["chart_types"].get(chart_type, {})
    single_cartesian = len(data_axes) == 1 and data_axes[0].name == "rectilinear"
    template = requested if single_cartesian else {}
    report = {"profile_version": profile["version"], "matched_template": chart_type if template else None,
              "warnings": [], "removed_titles": [], "font_substitutions": []}
    if chart_type and not template:
        report["warnings"].append("missing_template: preserve multi-panel, twin-axis or non-Cartesian geometry")
    if template:
        fig.set_layout_engine(None)
        fig.set_size_inches(*template["canvas_in"])
    fig.set_facecolor(style["background"])
    if fig._suptitle is not None and fig._suptitle.get_text():
        report["removed_titles"].append(fig._suptitle.get_text())
        fig._suptitle.set_text("")
    family = style["font_family"]
    font_manager.findfont(family, fallback_to_default=False)
    def label_family(text, weight):
        requested_weight = font_manager.weight_dict.get(weight, 400) if isinstance(weight, str) else weight
        registered = [entry for entry in font_manager.fontManager.ttflist if entry.name == family]
        available = [font_manager.weight_dict.get(entry.weight, 400) if isinstance(entry.weight, str) else entry.weight for entry in registered]
        # The fallback family is already specified by the profile. Keep the
        # requested numeric weight, but select its supported bold face for Latin.
        if requested_weight >= 700 and not any(value >= 700 for value in available):
            selected = family
            item = {"text": text, "requested_family": family, "requested_weight": weight,
                    "selected_family": selected,
                    "reason": "requested heavy face unavailable; fixed platform font retained with unresolved weight"}
            if item not in report["font_substitutions"]:
                report["font_substitutions"].append(item)
            warning = "font_weight_unverified: platform font lacks the requested heavy face"
            if warning not in report["warnings"]:
                report["warnings"].append(warning)
            return selected
        return family

    def converter(axis):
        getter = getattr(axis, "get_converter", None)
        return getter() if getter is not None else axis.converter

    for ax in data_axes:
        for title in (ax.title, ax._left_title, ax._right_title):
            if title.get_text():
                report["removed_titles"].append(title.get_text())
                title.set_text("")
        ax.set_facecolor(style["axes_facecolor"])
        if ax.name != "rectilinear":
            continue
        ax.grid(False)
        if template:
            ax.set_position(template["axes_rect"])
        visible = set(template.get("spines_visible", ()))
        for side, spine in ax.spines.items():
            if template:
                spine.set_visible(side in visible)
            if spine.get_visible():
                spine.set_linewidth(style["axis_spine_width_pt"])
                spine.set_color(style["ink"])
        for axis in (ax.xaxis, ax.yaxis):
            axis.label.set_fontsize(template.get("axis_title_font_size_pt", style["axis_title_font_size_pt"]))
            axis.label.set_fontweight(template.get("axis_title_font_weight", style["axis_title_font_weight"]))
            axis.label.set_color(style["ink"])
            axis.label.set_fontfamily(label_family(axis.label.get_text(), axis.label.get_fontweight()))
            axis.labelpad = style["axis_title_padding_pt"]
        ax.tick_params(axis="both", which="major", direction=style["tick_direction"],
                       width=style["tick_line_width_pt"], length=style["tick_length_pt"], colors=style["ink"])
        # Only a matching single-panel template can replace axis positioning.
        if template and chart_type == "heatmap":
            for side, spine in ax.spines.items():
                spine.set_position(("outward", 0))
                spine.set_bounds(*sorted(ax.get_ylim() if side in ("left", "right") else ax.get_xlim()))
            ax.tick_params(axis="x", labelrotation=template["x_tick_rotation_deg"])
        elif template:
            ax.spines["left"].set_position(("outward", 0))
            ax.spines["bottom"].set_position(("outward", style["x_axis_down_offset_pt"]))
            # Do not replace category labels or log/symlog tick interpretation.
            category_y = isinstance(converter(ax.yaxis), StrCategoryConverter)
            labels = [tick.get_text() for tick in ax.get_yticklabels()]
            if isinstance(ax.yaxis.get_major_locator(), FixedLocator) and labels:
                try:
                    for label in labels:
                        float(label.replace("−", "-").replace("$", ""))
                except ValueError:
                    category_y = True
            if not category_y and ax.get_yscale() == "linear":
                ax.yaxis.set_major_locator(MaxNLocator(nbins=style["max_numeric_y_major_tick_labels"] - 1))
            if not category_y:
                lower, upper = sorted(ax.get_ylim())
                ticks = [value for value in ax.get_yticks() if lower <= value <= upper]
                if len(ticks) > style["max_numeric_y_major_tick_labels"]:
                    indices = np.linspace(0, len(ticks) - 1, style["max_numeric_y_major_tick_labels"], dtype=int)
                    ax.set_yticks([ticks[index] for index in indices])
            for axis, side in ((ax.yaxis, "left"), (ax.xaxis, "bottom")):
                if side == "bottom" and chart_type in ("two_group_bar", "grouped_bar"):
                    ax.spines[side].set_bounds(*sorted(axis.get_view_interval()))
                    continue
                lower, upper = sorted(axis.get_view_interval())
                ticks = sorted(value for value in axis.get_majorticklocs() if lower <= value <= upper)
                if ticks:
                    ax.spines[side].set_bounds(ticks[0], ticks[-1])
        for axis in (ax.xaxis, ax.yaxis):
            labels = axis.get_ticklabels()
            is_category = isinstance(converter(axis), StrCategoryConverter) or chart_type == "heatmap"
            if isinstance(axis.get_major_locator(), FixedLocator):
                try:
                    for label in labels:
                        float(label.get_text().replace("−", "-").replace("$", ""))
                except ValueError:
                    is_category = True
            size = template.get("category_tick_font_size_pt", style["category_tick_font_size_pt"]) if is_category else style["numeric_tick_font_size_pt"]
            for label in labels:
                label.set_fontsize(size)
                label.set_fontfamily(family)
        legend = ax.get_legend()
        if template and legend is not None and isinstance(template.get("legend"), dict):
            rule = template["legend"]
            legend.set_loc(rule["location"])
            legend.set_bbox_to_anchor(rule["anchor_axes_fraction"], transform=ax.transAxes)
            legend.set_ncols(rule["columns"])
            legend.set_frame_on(rule["frame"])
            for text in legend.get_texts():
                text.set_fontsize(rule["font_size_pt"])
                text.set_fontfamily(family)
    report["font_audit"] = audit_figure_fonts(fig, normalize=True)
    if report["font_audit"]["missing_glyphs"]:
        report["warnings"].append("missing_glyphs: fixed platform font cannot draw all text")
    fig.canvas.draw()
    if template and chart_type == "heatmap":
        image_axes = data_axes[0]
        if image_axes.images or any(isinstance(item, QuadMesh) for item in image_axes.collections):
            colorbars = [ax for ax in fig.axes if ax.get_label() == "<colorbar>"]
            if len(colorbars) == 1:
                colorbar_axes = colorbars[0]
                box = image_axes.get_position()
                bar = template["colorbar"]
                colorbar_axes.set_axes_locator(None)
                colorbar_axes.set_box_aspect(None)
                colorbar_axes.set_aspect("auto")
                colorbar_axes.set_position([box.x1 + box.width * bar["pad_axes_fraction"], box.y0,
                                            box.width * bar["fraction"], box.height])
                colorbar_axes.tick_params(labelsize=bar["tick_font_size_pt"])
                colorbar_axes.yaxis.label.set_fontsize(bar["title_font_size_pt"])
            elif len(colorbars) > 1:
                report["warnings"].append("multiple_colorbars: no single colorbar template")
    fig.canvas.draw()
    fig._normalization_report = report
    return report


def finish_normalized_figure(fig, output, chart_type=None):
    """Save a candidate at fixed dimensions; caller decides whether to apply it."""
    report = normalize_figure_geometry(fig, chart_type)
    style = _normalization_profile()["global"]
    # Override rcParams too: a user may have previously set savefig.bbox='tight'.
    with matplotlib.rc_context({"savefig.bbox": None}):
        fig.savefig(output, dpi=style["png_dpi"], bbox_inches=None)
    plt.close(fig)
    return report


def plotting_error_values(rows, specification):
    """Resolve only explicitly identified prepared plotting uncertainty.

    specification examples: {kind:'SEM', column:'sem'};
    {kind:'SEM', sd_column:'sd', n_column:'n', sample_sd:True};
    {kind:'CI', lower_column:'lower', upper_column:'upper', mean_column:'mean',
     definition:'stored 95% CI'}. Values returned follow Matplotlib's yerr format.
    No CSV is written and no meaning or model is selected automatically.
    """
    import math
    kind = specification.get("kind")
    result = {"status": "unavailable", "values": None, "kind": kind, "columns": [], "formula": None}
    try:
        if not rows:
            raise ValueError("no plotting rows")
        if kind not in ("SD", "SEM", "CI"):
            raise ValueError("uncertainty meaning must be explicitly SD, SEM or CI")
        if kind == "CI" and not specification.get("definition"):
            raise ValueError("stored CI definition/confidence meaning is required")
        if specification.get("column"):
            column = specification["column"]
            result["columns"] = [column]
            values = [float(row[column]) for row in rows]
        elif kind == "SEM" and specification.get("sd_column") and specification.get("n_column"):
            if specification.get("sample_sd") is not True:
                raise ValueError("sample SD definition is required for the supplied SD")
            sd_col, n_col = specification["sd_column"], specification["n_column"]
            result["columns"] = [sd_col, n_col]
            values = []
            for row in rows:
                n = float(row[n_col])
                if not math.isfinite(n) or n < 2 or n != int(n):
                    raise ValueError("n must be an integer >= 2 for each corresponding aggregate")
                values.append(float(row[sd_col]) / math.sqrt(n))
            result["formula"] = "SEM = supplied sample SD / sqrt(supplied n)"
        elif kind == "CI" and all(specification.get(key) for key in ("lower_column", "upper_column", "mean_column", "definition")):
            low, high, mean = (specification[key] for key in ("lower_column", "upper_column", "mean_column"))
            result["columns"] = [low, high, mean]
            values = [[float(row[mean]) - float(row[low]) for row in rows],
                      [float(row[high]) - float(row[mean]) for row in rows]]
            result["formula"] = "yerr = [mean - supplied lower bound, supplied upper bound - mean]"
        else:
            raise ValueError("missing explicitly mapped uncertainty/aggregate columns or CI definition")
        flat = values[0] + values[1] if isinstance(values[0], list) else values
        if any(not math.isfinite(value) or value < 0 for value in flat):
            raise ValueError("uncertainty must be finite and nonnegative; CI must contain the plotted mean")
        result.update(status="available", values=values)
    except (ValueError, TypeError, KeyError) as exc:
        result["reason"] = str(exc)
    return result


def add_normalized_violin_quartiles(ax, bodies, positions, quartiles):
    """Add stored q25/median/q75 and IQR connectors without estimating a density.

    Call only for identified bodies without these existing marks. Input quartiles
    are supplied values, not inferred from mean/SD. Keep original artist layers.
    """
    import numpy as np
    rule = _normalization_profile()["chart_types"]["two_group_violin"]
    if not (len(bodies) == len(positions) == len(quartiles)):
        raise ValueError("Each violin requires one position and three supplied quartiles")
    all_values = [np.asarray(values, dtype=float) for values in quartiles]
    if any(values.shape != (3,) or not np.isfinite(values).all() or np.any(np.diff(values) < 0) for values in all_values):
        raise ValueError("Require finite ordered q25, median, q75")
    plans = []
    for body, center, values in zip(bodies, positions, all_values):
        vertices = body.get_paths()[0].vertices
        if values[0] < vertices[:, 1].min() or values[-1] > vertices[:, 1].max():
            raise ValueError("Stored quartiles fall outside the existing violin body")
        widths = []
        for value in values:
            crossings = []
            for start, end in zip(vertices[:-1], vertices[1:]):
                if start[1] != end[1] and min(start[1], end[1]) <= value <= max(start[1], end[1]):
                    crossings.append(start[0] + (end[0] - start[0]) * (value - start[1]) / (end[1] - start[1]))
            if len(crossings) < 2:
                raise ValueError("Cannot identify the existing violin width at a supplied quartile")
            widths.append(2 * min(center - min(crossings), max(crossings) - center))
        ratio = rule["inner_quartile_to_median_length_ratio"]
        median_length = min(rule["inner_median_max_length_x"], widths[1], widths[0] / ratio, widths[2] / ratio)
        if median_length <= 0:
            raise ValueError("No positive width for quartile marks within the body")
        plans.append((center, values, median_length))
    artists = []
    for center, values, median_length in plans:
        for index, value in enumerate(values):
            length = median_length if index == 1 else median_length * rule["inner_quartile_to_median_length_ratio"]
            artists.append(ax.hlines(value, center - length / 2, center + length / 2, color=rule["inner_line_color"],
                                     linewidth=rule["inner_median_line_width_pt"] if index == 1 else rule["inner_quartile_line_width_pt"]))
        artists.append(ax.vlines(center, values[0], values[2], color=rule["inner_line_color"], linewidth=rule["inner_iqr_connector_line_width_pt"]))
    for artist in artists:
        artist._normalization_role = 'violin_quartiles'
    return artists
