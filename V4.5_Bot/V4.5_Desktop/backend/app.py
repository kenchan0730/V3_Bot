"""V4.5 Desktop — FastAPI backend (intelligence-only, no auto-trading)."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BOT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOT_ROOT))

from core.data_utils import normalize_columns
from core.desktop_analyzer import DesktopAnalyzer, _load_config
from core.desktop_intelligence import DesktopIntelligence
from core.earnings_calendar import EarningsCalendar
from core.fundamental_filter import FundamentalFilter
from core.insider_tracker import InsiderTracker
from core.market_breadth import MarketBreadth
from core.quant_engine import QuantEngine
from core.regime import RegimeDetector
from core.sector_tracker import SectorTracker

logger = logging.getLogger(__name__)

app = FastAPI(title="V4.5 Desktop Intelligence", version="1.0.0")
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

intelligence = DesktopIntelligence(CONFIG.get("news") or {})
insider_tracker = InsiderTracker(CONFIG.get("news") or {})
earnings_cal = EarningsCalendar(CONFIG.get("news") or {})
fundamental = FundamentalFilter((CONFIG.get("fundamental") or {}))
analyzer = DesktopAnalyzer()

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
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B",
    "JPM", "V", "UNH", "XOM", "LLY", "JNJ", "WMT", "MA", "PG", "AVGO",
    "HD", "CVX", "MRK", "ABBV", "COST", "PEP", "KO", "ADBE", "CRM",
    "NFLX", "AMD", "INTC", "QCOM", "TXN", "ORCL", "IBM", "GS", "MS",
    "BAC", "C", "WFC", "BLK", "PLTR", "MU", "MRVL", "CAT", "DE", "BA",
    "RTX", "GE", "HON", "LIN", "SPGI", "TMO", "ISRG", "AMAT", "LRCX",
    "NKE", "DIS", "CMCSA", "VZ", "T", "PFE", "ABT", "TMO", "DHR", "SYK",
    "LOW", "SBUX", "MCD", "UPS", "FDX", "GM", "F", "UBER", "ABNB", "SNOW",
]


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
    try:
        t = yf.Ticker(symbol.upper())
        info = t.fast_info
        price = float(info.last_price or info.last_price or 0)
        prev = float(info.previous_close or price)
        chg_pct = ((price - prev) / prev * 100) if prev else 0.0
        return {
            "symbol": symbol.upper(),
            "price": round(price, 2),
            "change_pct": round(chg_pct, 2),
            "direction": "up" if chg_pct >= 0 else "down",
        }
    except Exception:
        return {"symbol": symbol.upper(), "price": 0, "change_pct": 0, "direction": "flat"}


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "intelligence-only", "auto_trade": False}


@app.get("/api/intelligence/feed")
def intelligence_feed(limit: int = 50):
    feed = intelligence.get_feed(limit=limit)
    for item in feed:
        if item.get("symbols"):
            item["quotes"] = [_quote_snapshot(s) for s in item["symbols"][:4]]
    return {"items": feed, "updated_at": datetime.now().isoformat()}


@app.get("/api/intelligence/watchlist")
def get_watchlist():
    symbols = _load_watchlist()
    rows = []
    for sym in symbols:
        q = _quote_snapshot(sym)
        rows.append({**q, "name": sym})
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
def symbol_detail(symbol: str):
    sym = symbol.upper()
    try:
        hist = yf.download(sym, period="max", interval="1d", progress=False)
        if hist is None or hist.empty:
            raise HTTPException(404, f"No data for {sym}")
        df = normalize_columns(hist)
        ohlcv = []
        for idx, row in df.tail(2000).iterrows():
            ts = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
            ohlcv.append({
                "time": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
            })
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))

    quote = _quote_snapshot(sym)
    news = intelligence.get_symbol_news(sym)
    fund = fundamental.assess(sym).to_dict()
    analysis = analyzer.analyze_symbol(sym)

    today = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    earnings = earnings_cal.fetch_range(today, end, sym)

    return {
        "symbol": sym,
        "quote": quote,
        "ohlcv": ohlcv,
        "news": news,
        "fundamental": fund,
        "analysis": analysis,
        "earnings": earnings,
    }


@app.get("/api/technical/overview")
def technical_overview():
    breadth = MarketBreadth.get_breadth_score()
    regime = RegimeDetector(CONFIG.get("regime")).detect(
        breadth_score=breadth.get("score", 50)
    )
    env_score = round(regime.score, 1)

    etf_rows = []
    for sym, name in TOP_ETFS:
        try:
            raw = yf.download(sym, period="5d", interval="1d", progress=False)
            if raw is None or raw.empty:
                continue
            df = normalize_columns(raw)
            closes = df["close"]
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            first = float(closes.iloc[0])
            last = float(closes.iloc[-1])
            chg = (last / first - 1) * 100 if first else 0
            spark = [float(x) for x in closes.tail(20).tolist()]
            etf_rows.append({
                "symbol": sym,
                "name": name,
                "price": round(last, 2),
                "change_pct": round(chg, 2),
                "sparkline": spark,
            })
        except Exception as exc:
            logger.debug("etf %s: %s", sym, exc)

    advancing = declining = unchanged = 0
    for sym in INTERNAL_UNIVERSE:
        q = _quote_snapshot(sym)
        pct = q.get("change_pct", 0)
        if pct > 0.05:
            advancing += 1
        elif pct < -0.05:
            declining += 1
        else:
            unchanged += 1
    total = advancing + declining + unchanged
    up_ratio = round(advancing / total * 100, 1) if total else 0
    down_ratio = round(declining / total * 100, 1) if total else 0

    rel = SectorTracker.get_relative_strength("5d")
    sectors = []
    for etf, name in SectorTracker.SECTORS.items():
        perf = SectorTracker._period_return_pct(etf, "5d")
        sectors.append({
            "symbol": etf,
            "name": name,
            "change_pct": round(float(perf or 0), 2),
            "vs_spy": round(float(rel.get(name, 0)), 2),
        })
    sectors.sort(key=lambda x: x["change_pct"], reverse=True)
    sectors = sectors[:11]

    headlines = intelligence.get_headlines(limit=15)
    hot_symbols = ["NVDA", "AMD", "SMCI", "PLTR", "META", "TSLA", "COIN", "HOOD", "MU", "MRVL"]
    fundamentals_hot = []
    for sym in hot_symbols:
        view = fundamental.assess(sym)
        q = _quote_snapshot(sym)
        fundamentals_hot.append({
            "symbol": sym,
            **q,
            "tier": view.tier,
            "tier_label": view.tier_label if hasattr(view, "tier_label") else "",
            "metrics": view.metrics,
        })

    return {
        "market_environment": {
            "score": env_score,
            "label": regime.regime,
            "regime": regime.to_dict(),
            "breadth": breadth,
        },
        "overall_market": etf_rows,
        "internals": {
            "up_ratio": up_ratio,
            "down_ratio": down_ratio,
            "advancing": advancing,
            "declining": declining,
            "unchanged": unchanged,
        },
        "sectors": sectors,
        "headlines": headlines,
        "fundamentals_hot": fundamentals_hot,
        "updated_at": datetime.now().isoformat(),
    }


@app.get("/api/insider/summary")
def insider_summary(date: str | None = None, sort: str = "composite"):
    target = date or datetime.now().strftime("%Y-%m-%d")
    extra = _load_watchlist()
    summary = insider_tracker.summarize_day(target, extra_symbols=extra)
    ranked = insider_tracker.rank_transactions(summary.transactions, sort=sort)
    data = summary.to_dict()
    data["ranking"] = ranked[:50]
    return data


@app.get("/api/calendar/earnings")
def calendar_earnings(
    date: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
):
    if date:
        from_d, to_d = date, date
    else:
        from_d = from_date or datetime.now().strftime("%Y-%m-%d")
        to_d = to_date or (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    items = earnings_cal.fetch_range(from_d, to_d)
    return {"from": from_d, "to": to_d, "items": items}


@app.get("/api/calendar/earnings/{symbol}")
def calendar_earnings_detail(symbol: str, date: str | None = None):
    return earnings_cal.get_detail(symbol.upper(), date)


@app.get("/api/ai/chat")
def ai_chat(q: str = Query(..., min_length=1)):
    """Rule-based assistant using V4.5 analysis context."""
    q_lower = q.lower()
    symbols = []
    for tok in q.upper().replace(",", " ").split():
        if len(tok) <= 5 and tok.isalpha():
            symbols.append(tok)
    if not symbols:
        symbols = _load_watchlist()[:3]

    analyses = []
    for sym in symbols[:3]:
        try:
            analyses.append(analyzer.analyze_symbol(sym))
        except Exception as exc:
            analyses.append({"symbol": sym, "error": str(exc)})

    signals = analyzer.get_signals()
    regime = RegimeDetector(CONFIG.get("regime")).detect()

    answer_parts = [
        f"市場環境：{regime.regime}（分數 {regime.score:.0f}/100）。",
    ]
    for a in analyses:
        sym = a.get("symbol")
        sig = a.get("signal") or {}
        action = sig.get("action", "NONE")
        price = a.get("price")
        answer_parts.append(
            f"{sym}：階段 {a.get('stage')}，訊號 {action}，現價 ${price or 'N/A'}。"
        )
        if a.get("reason"):
            answer_parts.append(f"  原因：{a.get('reason')}")

    if "買" in q or "buy" in q_lower or "signal" in q_lower:
        if signals:
            answer_parts.append("目前 V4.5 訊號建議：")
            for s in signals[:5]:
                answer_parts.append(
                    f"  • {s['symbol']} {s.get('action')} @ ${s.get('price')}"
                )
        else:
            answer_parts.append("目前 watchlist 無強烈買入訊號。")

    return {
        "question": q,
        "answer": "\n".join(answer_parts),
        "analyses": analyses,
        "signals": signals,
        "regime": regime.to_dict(),
    }


@app.get("/api/ai/signals")
def ai_signals():
    return {"signals": analyzer.get_signals(), "updated_at": datetime.now().isoformat()}


@app.get("/api/search")
def search_symbols(q: str = Query(..., min_length=1), limit: int = 20):
    results: list[dict[str, Any]] = []
    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if api_key:
        try:
            import finnhub

            client = finnhub.Client(api_key=api_key)
            data = client.symbol_lookup(q)
            for item in (data or {}).get("result") or [][:limit]:
                sym = item.get("symbol", "")
                if not sym:
                    continue
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


# Serve frontend if built
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")
