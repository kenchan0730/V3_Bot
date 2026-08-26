"""V4.5 Desktop — FastAPI backend (intelligence-only, no auto-trading)."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BOT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from core.config_loader import load_dotenv
from core.data_utils import normalize_columns
from core.desktop_analyzer import DesktopAnalyzer, _load_config
from core.desktop_intelligence import DesktopIntelligence
from core.earnings_calendar import EarningsCalendar
from core.fundamental_filter import FundamentalFilter
from core.insider_tracker import InsiderTracker
from core.market_breadth import MarketBreadth
from services.desktop_regime import desktop_regime

from services.market_cache import (
    TTLCache,
    batch_etf_snapshots,
    batch_quotes,
    fetch_ohlcv,
    quote_one,
    sector_rows,
)
from core.yf_throttle import silence_yfinance_logs

silence_yfinance_logs()

logger = logging.getLogger(__name__)

load_dotenv(str(BOT_ROOT / "data" / ".env"))
if os.environ.get("FINNHUB_KEY") and not os.environ.get("FINNHUB_API_KEY"):
    os.environ["FINNHUB_API_KEY"] = os.environ["FINNHUB_KEY"]

app = FastAPI(title="V4.5 Desktop Intelligence", version="1.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG = _load_config()
WATCHLIST_PATH = BOT_ROOT / "data" / "desktop_watchlist.json"
DESKTOP_WATCHLIST_PATH = BOT_ROOT / "data" / "watchlist.json"

_news_cfg = dict(CONFIG.get("news") or {})
_news_cfg["finnhub_key"] = (
    os.environ.get("FINNHUB_API_KEY")
    or os.environ.get("FINNHUB_KEY")
    or _news_cfg.get("finnhub_key")
    or ""
)

intelligence = DesktopIntelligence(_news_cfg)
insider_tracker = InsiderTracker(_news_cfg)
earnings_cal = EarningsCalendar(_news_cfg)
fundamental = FundamentalFilter((CONFIG.get("fundamental") or {}))
analyzer = DesktopAnalyzer()

technical_cache = TTLCache(ttl_seconds=120)
ohlcv_cache = TTLCache(ttl_seconds=600)
quote_cache = TTLCache(ttl_seconds=45)
fund_cache = TTLCache(ttl_seconds=3600)
feed_cache = TTLCache(ttl_seconds=90)
bootstrap_cache = TTLCache(ttl_seconds=60)
name_cache = TTLCache(ttl_seconds=86400)
earnings_cache = TTLCache(ttl_seconds=300)

TOP_ETFS = [
    ("SPY", "S&P 500"),
    ("QQQ", "Nasdaq 100"),
    ("IWM", "Russell 2000"),
    ("DIA", "Dow Jones"),
    ("VTI", "Total Market"),
    ("VOO", "S&P 500 Vanguard"),
    ("IVV", "S&P 500 iShares"),
    ("AGG", "US Bonds"),
    ("GLD", "Gold"),
    ("TLT", "Treasury 20Y"),
]

INTERNAL_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM",
    "V", "UNH", "XOM", "AMD", "NFLX", "PLTR", "MU",
]

TIER_LABEL_FALLBACK = "Acceptable tier B (fundamentals deferred)"


def _load_watchlist() -> list[str]:
    if WATCHLIST_PATH.exists():
        try:
            data = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
            return [s.upper() for s in data.get("symbols", [])]
        except Exception:
            pass
    if DESKTOP_WATCHLIST_PATH.exists():
        try:
            data = json.loads(DESKTOP_WATCHLIST_PATH.read_text(encoding="utf-8"))
            active = data.get("active") or data.get("core") or []
            return [s.upper() for s in active[:20]]
        except Exception:
            pass
    return ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "TSLA", "AMD", "PLTR"]


def _save_watchlist(symbols: list[str]):
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "symbols": [s.upper() for s in symbols],
    }
    WATCHLIST_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _quote_snapshot(symbol: str) -> dict[str, Any]:
    sym = symbol.upper()
    cached = quote_cache.get(f"q:{sym}")
    if cached:
        return cached
    result = quote_one(sym)
    quote_cache.set(f"q:{sym}", result)
    return result


def _cached_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    unique = list(dict.fromkeys(s.upper() for s in symbols if s))
    missing = [s for s in unique if not quote_cache.get(f"q:{s}")]
    if missing:
        fetched = batch_quotes(missing)
        for sym, q in fetched.items():
            quote_cache.set(f"q:{sym}", q)
    return {s: quote_cache.get(f"q:{s}") or _empty_quote(s) for s in unique}


def _empty_quote(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "price": 0.0,
        "change_pct": 0.0,
        "direction": "flat",
    }


def _company_name(symbol: str) -> str:
    sym = symbol.upper()
    cached = name_cache.get(f"n:{sym}")
    if cached:
        return cached
    name_cache.set(f"n:{sym}", sym)
    return sym


def _technical_skeleton() -> dict[str, Any]:
    breadth = MarketBreadth.get_breadth_score()
    env = desktop_regime(breadth, _empty_quote("SPY"))
    return {
        "market_environment": env,
        "overall_market": [],
        "internals": {
            "up_ratio": 0,
            "down_ratio": 0,
            "advancing": 0,
            "declining": 0,
            "unchanged": 0,
        },
        "sectors": [],
        "headlines": [],
        "fundamentals_hot": [],
        "loading": True,
        "updated_at": datetime.now().isoformat(),
    }


def _build_technical() -> dict[str, Any]:
    breadth = MarketBreadth.get_breadth_score()
    spy_q = _quote_snapshot("SPY")
    env = desktop_regime(breadth, spy_q)
    quotes = _cached_quotes(INTERNAL_UNIVERSE)
    etf_rows = batch_etf_snapshots(TOP_ETFS)
    sectors = sector_rows()
    advancing = declining = unchanged = 0
    for sym in INTERNAL_UNIVERSE:
        pct = (quotes.get(sym) or {}).get("change_pct", 0)
        if pct > 0.05:
            advancing += 1
        elif pct < -0.05:
            declining += 1
        else:
            unchanged += 1
    total = max(1, advancing + declining + unchanged)
    hot_symbols = ["NVDA", "AMD", "PLTR", "META", "TSLA", "MU", "MRVL"]
    hot_quotes = _cached_quotes(hot_symbols)
    fundamentals_hot: list[dict[str, Any]] = []
    for sym in hot_symbols:
        q = hot_quotes.get(sym) or _quote_snapshot(sym)
        cached_f = fund_cache.get(f"f:{sym}")
        view = cached_f or {"tier": "B", "tier_label": TIER_LABEL_FALLBACK, "metrics": {}}
        fundamentals_hot.append({
            "symbol": sym,
            **q,
            "tier": view.get("tier", "B"),
            "tier_label": view.get("tier_label", TIER_LABEL_FALLBACK),
            "metrics": view.get("metrics", {}),
        })
    return {
        "market_environment": env,
        "overall_market": etf_rows,
        "internals": {
            "up_ratio": round(advancing / total * 100, 1),
            "down_ratio": round(declining / total * 100, 1),
            "advancing": advancing,
            "declining": declining,
            "unchanged": unchanged,
        },
        "sectors": sectors,
        "headlines": intelligence.get_headlines(limit=15),
        "fundamentals_hot": fundamentals_hot,
        "updated_at": datetime.now().isoformat(),
    }


def _build_bootstrap() -> dict[str, Any]:
    wl = _load_watchlist()
    feed = feed_cache.get_or_set("feed", lambda: intelligence.get_feed(limit=50))
    symbols: list[str] = []
    for item in feed:
        symbols.extend(item.get("symbols") or [])
    quotes = _cached_quotes(list(dict.fromkeys(symbols[:30] + wl)))
    for item in feed:
        if item.get("symbols"):
            item["quotes"] = [quotes.get(s, _quote_snapshot(s)) for s in item["symbols"][:4]]
    wl_items = [
        {**quotes.get(s, _quote_snapshot(s)), "name": _company_name(s)}
        for s in wl
    ]
    technical = technical_cache.get("technical_overview") or _technical_skeleton()
    today = datetime.now().strftime("%Y-%m-%d")
    week_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    def load_earnings():
        return earnings_cal.fetch_range(today, week_end)

    earnings_week = earnings_cache.get_or_set(f"ew:{today}:{week_end}", load_earnings)
    trends = feed_cache.get_or_set("trends", lambda: intelligence.get_hot_trends(limit=20))
    return {
        "feed": feed,
        "watchlist": {"symbols": wl, "items": wl_items},
        "technical": technical,
        "earnings_today": [e for e in earnings_week if str(e.get("date", ""))[:10] == today],
        "earnings_week": earnings_week,
        "trends": trends,
        "updated_at": datetime.now().isoformat(),
    }


def _prefetch_watchlist_charts():
    for sym in _load_watchlist():
        key = f"ohlcv:{sym.upper()}"
        if ohlcv_cache.get(key):
            continue
        ohlcv_cache.set(key, fetch_ohlcv(sym, period="2y"))
        time.sleep(1.2)


@app.on_event("startup")
def warmup_cache():
    import threading

    def _warm():
        try:
            key = _news_cfg.get("finnhub_key") or ""
            if key:
                test = quote_one("AAPL")
                if test.get("price", 0) > 0:
                    logger.info("Finnhub OK - AAPL $%s", test["price"])
                else:
                    logger.warning("FINNHUB_KEY is set but AAPL quote failed - check key at finnhub.io")
            else:
                logger.warning("No FINNHUB_KEY in data/.env - quotes will fail when Yahoo blocks you")

            intelligence.poll(force=True)
            wl = _load_watchlist()
            _cached_quotes(wl)
            bootstrap_cache.set("bootstrap", _build_bootstrap())
            try:
                technical_cache.set("technical_overview", _build_technical())
                bootstrap_cache.set("bootstrap", _build_bootstrap())
            except Exception as exc:
                logger.warning("technical build deferred: %s", exc)
            logger.info("Desktop cache warmed")
        except Exception as exc:
            logger.warning("warmup failed: %s", exc)

    threading.Thread(target=_warm, daemon=True).start()


@app.get("/api/health")
def health():
    finnhub_ok = bool(_news_cfg.get("finnhub_key"))
    sample = quote_one("AAPL") if finnhub_ok else _empty_quote("AAPL")
    return {
        "status": "ok",
        "mode": "intelligence-only",
        "auto_trade": False,
        "finnhub": finnhub_ok,
        "finnhub_live": finnhub_ok and sample.get("price", 0) > 0,
        "sample_aapl": sample,
        "data_hint": (
            "Add FINNHUB_KEY=your_key to data/.env and restart API."
            if not finnhub_ok or sample.get("price", 0) <= 0
            else None
        ),
    }


@app.get("/api/bootstrap")
def bootstrap():
    """Single call to preload main tabs."""
    cached = bootstrap_cache.get("bootstrap")
    if cached:
        return cached
    payload = _build_bootstrap()
    bootstrap_cache.set("bootstrap", payload)
    return payload


@app.get("/api/intelligence/feed")
def intelligence_feed(limit: int = 50):
    def build():
        feed = intelligence.get_feed(limit=limit)
        symbols = []
        for item in feed:
            symbols.extend(item.get("symbols") or [])
        quotes = _cached_quotes(symbols[:40])
        for item in feed:
            if item.get("symbols"):
                item["quotes"] = [quotes.get(s, _quote_snapshot(s)) for s in item["symbols"][:4]]
        return feed

    feed = feed_cache.get_or_set("feed", build)
    return {"items": feed[:limit], "updated_at": datetime.now().isoformat()}


@app.get("/api/intelligence/watchlist")
def get_watchlist():
    symbols = _load_watchlist()
    quotes = _cached_quotes(symbols)
    rows = [{**quotes.get(s, _quote_snapshot(s)), "name": _company_name(s)} for s in symbols]
    return {"symbols": symbols, "items": rows}


@app.post("/api/intelligence/watchlist/{symbol}")
def add_watchlist(symbol: str):
    sym = symbol.upper()
    symbols = _load_watchlist()
    if sym not in symbols:
        symbols.append(sym)
        _save_watchlist(symbols)
    return {"symbols": symbols}


@app.delete("/api/intelligence/watchlist/{symbol}")
def remove_watchlist(symbol: str):
    sym = symbol.upper()
    symbols = [s for s in _load_watchlist() if s != sym]
    _save_watchlist(symbols)
    return {"symbols": symbols}


@app.get("/api/intelligence/symbol/{symbol}")
def symbol_detail(symbol: str, analyze: bool = False):
    sym = symbol.upper()

    def load_ohlcv():
        data = fetch_ohlcv(sym, period="2y")
        if not data:
            data = fetch_ohlcv(sym, period="6mo")
        return data

    ohlcv = ohlcv_cache.get_or_set(f"ohlcv:{sym}", load_ohlcv)
    quote = _quote_snapshot(sym)
    news = intelligence.get_symbol_news(sym)
    cached_f = fund_cache.get(f"f:{sym}")
    if cached_f:
        fund = cached_f
    elif _news_cfg.get("finnhub_key"):
        fund = {"tier": "B", "tier_label": TIER_LABEL_FALLBACK, "metrics": {}}
    else:
        fund = fundamental.assess(sym).to_dict()
        fund_cache.set(f"f:{sym}", fund)

    today = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    earnings = earnings_cal.fetch_range(today, end, sym)

    return {
        "symbol": sym,
        "quote": quote,
        "ohlcv": ohlcv or [],
        "news": news,
        "fundamental": fund,
        "analysis": None,
        "earnings": earnings,
    }


@app.get("/api/intelligence/symbol/{symbol}/analysis")
def symbol_analysis(symbol: str):
    return analyzer.analyze_symbol(symbol.upper())


@app.get("/api/technical/overview")
def technical_overview():
    return technical_cache.get_or_set("technical_overview", _build_technical)


@app.get("/api/insider/summary")
def insider_summary(date: Optional[str] = None, sort: str = "composite"):
    target = date or datetime.now().strftime("%Y-%m-%d")
    extra = _load_watchlist()
    summary = insider_tracker.summarize_day(target, extra_symbols=extra)
    ranked = insider_tracker.rank_transactions(summary.transactions, sort=sort)
    data = summary.to_dict()
    data["ranking"] = ranked[:50]
    data["data_available"] = bool(insider_tracker._client)
    if not insider_tracker._client:
        data["notice"] = "請在 data/.env 設定 FINNHUB_KEY 以載入 Form 4 內部交易"
    return data


@app.get("/api/calendar/earnings")
def calendar_earnings(
    date: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    if date:
        from_d, to_d = date, date
    else:
        from_d = from_date or datetime.now().strftime("%Y-%m-%d")
        to_d = to_date or (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    def load():
        return earnings_cal.fetch_range(from_d, to_d)

    items = earnings_cache.get_or_set(f"ew:{from_d}:{to_d}", load)
    return {"from": from_d, "to": to_d, "items": items}


@app.get("/api/calendar/earnings/{symbol}")
def calendar_earnings_detail(symbol: str, date: Optional[str] = None):
    return earnings_cal.get_detail(symbol.upper(), date)


def _extract_symbols(text: str) -> list[str]:
    import re
    cleaned = re.sub(r"[^\w\s]", " ", text.upper())
    return [t for t in cleaned.split() if 1 <= len(t) <= 5 and t.isalpha()]


@app.get("/api/ai/chat")
def ai_chat(q: str = Query(..., min_length=1)):
    try:
        q_lower = q.lower().strip().strip('"').strip("'")
        symbols = _extract_symbols(q)
        if not symbols:
            symbols = _load_watchlist()[:3]
        breadth = MarketBreadth.get_breadth_score()
        regime = desktop_regime(breadth, _quote_snapshot("SPY"))
        answer_parts = [f"市場環境：{regime['label']}（分數 {regime['score']:.0f}/100）。"]
        for sym in symbols[:2]:
            qd = _quote_snapshot(sym)
            answer_parts.append(f"{sym}：現價 ${qd['price']}，今日 {qd['change_pct']:+.2f}%。")
            cached_f = fund_cache.get(f"f:{sym}")
            if cached_f:
                answer_parts.append(
                    f"  基本面等級 {cached_f.get('tier', '—')}：{cached_f.get('tier_label', '')}"
                )

        wants_signals = any(
            kw in q_lower for kw in ("買", "buy", "訊號", "signal", "可以買", "值得")
        )
        signals: list[dict[str, Any]] = []
        if wants_signals:
            signals = analyzer.get_signals(init_if_needed=False)
            if signals:
                answer_parts.append("V4.5 訊號：")
                for s in signals[:5]:
                    answer_parts.append(
                        f"  • {s['symbol']} {s.get('action') or s.get('verdict')} @ ${s.get('price')}"
                    )
            elif not analyzer._initialized:
                answer_parts.append("V4.5 訊號載入中（首次約需 1 分鐘，請稍後再問「買入訊號」）。")
            else:
                answer_parts.append("目前 watchlist 無強烈買入訊號。")

        return {
            "question": q,
            "answer": "\n".join(answer_parts),
            "signals": signals,
            "regime": regime["regime"],
        }
    except Exception as exc:
        logger.exception("ai_chat failed")
        raise HTTPException(500, f"AI 分析失敗：{exc}") from exc


@app.get("/api/ai/signals")
def ai_signals(force: bool = False):
    try:
        if force:
            signals = analyzer.get_signals(force=True, init_if_needed=True)
        else:
            signals = analyzer.get_signals(init_if_needed=False)
        return {"signals": signals, "updated_at": datetime.now().isoformat()}
    except Exception as exc:
        logger.exception("ai_signals failed")
        return {
            "signals": [],
            "updated_at": datetime.now().isoformat(),
            "notice": f"訊號載入失敗：{exc}",
        }


@app.get("/api/search")
def search_symbols(q: str = Query(..., min_length=1), limit: int = 20):
    results: list[dict[str, Any]] = []
    api_key = _news_cfg.get("finnhub_key") or ""
    if api_key:
        try:
            import finnhub

            data = finnhub.Client(api_key=api_key).symbol_lookup(q)
            for item in ((data or {}).get("result") or [])[:limit]:
                sym = item.get("symbol", "")
                if sym:
                    results.append({
                        "symbol": sym,
                        "name": item.get("description", ""),
                        "type": item.get("type", ""),
                    })
        except Exception as exc:
            logger.debug("finnhub search: %s", exc)
    if not results:
        q_up = q.upper()
        pool = INTERNAL_UNIVERSE + [e[0] for e in TOP_ETFS]
        for sym in pool:
            if q_up in sym or sym.startswith(q_up):
                results.append({"symbol": sym, "name": sym, "type": "equity"})
        results = results[:limit]
    return {"query": q, "results": results}


@app.get("/api/search/trends")
def search_trends(limit: int = 20):
    return {"trends": intelligence.get_hot_trends(limit=limit)}


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")
