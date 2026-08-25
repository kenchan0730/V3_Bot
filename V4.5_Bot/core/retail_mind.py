"""Professional-retail decision layer.

The institutional stack (regime, portfolio heat, PDT, accumulation phase) is
built to protect large books. A retail account has different constraints and
different freedoms, so this layer re-scores a setup from the retail seat:

Freedoms an institution does not have
    - can hold unprofitable growth names when a catalyst is live
    - can take a full position in a small-cap without moving the tape
    - can be fully in cash or fully in one idea with no mandate pressure

Constraints an institution does not have
    - a $1 commission minimum is a real cost on a $200 position
    - one bad fill matters because there is no execution desk
    - capital is finite: an unaffordable "great" setup is not a setup

The output is advisory sizing plus an approve/watch/skip verdict; hard risk
gates stay where they are (``RiskManager``, ``Portfolio``, ``ProfessionalMind``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RetailVerdict:
    approve: bool = True
    verdict: str = "BUY"           # BUY | WATCH | SKIP
    retail_score: int = 5
    size_factor: float = 1.0
    reasons: list = field(default_factory=list)
    thoughts: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def summary(self) -> str:
        head = f"{self.verdict} (散戶評分 {self.retail_score}/10"
        if self.size_factor < 1.0:
            head += f", 建議 {self.size_factor:.0%} 倉"
        head += ")"
        detail = "; ".join(self.reasons[:3])
        return f"{head} — {detail}" if detail else head


class RetailMind:
    """Score a setup the way an experienced retail trader would."""

    DEFAULTS = {
        "enabled": True,
        "min_retail_score": 5,
        "watch_score_margin": 2,
        # Cost reality for a small account
        "commission_per_share": 0.005,
        "commission_minimum": 1.0,
        "slippage_pct": 0.10,
        "max_cost_drag_pct": 1.20,
        # Setup geometry
        "min_reward_risk": 1.4,
        "max_extension_above_ma50_pct": 22.0,
        # Tradability. Daily range is volatility, not spread — a liquid name can
        # swing 6% and still fill cleanly, so it costs size rather than a veto.
        "min_dollar_volume": 2_000_000,
        "max_spread_proxy_pct": 10.0,
        "high_volatility_pct": 6.0,
        # Catalysts are the retail edge: a live story beats a clean chart
        "catalyst_min_news_score": 0.12,
        "catalyst_min_vol_ratio": 1.15,
        "catalyst_bonus": 2,
        "require_catalyst": False,
        "external_signal_bonus": 1,
        # Fundamentals: tier, not veto
        "tier_bonus": {"A": 1, "B": 0, "C": -1, "D": -2},
        "allow_unprofitable_growth": True,
        "unprofitable_needs_catalyst": True,
        # Size ladder by conviction
        "size_ladder": [
            [9, 1.0],
            [7, 0.75],
            [6, 0.55],
            [5, 0.4],
        ],
    }

    def __init__(self, config=None):
        self.cfg = {**self.DEFAULTS, **(config or {})}
        self.cfg["tier_bonus"] = {
            **self.DEFAULTS["tier_bonus"],
            **((config or {}).get("tier_bonus") or {}),
        }

    # ----- cost model -----

    def commission(self, shares: int) -> float:
        if shares <= 0:
            return 0.0
        return max(
            float(self.cfg["commission_minimum"]),
            shares * float(self.cfg["commission_per_share"]),
        )

    def round_trip_cost(self, shares: int, entry: float) -> float:
        """Two commissions plus an assumed slippage haircut on both legs."""
        notional = max(0.0, shares * entry)
        slip = notional * float(self.cfg["slippage_pct"]) / 100.0 * 2
        return self.commission(shares) * 2 + slip

    def cost_drag_pct(self, shares: int, entry: float) -> float:
        notional = shares * entry
        if notional <= 0:
            return 999.0
        return self.round_trip_cost(shares, entry) / notional * 100.0

    def min_viable_notional(self) -> float:
        """Smallest position where round-trip cost stays inside the drag limit.

        Below this, taking the trade at a reduced size is worse than skipping
        it: the commission minimum is fixed, so halving the position doubles the
        move needed just to break even.
        """
        max_drag = float(self.cfg["max_cost_drag_pct"]) / 100.0
        slip = float(self.cfg["slippage_pct"]) / 100.0 * 2
        headroom = max_drag - slip
        if headroom <= 0:
            return 0.0
        return round(float(self.cfg["commission_minimum"]) * 2 / headroom, 2)

    def affordable_shares(self, entry, capital, max_shares=None, max_symbol_pct=100.0):
        """Largest share count the account can actually pay for."""
        if entry <= 0 or capital <= 0:
            return 0
        budget = capital * float(max_symbol_pct) / 100.0
        shares = int(budget // entry)
        if max_shares:
            shares = min(shares, int(max_shares))
        return max(0, shares)

    # ----- tradability -----

    @staticmethod
    def dollar_volume(df, lookback=20):
        if df is None or len(df) == 0:
            return None
        window = df.tail(lookback)
        try:
            return float((window["close"] * window["volume"]).mean())
        except Exception:
            return None

    @staticmethod
    def spread_proxy_pct(df, lookback=5):
        """Daily high-low range as a stand-in for the bid/ask we cannot see."""
        if df is None or len(df) == 0:
            return None
        window = df.tail(lookback)
        try:
            rng = (window["high"] - window["low"]) / window["close"] * 100.0
            return float(rng.mean())
        except Exception:
            return None

    # ----- catalyst -----

    def detect_catalyst(self, news_view=None, vol_ratio=None, external_signal=None):
        """A catalyst is a story the market is voting on, not just good news."""
        news_score = float((news_view or {}).get("score") or 0.0)
        headlines = int((news_view or {}).get("total") or 0)
        vol = float(vol_ratio or 1.0)

        if external_signal:
            return True, f"外部訊號: {external_signal.get('source', 'app')}"

        score_ok = news_score >= float(self.cfg["catalyst_min_news_score"])
        vol_ok = vol >= float(self.cfg["catalyst_min_vol_ratio"])
        if score_ok and vol_ok and headlines > 0:
            return True, f"催化劑: 新聞 {news_score:+.2f} + 量能 {vol:.2f}×"
        if score_ok and headlines >= 5:
            return True, f"催化劑: 新聞流 {headlines} 則 ({news_score:+.2f})"
        return False, "無明確催化劑"

    # ----- main evaluation -----

    def evaluate(
        self,
        symbol,
        signal,
        context,
        df=None,
        *,
        fundamental_view=None,
        news_view=None,
        external_signal=None,
        capital=0.0,
        max_shares=None,
        max_symbol_pct=100.0,
        planned_shares=None,
    ) -> RetailVerdict:
        verdict = RetailVerdict()
        if not self.cfg.get("enabled", True):
            verdict.thoughts = ["retail mind disabled"]
            return verdict

        entry = float(signal.get("entry") or getattr(context, "price", 0) or 0)
        stop = float(signal.get("stop") or 0)
        target = float(signal.get("target1") or 0)
        price = float(getattr(context, "price", entry) or entry)
        ma50 = getattr(context, "ma50", None)
        ma20 = getattr(context, "ma20", None)
        vol_ratio = getattr(context, "vol_ratio", None)

        score = 5
        reasons: list[str] = []
        thoughts: list[str] = []

        shares = int(planned_shares or 0) or self.affordable_shares(
            entry, capital, max_shares=max_shares, max_symbol_pct=max_symbol_pct,
        )
        if entry > 0 and capital > 0 and shares <= 0:
            verdict.approve = False
            verdict.verdict = "SKIP"
            verdict.retail_score = 0
            verdict.reasons = [f"資金不足：${capital:.0f} 買不到 1 股 ${entry:.2f}"]
            verdict.metrics = {"entry": entry, "shares": 0}
            return verdict

        drag = self.cost_drag_pct(shares, entry) if shares else 999.0
        rr = (target - entry) / (entry - stop) if target and stop and entry > stop else None
        extension = ((price - ma50) / ma50 * 100.0) if ma50 else None
        dvol = self.dollar_volume(df)
        spread = self.spread_proxy_pct(df)
        catalyst, catalyst_note = self.detect_catalyst(
            news_view=news_view, vol_ratio=vol_ratio, external_signal=external_signal,
        )
        tier = str((fundamental_view or {}).get("tier") or "B").upper()

        metrics = {
            "entry": round(entry, 2),
            "shares": shares,
            "notional": round(shares * entry, 2),
            "cost_drag_pct": round(drag, 3) if drag < 900 else None,
            "breakeven_move_pct": round(drag, 3) if drag < 900 else None,
            "reward_risk": round(rr, 2) if rr else None,
            "extension_above_ma50_pct": round(extension, 2) if extension is not None else None,
            "avg_dollar_volume": round(dvol, 0) if dvol else None,
            "spread_proxy_pct": round(spread, 2) if spread else None,
            "catalyst": catalyst,
            "fundamental_tier": tier,
        }

        # ---- hard retail vetoes ----
        max_drag = float(self.cfg["max_cost_drag_pct"])
        if drag > max_drag:
            return self._reject(
                verdict, metrics,
                f"成本拖累 {drag:.2f}% > {max_drag:.2f}%（{shares} 股 ${shares * entry:.0f} 太小，手續費吃掉優勢）",
            )

        min_rr = float(self.cfg["min_reward_risk"])
        if rr is not None and rr < min_rr:
            return self._reject(
                verdict, metrics,
                f"風報比 {rr:.2f} < {min_rr:.2f}（賺賠不對稱，不值得冒險）",
            )

        max_ext = float(self.cfg["max_extension_above_ma50_pct"])
        if extension is not None and extension > max_ext:
            return self._reject(
                verdict, metrics,
                f"距 MA50 已 +{extension:.1f}% > {max_ext:.0f}%（追高風險，等回調）",
            )

        min_dvol = float(self.cfg["min_dollar_volume"])
        if dvol is not None and dvol < min_dvol:
            return self._reject(
                verdict, metrics,
                f"日均成交額 ${dvol / 1e6:.1f}M < ${min_dvol / 1e6:.1f}M（想賣時可能沒人接）",
            )

        max_spread = float(self.cfg["max_spread_proxy_pct"])
        if spread is not None and spread > max_spread:
            return self._reject(
                verdict, metrics,
                f"日內振幅 {spread:.1f}% > {max_spread:.1f}%（跳動過大，難以控制滑點）",
            )

        if tier == "D":
            return self._reject(verdict, metrics, "基本面 D 級：財務風險過高")

        if (
            tier == "C"
            and self.cfg.get("unprofitable_needs_catalyst", True)
            and not catalyst
        ):
            return self._reject(
                verdict, metrics,
                "虧損／高估值股缺少催化劑（散戶不靠估值賺錢，靠故事與動能）",
            )

        if self.cfg.get("require_catalyst") and not catalyst:
            return self._reject(verdict, metrics, "設定要求催化劑，但目前沒有")

        # ---- scoring ----
        if catalyst:
            score += int(self.cfg["catalyst_bonus"])
            reasons.append(catalyst_note)
        else:
            thoughts.append("純技術面進場（無催化劑，倉位保守）")

        if external_signal:
            score += int(self.cfg["external_signal_bonus"])
            reasons.append("你的 App 已標記為關注標的")

        score += int(self.cfg["tier_bonus"].get(tier, 0))
        if tier == "A":
            reasons.append("基本面 A 級")
        elif tier == "C":
            thoughts.append("基本面 C 級：靠催化劑而非估值")

        if ma20 and price > ma20:
            score += 1
            reasons.append("站上 MA20")
        if ma20 and ma50 and ma20 > ma50:
            score += 1
            reasons.append("均線多頭排列")

        if rr is not None and rr >= 2.0:
            score += 1
            reasons.append(f"風報比 {rr:.1f}")

        if drag <= max_drag / 2:
            score += 1
            reasons.append(f"成本拖累僅 {drag:.2f}%")
        else:
            thoughts.append(f"回本需漲 {drag:.2f}%")

        if extension is not None and extension <= max_ext / 2:
            score += 1
            reasons.append(f"距 MA50 +{extension:.1f}%，位置不追高")

        high_vol = float(self.cfg["high_volatility_pct"])
        if spread is not None and spread > high_vol:
            score -= 1
            thoughts.append(f"日均振幅 {spread:.1f}%，波動偏大 → 倉位收斂")

        confluence = int(signal.get("confluence_score") or 0)
        if confluence >= 6:
            score += 1
            reasons.append(f"共振 {confluence}/10")
        elif confluence and confluence <= 3:
            score -= 1
            thoughts.append(f"共振僅 {confluence}/10")

        score = max(0, min(10, score))
        min_score = int(self.cfg["min_retail_score"])
        margin = int(self.cfg["watch_score_margin"])

        verdict.retail_score = score
        verdict.metrics = metrics
        verdict.reasons = reasons
        verdict.thoughts = thoughts

        if score >= min_score:
            verdict.approve = True
            verdict.verdict = "BUY"
            verdict.size_factor = self._size_from_score(score)
        elif score >= min_score - margin:
            verdict.approve = False
            verdict.verdict = "WATCH"
            verdict.size_factor = 0.0
            verdict.reasons = [f"散戶評分 {score}/10 未達 {min_score}，先觀察"] + reasons
        else:
            verdict.approve = False
            verdict.verdict = "SKIP"
            verdict.size_factor = 0.0
            verdict.reasons = [f"散戶評分 {score}/10 太低"] + reasons
        return verdict

    def _size_from_score(self, score):
        for threshold, factor in self.cfg["size_ladder"]:
            if score >= int(threshold):
                return float(factor)
        return 0.4

    @staticmethod
    def _reject(verdict, metrics, reason):
        verdict.approve = False
        verdict.verdict = "SKIP"
        verdict.retail_score = 0
        verdict.size_factor = 0.0
        verdict.reasons = [reason]
        verdict.metrics = metrics
        return verdict
