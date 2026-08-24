"""Optional candlestick chart export (matplotlib — no extra deps)."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def render_candle_chart(df, symbol, output_path, title=None, entry=None, stop=None):
    """Save a simple OHLC chart PNG. Returns path or None on failure."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        logger.warning("matplotlib 不可用，跳过图表输出")
        return None

    if df is None or len(df) < 5:
        return None

    tail = df.tail(min(60, len(df))).reset_index(drop=True)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, (ax_price, ax_vol) = plt.subplots(
        2, 1, sharex=True, figsize=(12, 6),
        gridspec_kw={"height_ratios": [3, 1]},
    )
    fig.suptitle(title or f"{symbol} Candlestick (last {len(tail)} bars)")

    for i, row in tail.iterrows():
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        color = "#26a69a" if c >= o else "#ef5350"
        ax_price.vlines(i, l, h, color=color, linewidth=1)
        body_bottom = min(o, c)
        body_height = max(abs(c - o), (h - l) * 0.05)
        ax_price.add_patch(Rectangle(
            (i - 0.3, body_bottom), 0.6, body_height,
            facecolor=color, edgecolor=color,
        ))
        ax_vol.bar(i, row.get("volume", 0), width=0.6, color=color, alpha=0.5)

    if entry:
        ax_price.axhline(entry, color="green", linestyle="--", linewidth=0.8, label=f"entry {entry}")
    if stop:
        ax_price.axhline(stop, color="red", linestyle="--", linewidth=0.8, label=f"stop {stop}")
    if entry or stop:
        ax_price.legend(loc="upper left", fontsize=8)

    ax_price.set_ylabel("Price")
    ax_vol.set_ylabel("Vol")
    ax_vol.set_xlabel("Bar index")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    logger.info(f"图表已保存: {output_path}")
    return str(output_path)
