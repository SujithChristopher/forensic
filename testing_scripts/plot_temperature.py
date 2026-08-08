"""Plot DS18B20 temperature logs for one day, dropping >50 C outliers.

Usage:
    python testing_scripts/plot_temperature.py 2026-08-03
    python testing_scripts/plot_temperature.py 2026-08-03 --max-temp 45 --out foo.png
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e2e1dd"
# categorical slots 1-4 (validated light-mode palette)
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]


def load(date: str, max_temp: float) -> tuple[pd.DataFrame, dict[str, int]]:
    csv = ROOT / "data" / date / f"temp_data_{date}.csv"
    df = pd.read_csv(csv, parse_dates=["timestamp"])
    sensors = [c for c in df.columns if c != "timestamp"]

    dropped = {}
    for col in sensors:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        bad = df[col] > max_temp
        dropped[col] = int(bad.sum())
        df.loc[bad, col] = pd.NA  # gap in the line, not an interpolated lie

    # sensors that never reported anything are not plotted
    df = df[["timestamp"] + [c for c in sensors if df[c].notna().any()]]
    return df, dropped


def plot(df: pd.DataFrame, date: str, max_temp: float, out: Path) -> None:
    sensors = [c for c in df.columns if c != "timestamp"]

    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for i, col in enumerate(sensors):
        color = SERIES_COLORS[i % len(SERIES_COLORS)]
        ax.plot(df["timestamp"], df[col], lw=2, color=color, label=col, solid_capstyle="round")
        # direct label at the last valid point (contrast relief for the light steps)
        last = df[col].last_valid_index()
        if last is not None:
            ax.annotate(
                f" {col}  {df[col][last]:.1f}",
                (df["timestamp"][last], df[col][last]),
                color=color, fontsize=9, va="center", fontweight="bold",
            )

    ax.set_title(f"Enclosure temperature — {date}", color=TEXT_PRIMARY, fontsize=13,
                 fontweight="bold", loc="left", pad=14)
    ax.set_ylabel("°C", color=TEXT_SECONDARY, fontsize=10)
    ax.set_xlabel("")
    ax.grid(True, axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_xlim(df["timestamp"].min(), df["timestamp"].max())
    # headroom for the end labels
    ax.margins(x=0.06)

    leg = ax.legend(loc="upper left", frameon=False, ncols=len(sensors), fontsize=9)
    for text in leg.get_texts():
        text.set_color(TEXT_SECONDARY)

    fig.text(0.01, 0.01, f"readings above {max_temp:g} °C removed", color=TEXT_SECONDARY, fontsize=8)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("date", help="YYYY-MM-DD")
    p.add_argument("--max-temp", type=float, default=50.0)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    out = args.out or ROOT / "output" / f"temp_plot_{args.date}.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    df, dropped = load(args.date, args.max_temp)
    plot(df, args.date, args.max_temp, out)

    sensors = [c for c in df.columns if c != "timestamp"]
    print(f"rows: {len(df)}  span: {df['timestamp'].min()} -> {df['timestamp'].max()}")
    for col, n in dropped.items():
        stats = f"min {df[col].min():.2f}  max {df[col].max():.2f}" if col in sensors else "no data"
        print(f"  {col}: dropped {n}  {stats}")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
