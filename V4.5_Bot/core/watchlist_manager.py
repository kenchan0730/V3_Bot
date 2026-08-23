"""Tiered watchlist management: core + satellite + dynamic refresh.

Solves the 'narrow watchlist' problem by:
1. Preserving hand-picked core names (higher conviction)
2. Rotating satellite names from scanner + quant rank
3. De-duplicating correlated names before each session
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import yfinance as yf

from core.correlation import clustered_pairs, correlation_matrix
from core.data_utils import normalize_columns
from core.quant_engine import QuantEngine
from core.scanner_pool import ScannerPool

logger = logging.getLogger(__name__)


class WatchlistManager:
    DEFAULTS = {
        "core": [],
        "satellite": [],
        "static": [],
        "max_active": 20,
        "max_satellite": 12,
        "max_core": 8,
        "refresh_hours": 168,
        "persist_file": "data/watchlist.json",
        "scanner": {},
        "rank_by": "z_score",
        "correlation_threshold": 0.78,
        "always_include_positions": True,
    }

    def __init__(self, config=None, portfolio=None):
        wl_cfg = config or {}
        if isinstance(wl_cfg, list):
            wl_cfg = {"static": wl_cfg}
        self.cfg = {**self.DEFAULTS, **wl_cfg}
        self.portfolio = portfolio
        self.scanner = ScannerPool(self.cfg.get("scanner", {}))
        self._active = []
        self._last_refresh = 0.0
        self._meta = {}
        self._load_persisted()

    def _load_persisted(self):
        path = Path(self.cfg.get("persist_file", "data/watchlist.json"))
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._active = data.get("active", [])
            self._last_refresh = float(data.get("last_refresh_epoch", 0))
            self._meta = data.get("meta", {})
        except Exception as exc:
            logger.warning(f"watchlist persist load failed: {exc}")

    def _save_persisted(self, active, meta=None):
        path = Path(self.cfg.get("persist_file", "data/watchlist.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "last_refresh_epoch": self._last_refresh,
            "active": active,
            "core": self.core_symbols(),
            "satellite": self.satellite_symbols(),
            "meta": meta or self._meta,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def core_symbols(self):
        core = list(self.cfg.get("core") or [])
        static = self.cfg.get("static") or []
        if not core and static:
            return [s.upper() for s in static[: int(self.cfg.get("max_core", 8))]]
        return [s.upper() for s in core]

    def satellite_symbols(self):
        return [s.upper() for s in (self.cfg.get("satellite") or [])]

    def get_active_watchlist(self, open_positions=None):
        if self._active:
            return list(self._active)
        return self._build_default(open_positions)

    def _build_default(self, open_positions=None):
        symbols = []
        seen = set()
        for sym in self.core_symbols() + self.satellite_symbols():
            sym = sym.upper()
            if sym not in seen:
                symbols.append(sym)
                seen.add(sym)
        if self.cfg.get("always_include_positions") and open_positions:
            for sym in open_positions:
                sym = sym.upper()
                if sym not in seen:
                    symbols.insert(0, sym)
                    seen.add(sym)
        max_active = int(self.cfg.get("max_active", 20))
        self._active = symbols[:max_active]
        return list(self._active)

    def needs_refresh(self, now=None):
        import time
        now = now or time.time()
        hours = float(self.cfg.get("refresh_hours", 168))
        if hours <= 0:
            return False
        return (now - self._last_refresh) >= hours * 3600

    def rank_candidates(self, symbols):
        ranked = []
        for symbol in symbols:
            try:
                df = yf.download(symbol, period="3mo", interval="1d", progress=False)
                if df is None or df.empty or len(df) < 60:
                    continue
                df = normalize_columns(df)
                quant = QuantEngine.dynamic_score(df)
                score = float(quant.get(self.cfg.get("rank_by", "z_score"), 0))
                ranked.append((symbol, score, quant))
            except Exception:
                continue
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def dedupe_correlated(self, symbols, threshold=None):
        threshold = threshold if threshold is not None else float(
            self.cfg.get("correlation_threshold", 0.78)
        )
        if len(symbols) < 2:
            return symbols

        closes = {}
        for sym in symbols:
            try:
                df = yf.download(sym, period="3mo", interval="1d", progress=False)
                if df is None or df.empty:
                    continue
                df = normalize_columns(df)
                closes[sym] = df["close"]
            except Exception:
                continue

        matrix = correlation_matrix(closes, use_weekly=True)
        if matrix is None or matrix.empty:
            return symbols

        clusters = clustered_pairs(matrix, threshold=threshold)
        drop = set()
        priority = {sym: idx for idx, sym in enumerate(symbols)}
        for a, b, corr in clusters:
            if a in drop or b in drop:
                continue
            loser = b if priority.get(a, 0) < priority.get(b, 99) else a
            drop.add(loser)
            logger.info(f"Watchlist dedupe: drop {loser} (corr {corr:.2f} with {a if loser == b else b})")

        return [s for s in symbols if s not in drop]

    def refresh(self, fundamental_filter=None, force=False):
        import time
        if not force and not self.needs_refresh():
            return self.get_active_watchlist()

        logger.info("WatchlistManager: refreshing satellite universe...")
        scanned = self.scanner.scan(limit=int(self.cfg.get("max_satellite", 12)) * 3)
        core = self.core_symbols()
        pool = list(core)
        seen = set(core)

        for sym in scanned:
            sym = sym.upper()
            if sym in seen:
                continue
            if fundamental_filter:
                ok, _reason = fundamental_filter.filter(sym)
                if not ok:
                    continue
            seen.add(sym)
            pool.append(sym)

        ranked = self.rank_candidates([s for s in pool if s not in core])
        satellite = []
        for sym, _score, _quant in ranked:
            if sym in core:
                continue
            satellite.append(sym)
            if len(satellite) >= int(self.cfg.get("max_satellite", 12)):
                break

        for sym in self.satellite_symbols():
            if sym not in core and sym not in satellite:
                satellite.append(sym)

        combined = core + satellite
        deduped = self.dedupe_correlated(combined)
        max_active = int(self.cfg.get("max_active", 20))
        active = deduped[:max_active]

        self._active = active
        self._last_refresh = time.time()
        self._meta = {
            "scanned": len(scanned),
            "ranked": len(ranked),
            "active_count": len(active),
        }
        self._save_persisted(active)
        logger.info(f"WatchlistManager: active list = {active}")
        return active
