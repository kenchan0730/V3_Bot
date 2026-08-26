"""SEC Form 4 insider transaction aggregation for desktop intelligence."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

BUY_CODES = {"P", "A"}
SELL_CODES = {"S", "D"}


@dataclass
class InsiderTransaction:
    symbol: str
    name: str
    title: str
    transaction_date: str
    transaction_code: str
    price: float
    shares: float
    value: float
    change: float | None = None
    filing_date: str = ""
    source: str = "finnhub"

    @property
    def is_buy(self) -> bool:
        return self.transaction_code in BUY_CODES

    @property
    def is_sell(self) -> bool:
        return self.transaction_code in SELL_CODES


@dataclass
class InsiderDaySummary:
    date: str
    buy_value: float = 0.0
    sell_value: float = 0.0
    buy_count: int = 0
    sell_count: int = 0
    buy_symbols: int = 0
    sell_symbols: int = 0
    high_conviction: int = 0
    cluster_buying: int = 0
    transactions: list[InsiderTransaction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "buy_value": round(self.buy_value, 2),
            "sell_value": round(self.sell_value, 2),
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "buy_symbols": self.buy_symbols,
            "sell_symbols": self.sell_symbols,
            "high_conviction": self.high_conviction,
            "cluster_buying": self.cluster_buying,
            "transactions": [self._tx_dict(t) for t in self.transactions],
        }

    @staticmethod
    def _tx_dict(t: InsiderTransaction) -> dict[str, Any]:
        return {
            "symbol": t.symbol,
            "name": t.name,
            "title": t.title,
            "transaction_date": t.transaction_date,
            "transaction_code": t.transaction_code,
            "side": "buy" if t.is_buy else "sell" if t.is_sell else "other",
            "price": round(t.price, 4),
            "shares": round(t.shares, 2),
            "value": round(t.value, 2),
            "change_pct": round(t.change, 2) if t.change is not None else None,
            "filing_date": t.filing_date,
            "source": t.source,
        }


class InsiderTracker:
    """Aggregate insider trades across a symbol universe for a given date."""

    DEFAULT_UNIVERSE = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B",
        "JPM", "V", "UNH", "XOM", "LLY", "JNJ", "WMT", "MA", "PG", "AVGO",
        "HD", "CVX", "MRK", "ABBV", "COST", "PEP", "KO", "ADBE", "CRM",
        "NFLX", "AMD", "INTC", "QCOM", "TXN", "ORCL", "IBM", "GS", "MS",
        "BAC", "C", "WFC", "BLK", "SCHW", "PLTR", "COIN", "HOOD", "SMCI",
        "MU", "MRVL", "ON", "LRCX", "AMAT", "CAT", "DE", "BA", "RTX",
    ]

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.api_key = (
            cfg.get("finnhub_key")
            or cfg.get("api_key")
            or os.environ.get("FINNHUB_API_KEY")
            or os.environ.get("FINNHUB_KEY")
            or ""
        )
        self.universe = list(cfg.get("universe") or self.DEFAULT_UNIVERSE)
        self._client = None
        if self.api_key:
            try:
                import finnhub

                self._client = finnhub.Client(api_key=self.api_key)
            except Exception as exc:
                logger.warning("Finnhub insider client init failed: %s", exc)

    def _parse_transaction(self, symbol: str, raw: dict[str, Any]) -> InsiderTransaction | None:
        code = str(raw.get("transactionCode") or "").upper()
        price = float(raw.get("transactionPrice") or 0)
        shares = float(raw.get("share") or 0)
        if price <= 0 and shares <= 0:
            return None
        value = price * shares
        change = raw.get("change")
        try:
            change_f = float(change) if change is not None else None
        except (TypeError, ValueError):
            change_f = None
        return InsiderTransaction(
            symbol=symbol.upper(),
            name=str(raw.get("name") or "Unknown"),
            title=str(raw.get("officerTitle") or raw.get("title") or ""),
            transaction_date=str(raw.get("transactionDate") or ""),
            transaction_code=code,
            price=price,
            shares=shares,
            value=value,
            change=change_f,
            filing_date=str(raw.get("filingDate") or ""),
        )

    def fetch_symbol_transactions(
        self, symbol: str, from_date: str, to_date: str
    ) -> list[InsiderTransaction]:
        if not self._client:
            return []
        try:
            data = self._client.stock_insider_transactions(
                symbol.upper(), from_date, to_date
            )
        except Exception as exc:
            logger.debug("insider fetch %s failed: %s", symbol, exc)
            return []
        out: list[InsiderTransaction] = []
        for raw in (data or {}).get("data") or []:
            tx = self._parse_transaction(symbol, raw)
            if tx:
                out.append(tx)
        return out

    def _is_high_conviction(self, tx: InsiderTransaction) -> bool:
        """≥25% shareholding change, or effectively new position (100%+)."""
        if tx.change is None:
            return False
        try:
            chg = float(tx.change)
        except (TypeError, ValueError):
            return False
        if not tx.is_buy:
            return False
        return chg >= 25 or chg >= 100

    def summarize_day(
        self,
        date: str | None = None,
        symbols: list[str] | None = None,
        extra_symbols: list[str] | None = None,
    ) -> InsiderDaySummary:
        target = date or datetime.now().strftime("%Y-%m-%d")
        pool = list(symbols or self.universe)
        if extra_symbols:
            for s in extra_symbols:
                if s.upper() not in pool:
                    pool.append(s.upper())

        all_tx: list[InsiderTransaction] = []
        if not self._client:
            return InsiderDaySummary(date=target, transactions=[])

        from_date = (datetime.strptime(target, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
        for sym in pool:
            txs = self.fetch_symbol_transactions(sym, target, target)
            if not txs:
                txs = self.fetch_symbol_transactions(sym, from_date, target)
            for tx in txs:
                if tx.transaction_date == target or tx.filing_date == target:
                    all_tx.append(tx)

        buys = [t for t in all_tx if t.is_buy]
        sells = [t for t in all_tx if t.is_sell]
        buy_syms = {t.symbol for t in buys}
        sell_syms = {t.symbol for t in sells}

        buy_by_sym: dict[str, list[InsiderTransaction]] = {}
        for t in buys:
            buy_by_sym.setdefault(t.symbol, []).append(t)

        cluster = sum(1 for sym, group in buy_by_sym.items() if len(group) >= 2)
        high_conv = sum(1 for t in buys if self._is_high_conviction(t))

        summary = InsiderDaySummary(
            date=target,
            buy_value=sum(t.value for t in buys),
            sell_value=sum(t.value for t in sells),
            buy_count=len(buys),
            sell_count=len(sells),
            buy_symbols=len(buy_syms),
            sell_symbols=len(sell_syms),
            high_conviction=high_conv,
            cluster_buying=cluster,
            transactions=all_tx,
        )
        return summary

    def rank_transactions(
        self,
        transactions: list[InsiderTransaction],
        sort: str = "composite",
    ) -> list[dict[str, Any]]:
        """Rank by conviction, amount, or buy priority composite."""
        ranked: list[tuple[float, InsiderTransaction]] = []
        for tx in transactions:
            conviction = 0.0
            if self._is_high_conviction(tx):
                conviction = 1.0
            elif tx.change is not None:
                conviction = min(1.0, abs(tx.change) / 100)
            amount_score = min(1.0, tx.value / 5_000_000)
            buy_bonus = 0.3 if tx.is_buy else 0.0
            if sort == "conviction":
                score = conviction
            elif sort == "amount":
                score = amount_score
            elif sort == "buy":
                score = buy_bonus + amount_score
            else:
                score = conviction * 0.4 + amount_score * 0.35 + buy_bonus * 0.25
            ranked.append((score, tx))

        ranked.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                **InsiderDaySummary._tx_dict(tx),
                "rank_score": round(score, 4),
            }
            for score, tx in ranked
        ]
