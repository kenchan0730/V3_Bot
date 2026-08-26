"""Earnings calendar with V4.5 scoring for desktop app."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

import yfinance as yf

from core.fundamental_filter import FundamentalFilter
from core.news_providers import score_headline

logger = logging.getLogger(__name__)


class EarningsCalendar:
    """Market earnings calendar via Finnhub with yfinance fallback."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.api_key = (
            cfg.get("finnhub_key")
            or cfg.get("api_key")
            or os.environ.get("FINNHUB_API_KEY", "")
        )
        self.fundamental = FundamentalFilter(cfg.get("fundamental") or {})
        self._client = None
        if self.api_key:
            try:
                import finnhub

                self._client = finnhub.Client(api_key=self.api_key)
            except Exception as exc:
                logger.warning("Finnhub earnings client init failed: %s", exc)

    def _score_earnings(self, symbol: str, eps_est: float | None) -> dict[str, Any]:
        """Heuristic 1-10 score for upcoming earnings."""
        view = self.fundamental.assess(symbol)
        base = 5.0
        tier_bonus = {"A": 2.0, "B": 1.0, "C": -1.0, "D": -2.0}.get(view.tier, 0)
        base += tier_bonus

        metrics = view.metrics or {}
        growth = metrics.get("earnings_growth")
        if growth is not None:
            try:
                g = float(growth)
                if g > 20:
                    base += 1.5
                elif g > 10:
                    base += 0.8
                elif g < 0:
                    base -= 1.0
            except (TypeError, ValueError):
                pass

        pe = metrics.get("pe_ratio")
        if pe is not None:
            try:
                p = float(pe)
                if 0 < p < 25:
                    base += 0.5
                elif p > 50:
                    base -= 0.8
            except (TypeError, ValueError):
                pass

        score = max(1.0, min(10.0, base))
        label = self._score_label(score)
        return {
            "score": round(score, 1),
            "label": label,
            "tier": view.tier,
            "tier_label": view.tier_label if hasattr(view, "tier_label") else "",
            "fundamental": view.to_dict(),
        }

    @staticmethod
    def _score_label(score: float) -> str:
        if score >= 9:
            return "強烈看漲"
        if score >= 7:
            return "看漲"
        if score >= 5:
            return "中性"
        if score >= 3:
            return "看跌"
        return "強烈看跌"

    def fetch_range(
        self, from_date: str, to_date: str, symbol: str = ""
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if self._client:
            try:
                data = self._client.earnings_calendar(
                    _from=from_date, to=to_date, symbol=symbol, international=False
                )
                for row in (data or {}).get("earningsCalendar") or []:
                    sym = str(row.get("symbol") or "").upper()
                    if not sym:
                        continue
                    eps_est = row.get("epsEstimate")
                    try:
                        eps_f = float(eps_est) if eps_est is not None else None
                    except (TypeError, ValueError):
                        eps_f = None
                    scoring = self._score_earnings(sym, eps_f)
                    items.append({
                        "date": row.get("date"),
                        "symbol": sym,
                        "name": row.get("name") or sym,
                        "hour": row.get("hour"),
                        "hour_label": {"bmo": "盤前", "amc": "盤後"}.get(
                            str(row.get("hour") or ""), row.get("hour")
                        ),
                        "eps_estimate": eps_f,
                        "eps_actual": row.get("epsActual"),
                        "revenue_estimate": row.get("revenueEstimate"),
                        "revenue_actual": row.get("revenueActual"),
                        "score": scoring["score"],
                        "score_label": scoring["label"],
                        "analysis": self._build_analysis(sym, scoring),
                        "fundamental": scoring["fundamental"],
                    })
            except Exception as exc:
                logger.warning("Finnhub earnings calendar failed: %s", exc)

        if not items and symbol:
            items.extend(self._yfinance_earnings(symbol))

        return items

    def fetch_day(self, date: str) -> list[dict[str, Any]]:
        return self.fetch_range(date, date)

    def _yfinance_earnings(self, symbol: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            ticker = yf.Ticker(symbol.upper())
            cal = ticker.calendar
            if cal is None:
                return out
            if hasattr(cal, "to_dict"):
                d = cal.to_dict()
                earnings_date = d.get("Earnings Date")
                if earnings_date:
                    date_str = str(earnings_date).split(" ")[0]
                    scoring = self._score_earnings(symbol, None)
                    out.append({
                        "date": date_str,
                        "symbol": symbol.upper(),
                        "name": symbol.upper(),
                        "hour": None,
                        "hour_label": "待定",
                        "eps_estimate": d.get("Earnings Average"),
                        "eps_actual": None,
                        "revenue_estimate": d.get("Revenue Average"),
                        "revenue_actual": None,
                        "score": scoring["score"],
                        "score_label": scoring["label"],
                        "analysis": self._build_analysis(symbol, scoring),
                        "fundamental": scoring["fundamental"],
                    })
        except Exception as exc:
            logger.debug("yfinance earnings %s: %s", symbol, exc)
        return out

    def _build_analysis(self, symbol: str, scoring: dict[str, Any]) -> str:
        fund = scoring.get("fundamental") or {}
        tier = fund.get("tier", "B")
        tier_label = fund.get("tier_label", "")
        metrics = fund.get("metrics") or {}
        parts = [
            f"{symbol} 財報前瞻評分 {scoring['score']}/10（{scoring['label']}）。",
            f"基本面等級 {tier}：{tier_label}。",
        ]
        if metrics.get("pe_ratio") is not None:
            parts.append(f"市盈率約 {metrics['pe_ratio']:.1f}。")
        if metrics.get("earnings_growth") is not None:
            parts.append(f"盈利成長約 {metrics['earnings_growth']:.1f}%。")
        parts.append(
            "建議關注：指引是否上調、毛利率趨勢、同業對比及盤前/盤後波動。"
        )
        return "".join(parts)

    def get_symbol_news_headlines(self, symbol: str, limit: int = 5) -> list[dict[str, Any]]:
        headlines: list[dict[str, Any]] = []
        try:
            raw = yf.Ticker(symbol.upper()).news or []
            for entry in raw[:limit]:
                title = (entry.get("title") or "").strip()
                if not title:
                    continue
                sent = score_headline(title)
                headlines.append({
                    "headline": title,
                    "url": entry.get("link") or "",
                    "sentiment": round(sent, 3),
                })
        except Exception as exc:
            logger.debug("earnings news %s: %s", symbol, exc)
        return headlines

    def get_detail(self, symbol: str, date: str | None = None) -> dict[str, Any]:
        sym = symbol.upper()
        from_d = date or datetime.now().strftime("%Y-%m-%d")
        to_d = (datetime.strptime(from_d, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
        events = self.fetch_range(from_d, to_d, sym)
        event = next((e for e in events if e["symbol"] == sym), None)
        if not event:
            scoring = self._score_earnings(sym, None)
            event = {
                "symbol": sym,
                "date": from_d,
                "score": scoring["score"],
                "score_label": scoring["label"],
                "analysis": self._build_analysis(sym, scoring),
                "fundamental": scoring["fundamental"],
            }
        event["news"] = self.get_symbol_news_headlines(sym)
        return event
