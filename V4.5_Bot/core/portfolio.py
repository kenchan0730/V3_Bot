"""Portfolio-level risk controls: gross exposure, position count, sector and
single-name concentration, plus optional correlation-based exposure reduction.
"""

import logging
from datetime import date

logger = logging.getLogger(__name__)

DEFAULT_SECTOR_MAP = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Semiconductor",
    "AMD": "Semiconductor", "AVGO": "Semiconductor", "SMH": "Semiconductor",
    "GOOGL": "Technology", "AMZN": "ConsumerDisc", "TSLA": "ConsumerDisc",
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials",
    "XOM": "Energy", "CVX": "Energy",
    "JNJ": "Healthcare", "UNH": "Healthcare", "PFE": "Healthcare",
    "AVAH": "Healthcare", "EROC": "Energy", "QXO": "Industrials",
}


class Portfolio:
    """Tracks open positions and enforces book-level limits."""

    def __init__(self, config=None):
        cfg = config or {}
        self.max_gross_exposure_pct = float(cfg.get("max_gross_exposure_pct", 100.0))
        self.max_open_positions = int(cfg.get("max_open_positions", 5))
        self.max_sector_pct = float(cfg.get("max_sector_pct", 40.0))
        self.max_symbol_pct = float(cfg.get("max_symbol_pct", 50.0))
        self.max_total_open_risk_pct = float(cfg.get("max_total_open_risk_pct", 6.0))
        self.correlation_threshold = float(cfg.get("correlation_threshold", 0.8))
        self.sector_map = dict(DEFAULT_SECTOR_MAP)
        self.sector_map.update(cfg.get("sector_map", {}) or {})

        # symbol -> {"quantity", "avg_cost", "price", "market_value", "stop"}
        self.positions = {}
        # Stop prices recorded before broker fill (survives pre-position set_stop).
        self.intended_stops = {}
        # symbol -> ISO date of first entry, for the time stop.
        self.entry_dates = {}

    # ----- state sync -----

    def sync(self, broker_positions, prices=None):
        """Replace local view with broker truth.

        broker_positions: {symbol: {"quantity": n, "avg_cost": c}} or {symbol: qty}
        """
        prices = prices or {}
        merged = {}
        for symbol, data in (broker_positions or {}).items():
            if isinstance(data, dict):
                quantity = float(data.get("quantity", 0) or 0)
                avg_cost = float(data.get("avg_cost", 0) or 0)
            else:
                quantity = float(data or 0)
                avg_cost = 0.0
            if quantity == 0:
                continue
            price = float(prices.get(symbol, avg_cost) or avg_cost)
            existing_stop = (
                self.positions.get(symbol, {}).get("stop")
                or self.intended_stops.get(symbol)
            )
            merged[symbol] = {
                "quantity": quantity,
                "avg_cost": avg_cost,
                "price": price,
                "market_value": abs(quantity) * price,
                "stop": existing_stop,
                "entry_date": (
                    self.positions.get(symbol, {}).get("entry_date")
                    or self.entry_dates.get(symbol)
                ),
            }
        self.positions = merged
        for symbol in list(self.entry_dates):
            if symbol not in merged:
                self.entry_dates.pop(symbol, None)
        return self.positions

    def record_intended_stop(self, symbol, stop_price):
        """Remember stop before fill so protection checks can re-arm."""
        if not stop_price or stop_price <= 0:
            return
        self.intended_stops[symbol] = float(stop_price)
        if symbol in self.positions:
            self.positions[symbol]["stop"] = float(stop_price)

    def set_stop(self, symbol, stop_price):
        self.record_intended_stop(symbol, stop_price)

    # ----- time stop -----

    def record_entry_date(self, symbol, when=None):
        """First-entry date, used by the time stop. Re-entries do not reset it."""
        if symbol in self.entry_dates:
            return self.entry_dates[symbol]
        stamp = (when or date.today()).isoformat()
        self.entry_dates[symbol] = stamp
        if symbol in self.positions:
            self.positions[symbol]["entry_date"] = stamp
        return stamp

    def clear_entry_date(self, symbol):
        self.entry_dates.pop(symbol, None)
        if symbol in self.positions:
            self.positions[symbol].pop("entry_date", None)

    def holding_days(self, symbol, today=None):
        """Calendar days held, or ``None`` when the entry date is unknown."""
        stamp = self.entry_dates.get(symbol) or self.positions.get(symbol, {}).get("entry_date")
        if not stamp:
            return None
        try:
            entered = date.fromisoformat(str(stamp)[:10])
        except ValueError:
            return None
        return max(0, ((today or date.today()) - entered).days)

    def stale_positions(self, max_days, today=None):
        """Open positions past the time stop: [(symbol, days_held), ...]."""
        if not max_days or max_days <= 0:
            return []
        stale = []
        for symbol in self.positions:
            days = self.holding_days(symbol, today=today)
            if days is not None and days >= int(max_days):
                stale.append((symbol, days))
        return sorted(stale, key=lambda item: -item[1])

    def clear_stop(self, symbol):
        self.intended_stops.pop(symbol, None)
        if symbol in self.positions:
            self.positions[symbol].pop("stop", None)

    @property
    def stops(self):
        """Known stop price per symbol (held or pending), for protection re-arming."""
        result = dict(self.intended_stops)
        for symbol, pos in self.positions.items():
            stop = pos.get("stop")
            if stop:
                result[symbol] = float(stop)
        return result

    def update_price(self, symbol, price):
        if symbol in self.positions and price:
            self.positions[symbol]["price"] = float(price)
            self.positions[symbol]["market_value"] = abs(self.positions[symbol]["quantity"]) * float(price)

    # ----- metrics -----

    def sector_of(self, symbol):
        return self.sector_map.get(symbol.upper(), "UNKNOWN")

    def open_position_count(self):
        return len(self.positions)

    def gross_exposure(self):
        return sum(pos["market_value"] for pos in self.positions.values())

    def gross_exposure_pct(self, total_capital):
        if total_capital <= 0:
            return 0.0
        return self.gross_exposure() / total_capital * 100

    def sector_exposure(self):
        totals = {}
        for symbol, pos in self.positions.items():
            sector = self.sector_of(symbol)
            totals[sector] = totals.get(sector, 0.0) + pos["market_value"]
        return totals

    def open_risk(self):
        """Sum of (price - stop) * qty across positions that have a known stop."""
        total = 0.0
        for pos in self.positions.values():
            stop = pos.get("stop")
            if stop:
                total += max(0.0, (pos["price"] - stop)) * abs(pos["quantity"])
        return total

    def open_risk_pct(self, total_capital):
        if total_capital <= 0:
            return 0.0
        return self.open_risk() / total_capital * 100

    def has_position(self, symbol):
        return symbol in self.positions and self.positions[symbol]["quantity"] != 0

    def position_quantity(self, symbol):
        return int(self.positions.get(symbol, {}).get("quantity", 0))

    # ----- limit checks -----

    def check_book_limits(self, total_capital, max_gross_pct_override=None):
        """Book-wide gate evaluated before considering any new entry."""
        gross_cap = (
            float(max_gross_pct_override)
            if max_gross_pct_override is not None
            else self.max_gross_exposure_pct
        )
        if self.open_position_count() >= self.max_open_positions:
            return False, f"持倉數 {self.open_position_count()} 已達上限 {self.max_open_positions}"
        gross_pct = self.gross_exposure_pct(total_capital)
        if gross_pct >= gross_cap:
            return False, f"總曝險 {gross_pct:.1f}% 已達上限 {gross_cap}%"
        risk_pct = self.open_risk_pct(total_capital)
        if risk_pct >= self.max_total_open_risk_pct:
            return False, f"未平倉風險 {risk_pct:.2f}% 已達上限 {self.max_total_open_risk_pct}%"
        return True, "OK"

    def can_open(self, symbol, cost, total_capital, stop_risk=0.0, max_gross_pct_override=None):
        """Per-candidate gate. Returns (allowed, reason)."""
        if total_capital <= 0:
            return False, "資本為零"
        if self.has_position(symbol):
            return False, f"{symbol} 已有持倉，避免重複進場"

        ok_book, book_reason = self.check_book_limits(total_capital, max_gross_pct_override)
        if not ok_book:
            return False, book_reason

        symbol_pct = cost / total_capital * 100
        if symbol_pct > self.max_symbol_pct:
            return False, f"單一標的 {symbol_pct:.1f}% > 上限 {self.max_symbol_pct}%"

        projected_gross = (self.gross_exposure() + cost) / total_capital * 100
        gross_cap = (
            float(max_gross_pct_override)
            if max_gross_pct_override is not None
            else self.max_gross_exposure_pct
        )
        if projected_gross > gross_cap:
            return False, f"進場後總曝險 {projected_gross:.1f}% > 上限 {gross_cap}%"

        sector = self.sector_of(symbol)
        sector_value = self.sector_exposure().get(sector, 0.0) + cost
        sector_pct = sector_value / total_capital * 100
        if sector_pct > self.max_sector_pct:
            return False, f"{sector} 板塊曝險 {sector_pct:.1f}% > 上限 {self.max_sector_pct}%"

        projected_risk = (self.open_risk() + stop_risk) / total_capital * 100
        if projected_risk > self.max_total_open_risk_pct:
            return False, f"進場後未平倉風險 {projected_risk:.2f}% > 上限 {self.max_total_open_risk_pct}%"

        return True, "OK"

    # ----- correlation -----

    def correlation_scale(self, symbol, returns_by_symbol):
        """Halve size when the candidate is highly correlated with an open name."""
        if not returns_by_symbol or symbol not in returns_by_symbol:
            return 1.0
        candidate = returns_by_symbol[symbol]
        for held in self.positions:
            if held == symbol or held not in returns_by_symbol:
                continue
            try:
                corr = candidate.corr(returns_by_symbol[held])
            except Exception:
                continue
            if corr is not None and corr == corr and abs(corr) >= self.correlation_threshold:
                logger.info(f"{symbol} 與持倉 {held} 相關性 {corr:.2f}，倉位減半")
                return 0.5
        return 1.0

    def snapshot(self, total_capital):
        return {
            "open_positions": self.open_position_count(),
            "max_open_positions": self.max_open_positions,
            "gross_exposure": round(self.gross_exposure(), 2),
            "gross_exposure_pct": round(self.gross_exposure_pct(total_capital), 2),
            "open_risk": round(self.open_risk(), 2),
            "open_risk_pct": round(self.open_risk_pct(total_capital), 2),
            "sector_exposure": {k: round(v, 2) for k, v in self.sector_exposure().items()},
            "positions": {
                symbol: {
                    "quantity": pos["quantity"],
                    "price": round(pos["price"], 2),
                    "market_value": round(pos["market_value"], 2),
                    "stop": pos.get("stop"),
                    "entry_date": pos.get("entry_date") or self.entry_dates.get(symbol),
                }
                for symbol, pos in self.positions.items()
            },
        }
