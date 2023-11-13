import json
import os
import re
import sys
from collections import defaultdict

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

help_msg = "usage: python3 plot.py [max_gflops] [include Percent of Peak Geomean?] [For Paper?] [jsons...]"


def process_arg(i, typ):
    try:
        return typ(sys.argv[i])
    except:
        exit(help_msg)


flops = process_arg(1, float) * 1e9
include_pop_gm = process_arg(2, int)
for_paper = process_arg(3, int)
jsons = sys.argv[4:]

##
# Load and clean data

matcher = re.compile(r"^sgemm_(?P<name>\w+)/(?P<m>\d+)/(?P<n>\d+)/(?P<k>\d+)$")

square_plots = defaultdict(lambda: defaultdict(list))
aspect_plots = defaultdict(lambda: defaultdict(list))

for filename in jsons:
    with open(filename) as f:
        data = json.load(f)

    for point in data["benchmarks"]:
        if m := matcher.match(point["name"]):
            groups = m.groupdict()
            series = groups.get("name")

            if groups["m"] == groups["n"] == groups["k"]:
                square_plots[series]["n"].append(float(groups["n"]))
                square_plots[series]["flops"].append(float(point["flops"]))

            if groups["k"] == "512":
                aspect_plots[series]["ratio"].append(
                    float(groups["m"]) / float(groups["n"])
                )
                aspect_plots[series]["flops"].append(float(point["flops"]))

for series, points in square_plots.items():
    points["n"], points["flops"] = zip(*sorted(zip(points["n"], points["flops"])))

for series, points in aspect_plots.items():
    points["ratio"], points["flops"] = zip(
        *sorted(zip(points["ratio"], points["flops"]))
    )

##
# Common plotting styles for ACM one-column figure in two-column layout.

# Size constants
pts_per_inch = 72.27 if for_paper else 20
golden_ratio = (5**0.5 - 1) / 2

# Get from LaTeX by writing \showthe\textwidth (prints points in log)
latex_textwidth_pts = 395.8225 / 2 if for_paper else 300

# Compute figure size
width = latex_textwidth_pts / pts_per_inch
height = width * golden_ratio

matplotlib.rcParams.update(
    {
        "axes.labelpad": 0,
        "axes.labelsize": 7,
        "axes.linewidth": 0.4,
        "figure.figsize": (width, height),
        "font.size": 6.25,
        "grid.linewidth": 0.5,
        "lines.linewidth": 0.75,
        "font.family": "serif",
        "font.serif": "Linux Libertine O",
        "pgf.rcfonts": False,
        "pgf.texsystem": "pdflatex",
        "text.usetex": True,
        "xtick.major.pad": 0.4,
        "xtick.major.width": 0.4,
        "ytick.major.pad": 0.4,
        "ytick.major.width": 0.4,
    }
)


# Calculate the GeoMean of Percent of Peak
def calc_PoP_GM(values):
    result = 1.0
    for val in values:
        result *= val
    return result ** (1 / len(values))


##
# Plotting function


def plot_perf(data, filename, xkey, xlabel, xscale, ykey, ylabel):
    fig, ax1 = plt.subplots()

    color_table = {
        "exo": "tab:orange",
        "MKL": "tab:blue",
        "OpenBLAS": "tab:green",
    }

    for series, points in data.items():
        PoP_GM = calc_PoP_GM([i / flops for i in points[ykey]]) * 100
        PoP_GM = round(PoP_GM, 2)
        PoP_GM_label = f" (PoP GM {PoP_GM})"
        label = series + PoP_GM_label if include_pop_gm else ""
        ax1.plot(
            points[xkey],
            points[ykey],
            label=label,
            color=color_table.get(series, None),
            zorder=100 if series == "exo" else 1,
        )

    ax1.set(xlabel=xlabel, ylabel=ylabel)
    ax1.set_xscale(xscale)
    ax1.set_ybound(lower=0, upper=flops)
    ax1.grid()
    ax1.legend()

    ax1.yaxis.set_major_formatter(lambda x, _: f"{x / 1e9:.2f}")

    if flops:
        ax2 = ax1.twinx()
        ax2.set_ylabel("$\\%$ of peak")
        ax2.yaxis.set_major_formatter(lambda x, _: f"${x:.0%}$".replace("%", "\\%"))

        ax1.set_yticks(np.linspace(ax1.get_ybound()[0], ax1.get_ybound()[1], 7))
        ax2.set_yticks(np.linspace(ax2.get_ybound()[0], ax2.get_ybound()[1], 7))

    fig.tight_layout(pad=0)

    plt.savefig(f"{filename}.png")
    plt.savefig(f"{filename}.pgf")


##
# Create aspect ratio plots

plot_perf(
    data=aspect_plots,
    filename="sgemm_aspect_ratio",
    xkey="ratio",
    xlabel="Aspect ratio ($M/N$)",
    xscale="log",
    ykey="flops",
    ylabel="GFLOP/s",
)

##
# Create square-size plots

plot_perf(
    data=square_plots,
    filename="sgemm_square",
    xkey="n",
    xlabel="Dimension ($M=N=K$)",
    xscale="linear",
    ykey="flops",
    ylabel="GFLOP/s",
)
