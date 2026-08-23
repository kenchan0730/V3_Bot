"""Combined technical + candlestick signal with M.E.T.A. confluence grading.

Entry still requires every mandatory edge (z-score zone, trend structure, volume
anomaly, calm volatility, bullish candle). On top of that hard gate the module
grades *how strongly* those edges align and exposes it as:

- ``confluence_score`` (1–10): how many edges merely passed vs strongly confirmed
- ``confidence`` (0–1 float): numeric conviction consumed by the risk layer
- ``confidence_label`` (HIGH/MEDIUM/LOW): human-readable form for logs and UI

``confidence`` is deliberately numeric: the risk layer scores it arithmetically,
and a string here previously raised ``ValueError`` on every real buy signal.
"""

from core.candle_patterns import CandlePatterns
from core.data_utils import normalize_columns

ZSCORE_SWEET_SPOT = (0.8, 1.3)
STRONG_VOL_RATIO = 2.0
CALM_VIX = 18.0
STRONG_CANDLE_STRENGTH = 0.8
TREND_SPREAD_PCT = 1.0


def _label(confidence):
    if confidence >= 0.75:
        return "HIGH"
    if confidence >= 0.55:
        return "MEDIUM"
    return "LOW"


def evaluate_edges(price, vix, z_score, vol_ratio, ma20, ma50, candle,
                   zscore_min=0.5, min_candle_strength=0.4):
    """Score each edge as passed (mandatory) and/or strongly confirmed (bonus)."""
    strength = candle.get("strength", 0) or 0
    edges = {
        "zscore": {
            "passed": zscore_min <= z_score <= 1.5,
            "strong": ZSCORE_SWEET_SPOT[0] <= z_score <= ZSCORE_SWEET_SPOT[1],
        },
        "trend": {
            "passed": price > ma20 > ma50,
            "strong": ma50 > 0 and (ma20 - ma50) / ma50 * 100 >= TREND_SPREAD_PCT,
        },
        "volume": {
            "passed": vol_ratio > 1.5 or vol_ratio < 0.8,
            "strong": vol_ratio >= STRONG_VOL_RATIO,
        },
        "volatility": {
            "passed": vix <= 25,
            "strong": vix <= CALM_VIX,
        },
        "candle": {
            "passed": candle.get("signal") == "bullish" and strength >= min_candle_strength,
            "strong": strength >= STRONG_CANDLE_STRENGTH,
        },
    }
    for edge in edges.values():
        edge["strong"] = bool(edge["strong"] and edge["passed"])
    return edges


def confluence_from_edges(edges):
    """Map edge alignment onto a 1–10 M.E.T.A. confluence score."""
    passed = sum(1 for e in edges.values() if e["passed"])
    strong = sum(1 for e in edges.values() if e["strong"])
    if passed < len(edges):
        return max(1, passed)
    return min(10, 5 + strong)


def confidence_from_edges(edges, candle_strength):
    """Numeric conviction in [0, 1] driven by bonus edges and candle strength."""
    strong = sum(1 for e in edges.values() if e["strong"])
    confidence = 0.5 + strong * 0.05 + abs(candle_strength) * 0.2
    return round(min(0.98, confidence), 3)


class TradingSignals:
    @staticmethod
    def get_combined_signal(df, price, vix, z_score, vol_ratio, ma20, ma50,
                            zscore_min=0.5, min_candle_strength=0.4):
        df = normalize_columns(df)
        candle = CandlePatterns.identify_all(df)
        strength = candle.get("strength", 0) or 0

        edges = evaluate_edges(
            price, vix, z_score, vol_ratio, ma20, ma50, candle,
            zscore_min=zscore_min, min_candle_strength=min_candle_strength,
        )
        confluence = confluence_from_edges(edges)
        edge_names = sorted(name for name, e in edges.items() if e["passed"])
        strong_names = sorted(name for name, e in edges.items() if e["strong"])

        if all(e["passed"] for e in edges.values()):
            entry = candle["entry"] or price + 0.01
            stop = candle["stop"] or price - (price * 0.02)
            risk = entry - stop
            confidence = confidence_from_edges(edges, strength)
            return {
                "action": "STRONG_BUY",
                "entry": round(entry, 2),
                "stop": round(stop, 2),
                "target1": round(entry + risk * 1.5, 2),
                "target2": round(entry + risk * 3.0, 2),
                "confidence": confidence,
                "confidence_label": _label(confidence),
                "confluence_score": confluence,
                "edges": edge_names,
                "strong_edges": strong_names,
                "candle_driver": candle.get("driver"),
                "reason": (
                    f"K線信號: {', '.join(candle['patterns'])} + V4.0確認 "
                    f"(共振 {confluence}/10, 強化 {len(strong_names)}/5)"
                ),
            }

        if candle["signal"] == "bearish" and strength <= -min_candle_strength:
            return {
                "action": "STRONG_SELL",
                "confidence": confidence_from_edges(edges, strength),
                "confluence_score": confluence,
                "candle_driver": candle.get("driver"),
                "reason": f"K線形態: {', '.join(candle['patterns'])}",
            }

        missing = sorted(name for name, e in edges.items() if not e["passed"])
        return {
            "action": "HOLD",
            "confluence_score": confluence,
            "edges": edge_names,
            "missing_edges": missing,
            "reason": (
                f"無強力信號 (K線強度 {candle['strength']}, "
                f"共振 {confluence}/10, 缺: {', '.join(missing) or '無'})"
            ),
        }
