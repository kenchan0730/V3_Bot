"""Professional retail mindset — autonomous deliberation layer for V4.5_Bot.

This module does NOT replace signal logic. It sits above signals and answers:
  - Should we hold cash strategically?
  - Is this entry professional-grade right now?
  - How should size/stop adapt to volatility, macro, structure, PDT?

Design goal: mature 8–9/10 automation with honest 6–7/10 live edge expectations.
True 10/10 requires paid L2 data, years of journal feedback, and human oversight.
"""

import logging
from dataclasses import dataclass, field

from core.economic_calendar import EconomicCalendar
from core.execution_journal import ExecutionJournal
from core.liquidity_guard import LiquidityGuard
from core.market_structure import MarketStructure
from core.pdt_guard import PDTGuard
from core.portfolio_analytics import PortfolioHeatMonitor
from core.position_sizer import DynamicPositionSizer
from core.pyramid_manager import PyramidManager
from core.regime import CRISIS, RISK_OFF
from core.signal_utils import parse_confidence
from core.theme_registry import ThemeRegistry

logger = logging.getLogger(__name__)


@dataclass
class MindDecision:
    approve: bool = True
    action: str = "PROCEED"          # PROCEED | STRATEGIC_CASH | REDUCE | REJECT
    risk_multiplier: float = 1.0
    shares_scale: float = 1.0
    stop_override: float = None
    reasons: list = field(default_factory=list)
    thoughts: list = field(default_factory=list)
    execution_score: int = 7
    context_snapshot: dict = field(default_factory=dict)


class ProfessionalMind:
    """Central 'autonomous thinking' orchestrator."""

    DEFAULTS = {
        "enabled": True,
        "strategic_cash_enabled": True,
        "min_regime_score_to_trade": 40,
        "require_accumulation_phase": False,
        "log_every_deliberation": True,
        "journal_file": "data/execution_journal.csv",
        "consecutive_no_trade_days_goal": 3,
    }

    def __init__(self, config=None, state=None):
        cfg = {**self.DEFAULTS, **(config or {})}
        self.cfg = cfg
        self.state = state

        sub = cfg.get("submodules") or {}
        self.sizer = DynamicPositionSizer(sub.get("position_sizer") or cfg.get("position_sizer"))
        self.calendar = EconomicCalendar(sub.get("economic_calendar") or cfg.get("economic_calendar"))
        self.structure = MarketStructure(sub.get("market_structure") or cfg.get("market_structure"))
        self.liquidity = LiquidityGuard(sub.get("liquidity") or cfg.get("liquidity"))
        self.pdt = PDTGuard(sub.get("pdt") or cfg.get("pdt"), state=state)
        self.pyramid = PyramidManager(sub.get("pyramid") or cfg.get("pyramid"))
        self.heat = PortfolioHeatMonitor(sub.get("portfolio_heat") or cfg.get("portfolio_heat"))
        self.themes = ThemeRegistry(sub.get("themes") or cfg.get("themes"))
        self.journal = ExecutionJournal(cfg.get("journal_file", "data/execution_journal.csv"))

        self._cycles_without_setup = 0
        self._strategic_cash = False
        self._strategic_cash_reason = ""
        self._last_deliberation = None

    # ----- cycle-level thinking -----

    def deliberate_cycle(self, regime_result, portfolio, total_capital, watchlist_len=0):
        """Session-level decision: trade actively or protect capital in cash."""
        thoughts = []
        decision = MindDecision(approve=True, action="PROCEED")

        if not self.cfg.get("enabled", True):
            decision.thoughts = ["professional mind disabled"]
            return decision

        regime = getattr(regime_result, "regime", "NEUTRAL")
        score = getattr(regime_result, "score", 50)

        macro = self.calendar.current_context()
        if macro.get("active"):
            decision.risk_multiplier *= macro.get("risk_multiplier", 1.0)
            thoughts.append(macro.get("reason", "macro window"))
            if macro.get("block_new_entries"):
                decision.action = "REDUCE"
                decision.approve = False
                thoughts.append("宏觀窗口：暫停新倉")

        heat = self.heat.analyze(portfolio, total_capital)
        if heat.heat_2pct_pullback_pct > 4:
            thoughts.append(
                f"組合熱度：市場跌2% 約虧 {heat.heat_2pct_pullback_pct:.1f}% 帳戶"
            )
        if heat.rebalance_needed:
            thoughts.append(f"再平衡提示: {heat.rebalance_reason}")

        if regime in (CRISIS, RISK_OFF):
            self._strategic_cash = True
            self._strategic_cash_reason = f"regime={regime} score={score:.0f}"
            decision.action = "STRATEGIC_CASH"
            decision.approve = False
            decision.risk_multiplier = 0.0
            thoughts.append(f"專業空倉：{self._strategic_cash_reason}（保護本金）")
        elif score < float(self.cfg.get("min_regime_score_to_trade", 40)):
            decision.risk_multiplier *= 0.5
            thoughts.append(f"regime 偏弱 ({score:.0f})，半倉思維")

        if self.cfg.get("strategic_cash_enabled") and watchlist_len == 0:
            decision.action = "STRATEGIC_CASH"
            decision.approve = False
            thoughts.append("無合格 watchlist — 主動空倉")

        decision.thoughts = thoughts
        decision.context_snapshot = {
            "regime": regime,
            "regime_score": score,
            "macro": macro.get("events", []),
            "portfolio_heat_2pct": heat.heat_2pct_pullback_pct,
        }
        self._last_deliberation = decision

        if self.cfg.get("log_every_deliberation"):
            self.journal.log_decision(
                symbol="*SESSION*",
                decision=decision.action,
                deliberation=thoughts,
                context={
                    "regime": regime,
                    "breadth_score": getattr(regime_result, "components", {}).get("breadth"),
                    "notes": f"heat_2pct={heat.heat_2pct_pullback_pct}%",
                },
            )
        return decision

    def record_no_setup_cycle(self):
        self._cycles_without_setup += 1

    def record_setup_found(self):
        self._cycles_without_setup = 0

    @property
    def strategic_cash_mode(self):
        return self._strategic_cash

    @property
    def strategic_cash_reason(self):
        return self._strategic_cash_reason

    # ----- entry-level thinking -----

    def approve_entry(
        self, symbol, signal, df, context, portfolio, risk_mgr,
        entry_price, stop_price, base_shares, is_day_trade=False,
    ):
        thoughts = []
        decision = MindDecision(
            approve=True,
            action="PROCEED",
            stop_override=stop_price,
            context_snapshot={},
        )

        if not self.cfg.get("enabled", True):
            return decision

        if self._strategic_cash:
            return MindDecision(
                approve=False, action="STRATEGIC_CASH",
                reasons=[self._strategic_cash_reason],
                thoughts=["全局空倉模式"],
            )

        ok_liq, liq_msg = self.liquidity.allow_new_entry()
        if not ok_liq:
            return MindDecision(approve=False, action="REJECT", reasons=[liq_msg], thoughts=[liq_msg])

        ok_struct, struct_msg = self.structure.allow_long_entry(df)
        if not ok_struct:
            return MindDecision(approve=False, action="REJECT", reasons=[struct_msg], thoughts=[struct_msg])
        thoughts.append(struct_msg)

        if self.cfg.get("require_accumulation_phase"):
            info = self.structure.analyze(df)
            if info["phase"] not in ("ACCUMULATION", "NEUTRAL"):
                return MindDecision(
                    approve=False, action="REJECT",
                    reasons=[f"phase={info['phase']}"],
                    thoughts=[info["detail"]],
                )

        atr_stop = self.sizer.suggest_stop(df, entry_price, stop_price)
        if atr_stop and atr_stop != stop_price:
            decision.stop_override = self.liquidity.adjust_stop(atr_stop, entry_price)
            thoughts.append(f"ATR 停損 ${decision.stop_override:.2f}")

        scaled, size_msg = self.sizer.scale_shares(
            base_shares, df, entry_price, decision.stop_override or stop_price,
            risk_mgr.total_capital, vix=getattr(context, "vix", 18),
        )
        decision.shares_scale = scaled / base_shares if base_shares else 0
        if size_msg != "OK":
            thoughts.append(size_msg)

        ok_pdt, pdt_msg = self.pdt.check(risk_mgr.total_capital, is_day_trade=is_day_trade)
        if not ok_pdt:
            return MindDecision(approve=False, action="REJECT", reasons=[pdt_msg], thoughts=[pdt_msg])

        if portfolio.has_position(symbol):
            pos = portfolio.positions[symbol]
            ok_pyr, pyr_msg = self.pyramid.can_add(
                symbol, entry_price, pos.get("avg_cost", entry_price), pos.get("quantity", 0),
            )
            if not ok_pyr:
                return MindDecision(approve=False, action="REJECT", reasons=[pyr_msg], thoughts=[pyr_msg])
            thoughts.append(pyr_msg)

        macro = self.calendar.current_context()
        decision.risk_multiplier *= macro.get("risk_multiplier", 1.0)

        if not getattr(context, "allow_new_entries", True):
            return MindDecision(
                approve=False, action="REJECT",
                reasons=[f"regime {getattr(context, 'regime', '')} blocks entries"],
                thoughts=thoughts,
            )

        decision.execution_score = self._score_execution(signal, context, thoughts)
        decision.thoughts = thoughts
        decision.context_snapshot = {
            "regime": getattr(context, "regime", ""),
            "vix": getattr(context, "vix", ""),
            "market_structure": struct_msg,
            "macro_event": ",".join(macro.get("events", [])),
        }
        self._last_deliberation = decision

        self.journal.log_decision(
            symbol=symbol,
            decision="APPROVE" if decision.approve else "REJECT",
            deliberation=thoughts,
            execution_score=decision.execution_score,
            context={
                "action": signal.get("action", ""),
                "regime": getattr(context, "regime", ""),
                "breadth_score": getattr(context, "breadth_score", ""),
                "vix": getattr(context, "vix", ""),
                "exposure_pct": getattr(context, "exposure", ""),
                "market_structure": struct_msg,
                "macro_event": ",".join(macro.get("events", [])),
            },
        )
        return decision

    def _score_execution(self, signal, context, thoughts):
        score = 7
        conf = parse_confidence(signal.get("confidence"), default=0.5)
        if conf >= 0.8:
            score += 1
        if getattr(context, "regime", "") == "RISK_ON":
            score += 1
        if any("吸籌" in t for t in thoughts):
            score += 1
        if any("派貨" in t for t in thoughts):
            score -= 2
        if getattr(context, "regime", "") in (RISK_OFF, CRISIS):
            score -= 3
        return max(1, min(10, score))

    def theme_symbols(self):
        return self.themes.active_symbols()

    def theme_notes(self):
        return self.themes.describe()
