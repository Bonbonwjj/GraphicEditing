"""Central plotting conventions used by every chart script."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
