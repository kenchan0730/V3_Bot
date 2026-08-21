"""Market regime detection — unifies VIX, breadth, and free macro proxies.

Outputs a single regime label plus trading parameters (exposure, z-score floor,
entry permission). Designed for zero paid data vendors.
"""

import logging
from dataclasses import dataclass, field

from core.market_proxy import fetch_macro_snapshot

logger = logging.getLogger(__name__)

RISK_ON = "RISK_ON"
NEUTRAL = "NEUTRAL"
RISK_OFF = "RISK_OFF"
CRISIS = "CRISIS"


@dataclass
class RegimeResult:
    regime: str = NEUTRAL
    score: float = 50.0
    exposure_pct: int = 60
    zscore_min: float = 0.8
    allow_new_entries: bool = True
    allow_intraday_entries: bool = True
    max_open_positions_scale: float = 1.0
    reasons: list = field(default_factory=list)
    components: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "regime": self.regime,
            "score": round(self.score, 1),
            "exposure_pct": self.exposure_pct,
            "zscore_min": self.zscore_min,
            "allow_new_entries": self.allow_new_entries,
            "allow_intraday_entries": self.allow_intraday_entries,
            "max_open_positions_scale": self.max_open_positions_scale,
            "reasons": self.reasons,
            "components": self.components,
        }


class RegimeDetector:
    """Score-based regime classifier with configurable thresholds."""

    DEFAULTS = {
        "enabled": True,
        "vix_risk_on": 18.0,
        "vix_neutral": 22.0,
        "vix_risk_off": 28.0,
        "vix_crisis": 35.0,
        "breadth_risk_on": 65.0,
        "breadth_neutral": 45.0,
        "breadth_risk_off": 30.0,
        "risk_on_exposure": 100,
        "neutral_exposure": 60,
        "risk_off_exposure": 25,
        "crisis_exposure": 0,
        "risk_on_zscore_min": 0.5,
        "neutral_zscore_min": 0.8,
        "risk_off_zscore_min": 1.2,
        "crisis_zscore_min": 999.0,
        "macro_cache_seconds": 300,
        "halt_on_crisis": True,
        "credit_stress_pct": -2.0,
    }

    def __init__(self, config=None):
        cfg = {**self.DEFAULTS, **(config or {})}
        self.cfg = cfg
        self.last_result = RegimeResult()

    def detect(self, vix=None, breadth_score=None, force_macro_refresh=False):
        if not self.cfg.get("enabled", True):
            self.last_result = RegimeResult(
                regime=NEUTRAL,
                score=50.0,
                exposure_pct=int(self.cfg["neutral_exposure"]),
                zscore_min=float(self.cfg["neutral_zscore_min"]),
                reasons=["regime disabled"],
            )
            return self.last_result

        if force_macro_refresh:
            from core.market_proxy import clear_cache
            clear_cache()

        macro = fetch_macro_snapshot(ttl=int(self.cfg.get("macro_cache_seconds", 300)))
        vix = float(vix if vix is not None else macro.get("vix") or 20.0)
        breadth = float(breadth_score if breadth_score is not None else 50.0)

        components = {}
        score = 50.0
        reasons = []

        # --- VIX (30 pts) ---
        if vix <= self.cfg["vix_risk_on"]:
            score += 15
            components["vix"] = "calm"
            reasons.append(f"VIX {vix:.1f} calm")
        elif vix <= self.cfg["vix_neutral"]:
            score += 5
            components["vix"] = "normal"
        elif vix <= self.cfg["vix_risk_off"]:
            score -= 10
            components["vix"] = "elevated"
            reasons.append(f"VIX {vix:.1f} elevated")
        elif vix <= self.cfg["vix_crisis"]:
            score -= 20
            components["vix"] = "high"
            reasons.append(f"VIX {vix:.1f} high")
        else:
            score -= 30
            components["vix"] = "crisis"
            reasons.append(f"VIX {vix:.1f} crisis")

        # --- Breadth (25 pts) ---
        if breadth >= self.cfg["breadth_risk_on"]:
            score += 12
            components["breadth"] = "strong"
        elif breadth >= self.cfg["breadth_neutral"]:
            score += 4
            components["breadth"] = "neutral"
        elif breadth >= self.cfg["breadth_risk_off"]:
            score -= 8
            components["breadth"] = "weak"
            reasons.append(f"breadth {breadth:.0f} weak")
        else:
            score -= 18
            components["breadth"] = "critical"
            reasons.append(f"breadth {breadth:.0f} critical")

        # --- SPY trend (20 pts) ---
        spy50 = macro.get("spy_above_ma50")
        spy200 = macro.get("spy_above_ma200")
        if spy50 is True and spy200 is True:
            score += 10
            components["spy_trend"] = "bullish"
        elif spy50 is False and spy200 is False:
            score -= 12
            components["spy_trend"] = "bearish"
            reasons.append("SPY below MA50/MA200")
        else:
            components["spy_trend"] = "mixed"

        # --- Credit stress (15 pts) ---
        credit_trend = macro.get("credit_trend_pct")
        if credit_trend is not None:
            if credit_trend >= 0:
                score += 5
                components["credit"] = "stable"
            elif credit_trend <= self.cfg["credit_stress_pct"]:
                score -= 10
                components["credit"] = "stress"
                reasons.append(f"credit stress {credit_trend:.1f}%")
            else:
                components["credit"] = "soft"

        # --- VIX term structure (10 pts) ---
        term = macro.get("vix_term_spread")
        if term is not None:
            if term < 0:
                score += 4
                components["vix_term"] = "contango"
            elif term > 3:
                score -= 8
                components["vix_term"] = "backwardation"
                reasons.append(f"VIX backwardation {term:.1f}")

        score = max(0.0, min(100.0, score))
        regime, params = self._map_score(score, vix, breadth)
        components["macro"] = macro
        components["score"] = score

        self.last_result = RegimeResult(
            regime=regime,
            score=score,
            exposure_pct=params["exposure"],
            zscore_min=params["zscore_min"],
            allow_new_entries=params["allow_entries"],
            allow_intraday_entries=params["allow_intraday"],
            max_open_positions_scale=params["position_scale"],
            reasons=reasons or [f"regime={regime} score={score:.0f}"],
            components=components,
        )
        return self.last_result

    def _map_score(self, score, vix, breadth):
        crisis_vix = vix >= self.cfg["vix_crisis"]
        crisis_breadth = breadth < self.cfg["breadth_risk_off"] / 2

        if crisis_vix or (score < 25 and crisis_breadth):
            return CRISIS, {
                "exposure": int(self.cfg["crisis_exposure"]),
                "zscore_min": float(self.cfg["crisis_zscore_min"]),
                "allow_entries": False,
                "allow_intraday": False,
                "position_scale": 0.0,
            }
        if score >= 70:
            return RISK_ON, {
                "exposure": int(self.cfg["risk_on_exposure"]),
                "zscore_min": float(self.cfg["risk_on_zscore_min"]),
                "allow_entries": True,
                "allow_intraday": True,
                "position_scale": 1.0,
            }
        if score >= 45:
            return NEUTRAL, {
                "exposure": int(self.cfg["neutral_exposure"]),
                "zscore_min": float(self.cfg["neutral_zscore_min"]),
                "allow_entries": True,
                "allow_intraday": True,
                "position_scale": 0.75,
            }
        return RISK_OFF, {
            "exposure": int(self.cfg["risk_off_exposure"]),
            "zscore_min": float(self.cfg["risk_off_zscore_min"]),
            "allow_entries": False,
            "allow_intraday": False,
            "position_scale": 0.5,
        }
