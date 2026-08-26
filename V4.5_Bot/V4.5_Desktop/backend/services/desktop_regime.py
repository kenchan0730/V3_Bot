"""Desktop regime without Yahoo macro downloads."""

from __future__ import annotations

from typing import Any


def desktop_regime(breadth: dict[str, Any], spy_quote: dict[str, Any]) -> dict[str, Any]:
    score = float(breadth.get("score") or 50)
    if spy_quote.get("price", 0) > 0:
        score = min(100.0, max(0.0, score + float(spy_quote.get("change_pct") or 0) * 2.0))

    if score >= 65:
        label = "RISK_ON"
    elif score >= 45:
        label = "NEUTRAL"
    else:
        label = "RISK_OFF"

    regime = {
        "regime": label,
        "score": round(score, 1),
        "exposure_pct": 100 if label == "RISK_ON" else 60 if label == "NEUTRAL" else 25,
        "zscore_min": 0.5 if label == "RISK_ON" else 0.8,
        "allow_new_entries": label != "RISK_OFF",
        "allow_intraday_entries": label != "RISK_OFF",
        "max_open_positions_scale": 1.0,
        "reasons": [f"breadth {breadth.get('zone', 'NEUTRAL')}"],
        "components": {"breadth": breadth, "source": "desktop-finnhub"},
    }
    return {
        "score": round(score, 1),
        "label": label,
        "regime": regime,
        "breadth": breadth,
    }
