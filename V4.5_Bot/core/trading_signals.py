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
                   zscore_min=0.5, min_candle_strength=0.4,
                   min_vol_ratio_high=1.5, max_vol_ratio_low=0.8,
                   trend_mode="full", zscore_max=1.5):
    """Score each edge as passed (mandatory) and/or strongly confirmed (bonus).

    trend_mode: full (price>MA20>MA50) | swing (price>MA50) | off (always pass)
    """
    strength = candle.get("strength", 0) or 0
    if trend_mode == "off":
        trend_passed = True
    elif trend_mode == "swing":
        trend_passed = bool(ma50) and price > ma50
    else:
        trend_passed = price > ma20 > ma50
    edges = {
        "zscore": {
            "passed": zscore_min <= z_score <= zscore_max,
            "strong": ZSCORE_SWEET_SPOT[0] <= z_score <= ZSCORE_SWEET_SPOT[1],
        },
        "trend": {
            "passed": trend_passed,
            "strong": ma50 > 0 and (ma20 - ma50) / ma50 * 100 >= TREND_SPREAD_PCT,
        },
        "volume": {
            "passed": vol_ratio > min_vol_ratio_high or vol_ratio < max_vol_ratio_low,
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
                            zscore_min=0.5, min_candle_strength=0.4,
                            min_vol_ratio_high=1.5, max_vol_ratio_low=0.8,
                            trend_mode="full", zscore_max=1.5,
                            moderate_enabled=True, moderate_min_edges=4,
                            moderate_min_confluence=5,
                            symbol=None, candle_config=None):
        df = normalize_columns(df)
        candle = CandlePatterns.identify_all(df)
        swing_cfg = (candle_config or {}).get("_swing") or {}
        if swing_cfg:
            moderate_enabled = bool(swing_cfg.get("moderate_buy_enabled", moderate_enabled))
            moderate_min_edges = int(swing_cfg.get("moderate_min_edges", moderate_min_edges))
            moderate_min_confluence = int(
                swing_cfg.get("moderate_min_confluence", moderate_min_confluence)
            )
            trend_mode = swing_cfg.get("trend_mode", trend_mode)
            zscore_max = float(swing_cfg.get("zscore_max", zscore_max))

        if symbol and candle_config:
            try:
                from candle_lab.bridge import apply_learned_adjustment
                candle = apply_learned_adjustment(candle, symbol, candle_config)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(f"Candle Lab 调整跳过: {exc}")
        strength = candle.get("strength", 0) or 0

        edges = evaluate_edges(
            price, vix, z_score, vol_ratio, ma20, ma50, candle,
            zscore_min=zscore_min, min_candle_strength=min_candle_strength,
            min_vol_ratio_high=min_vol_ratio_high, max_vol_ratio_low=max_vol_ratio_low,
            trend_mode=trend_mode, zscore_max=zscore_max,
        )
        confluence = confluence_from_edges(edges)
        edge_names = sorted(name for name, e in edges.items() if e["passed"])
        strong_names = sorted(name for name, e in edges.items() if e["strong"])
        passed_count = sum(1 for e in edges.values() if e["passed"])

        def _buy_payload(action, track):
            entry = candle["entry"] or price + 0.01
            stop = candle["stop"] or price - (price * 0.02)
            risk = entry - stop
            confidence = confidence_from_edges(edges, strength)
            return {
                "action": action,
                "track": track,
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
                "learned_candle": {
                    "blocked": candle.get("learned_blocked", False),
                    "multiplier": candle.get("learned_multiplier"),
                    "reason": candle.get("learned_reason"),
                },
                "reason": (
                    f"K線: {', '.join(candle['patterns'])} ({track}) "
                    f"共振 {confluence}/10, 強化 {len(strong_names)}/5"
                ),
            }

        if all(e["passed"] for e in edges.values()):
            return _buy_payload("STRONG_BUY", "STRONG")

        if (
            moderate_enabled
            and passed_count >= moderate_min_edges
            and edges["candle"]["passed"]
            and edges["zscore"]["passed"]
            and confluence >= moderate_min_confluence
        ):
            return _buy_payload("MODERATE_BUY", "MODERATE")

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
