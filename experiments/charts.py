"""Charts for the report from experiments/results/summary.csv and tuning/fitness.csv.

    python -m experiments.charts
"""

import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
RED, BLUE, BG, FG = "#ff3b5c", "#409cff", "#050916", "#e2e9f5"


def _style(ax):
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_color("#1c2c50")
    ax.tick_params(colors=FG)
    ax.yaxis.label.set_color(FG)
    ax.xaxis.label.set_color(FG)
    ax.title.set_color(FG)


def win_rates():
    path = os.path.join(RESULTS, "summary.csv")
    if not os.path.exists(path):
        print("run `python -m experiments.run_batch --suite` first")
        return
    with open(path) as f:
        rows = list(csv.DictReader(f))
    labels = [r["pairing"].replace("Ablation: ", "").replace(" vs ", "\nvs ") for r in rows]
    red = [float(r["red_win_rate"]) * 100 for r in rows]
    blue = [float(r["blue_win_rate"]) * 100 for r in rows]
    fig, ax = plt.subplots(figsize=(11, 5), facecolor=BG)
    _style(ax)
    y = range(len(rows))
    ax.barh(y, red, color=RED, label="Red wins")
    ax.barh(y, blue, left=red, color=BLUE, label="Blue wins")
    for i, (r, b) in enumerate(zip(red, blue)):
        if r >= 5:
            ax.text(r / 2, i, f"{r:.0f}%", va="center", ha="center", color="white", fontsize=9)
        if b >= 5:
            ax.text(r + b / 2, i, f"{b:.0f}%", va="center", ha="center", color="white", fontsize=9)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of matches (%)")
    ax.set_title(f"Zero Day evaluation ({rows[0]['matches']} matches per pairing, fixed seeds)")
    leg = ax.legend(loc="lower right", facecolor=BG, edgecolor="#1c2c50")
    for t in leg.get_texts():
        t.set_color(FG)
    fig.tight_layout()
    out = os.path.join(RESULTS, "win_rates.png")
    fig.savefig(out, dpi=140, facecolor=BG)
    print("wrote", out)


def fitness():
    path = os.path.join(HERE, "..", "tuning", "fitness.csv")
    if not os.path.exists(path):
        return
    with open(path) as f:
        rows = list(csv.DictReader(f))
    g = [int(r["generation"]) for r in rows]
    fig, ax = plt.subplots(figsize=(7, 4), facecolor=BG)
    _style(ax)
    ax.plot(g, [float(r["best"]) for r in rows], color=BLUE, linewidth=2.5, label="best")
    ax.plot(g, [float(r["mean"]) for r in rows], color="#7a8caf", linewidth=1.5, label="population mean")
    ax.set_xlabel("generation")
    ax.set_ylabel("fitness")
    ax.set_title("Blue AI tuned by the genetic algorithm")
    ax.grid(alpha=0.15)
    leg = ax.legend(facecolor=BG, edgecolor="#1c2c50")
    for t in leg.get_texts():
        t.set_color(FG)
    fig.tight_layout()
    out = os.path.join(HERE, "..", "tuning", "fitness.png")
    fig.savefig(out, dpi=140, facecolor=BG)
    print("wrote", os.path.normpath(out))


if __name__ == "__main__":
    win_rates()
    fitness()
