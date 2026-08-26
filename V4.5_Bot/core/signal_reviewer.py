"""Review an externally sourced idea and answer two separate questions.

    Institutional desk  — is the story true, and do the fundamentals hold up?
    Retail seat         — given that, can *this* account actually trade it well?

Both answers are returned so the trader can see when a real story is still a
bad trade for a small account (and vice versa).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SymbolAnalysis:
    """Everything a decision needs about one symbol at one point in time."""

    symbol: str
    ok: bool = False
    stage: str = ""
    reason: str = ""
    price: float = 0.0
    df: object = None
    quant: dict = field(default_factory=dict)
    context: object = None
    signal: dict = field(default_factory=dict)
    fundamental_view: dict = field(default_factory=dict)
    news_view: dict = field(default_factory=dict)
    quality_ok: bool = False
    quality_reason: str = ""


class ExternalSignalReviewer:
    def __init__(
        self,
        *,
        analyzer,
        credibility,
        retail_mind,
        news=None,
        fundamental=None,
        capital_fn=None,
        max_shares=None,
        max_symbol_pct=100.0,
    ):
        self.analyzer = analyzer
        self.credibility = credibility
        self.retail_mind = retail_mind
        self.news = news
        self.fundamental = fundamental
        self.capital_fn = capital_fn or (lambda: 0.0)
        self.max_shares = max_shares
        self.max_symbol_pct = max_symbol_pct

    # ----- institutional half -----

    def verify_claim(self, signal):
        """Cross-source credibility audit of whatever the app sent over."""
        claim = signal.claim_text
        if not claim:
            return {
                "verdict": "NO_CLAIM",
                "confidence": 0.0,
                "reasons": ["未附帶消息內容，僅做技術與基本面審視"],
            }
        items = []
        if self.news is not None:
            for provider in getattr(self.news, "providers", []) or []:
                try:
                    items.extend(provider.fetch(signal.symbol, getattr(self.news, "days", 3)))
                except Exception as exc:
                    logger.debug("%s credibility fetch via %s failed: %s",
                                 signal.symbol, getattr(provider, "name", "?"), exc)
        report = self.credibility.audit(claim, items)
        return report.to_dict()

    def audit_fundamentals(self, symbol):
        if self.fundamental is None or not hasattr(self.fundamental, "assess"):
            return {}
        try:
            return self.fundamental.assess(symbol).to_dict()
        except Exception as exc:
            logger.warning("%s 基本面審視失敗: %s", symbol, exc)
            return {"error": str(exc)}

    # ----- combined -----

    def review(self, signal):
        symbol = signal.symbol
        report = {
            "symbol": symbol,
            "action_hint": signal.action_hint,
            "note": signal.note,
            "credibility": self.verify_claim(signal),
            "fundamental": self.audit_fundamentals(symbol),
        }

        analysis = self.analyzer(symbol)
        report["stage"] = analysis.stage
        report["technical"] = {
            "ok": analysis.ok,
            "reason": analysis.reason,
            "price": analysis.price,
            "action": (analysis.signal or {}).get("action"),
            "confluence": (analysis.signal or {}).get("confluence_score"),
            "missing_edges": (analysis.signal or {}).get("missing_edges"),
            "quality_ok": analysis.quality_ok,
            "quality_reason": analysis.quality_reason,
        }

        if not analysis.ok:
            report["verdict"] = "SKIP"
            report["retail"] = {}
            report["explanation"] = f"技術/資料階段未通過（{analysis.stage}）：{analysis.reason}"
            return report

        retail = self.retail_mind.evaluate(
            symbol,
            analysis.signal,
            analysis.context,
            df=analysis.df,
            fundamental_view=analysis.fundamental_view or report["fundamental"],
            news_view=analysis.news_view,
            external_signal=signal.to_dict(),
            capital=float(self.capital_fn() or 0.0),
            max_shares=self.max_shares,
            max_symbol_pct=self.max_symbol_pct,
        )
        report["retail"] = {
            "verdict": retail.verdict,
            "score": retail.retail_score,
            "size_factor": retail.size_factor,
            "reasons": retail.reasons,
            "thoughts": retail.thoughts,
            "metrics": retail.metrics,
        }

        credibility_verdict = report["credibility"].get("verdict")
        blocked_by_news = credibility_verdict in ("CONTRADICTED", "UNVERIFIED") and bool(signal.claim_text)

        if blocked_by_news:
            report["verdict"] = "WATCH" if credibility_verdict == "UNVERIFIED" else "SKIP"
            report["explanation"] = (
                f"消息審核 {credibility_verdict}："
                + "；".join(report["credibility"].get("reasons", [])[:2])
            )
            return report

        buyable = (
            analysis.quality_ok
            and retail.approve
            and (analysis.signal or {}).get("action") in ("STRONG_BUY", "MODERATE_BUY")
        )
        if buyable:
            report["verdict"] = "BUY"
        elif retail.verdict == "BUY":
            # Retail seat is happy but a gate upstream is not — keep it on watch.
            report["verdict"] = "WATCH"
        else:
            report["verdict"] = retail.verdict
        report["explanation"] = self._explain(analysis, retail, report["credibility"])
        return report

    @staticmethod
    def _explain(analysis, retail, credibility):
        parts = []
        if credibility.get("verdict") not in (None, "NO_CLAIM"):
            parts.append(f"消息 {credibility['verdict']} ({credibility.get('confidence', 0):.0%})")
        action = (analysis.signal or {}).get("action", "HOLD")
        parts.append(f"技術 {action} 共振 {(analysis.signal or {}).get('confluence_score', 0)}/10")
        if not analysis.quality_ok and analysis.quality_reason:
            parts.append(f"品質過濾: {analysis.quality_reason}")
        parts.append(retail.summary())
        return " | ".join(parts)
