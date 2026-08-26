"""Pluggable news providers — free-tier friendly, no single-vendor lock-in."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

POSITIVE_WORDS = (
    "beat", "surpass", "growth", "upgrade", "buy", "strong", "record",
    "high", "rise", "gain", "bullish", "outperform", "raise", "profit",
)
NEGATIVE_WORDS = (
    "miss", "downgrade", "sell", "weak", "low", "fall", "drop", "loss",
    "decline", "cut", "bearish", "underperform", "lawsuit", "fraud", "probe",
)


@dataclass
class NewsItem:
    headline: str
    provider: str
    url: str = ""
    published: datetime | None = None
    sentiment_score: float | None = None


def score_headline(headline: str) -> float:
    """Lexicon sentiment in [-1, 1]."""
    text = headline.lower()
    score = 0.0
    for word in POSITIVE_WORDS:
        if word in text:
            score += 0.2
    for word in NEGATIVE_WORDS:
        if word in text:
            score -= 0.2
    return max(-1.0, min(1.0, score))


class BaseNewsProvider(ABC):
    name: str = "base"
    weight: float = 1.0

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @abstractmethod
    def fetch(self, symbol: str, days: int) -> list[NewsItem]:
        ...


class YahooFinanceNewsProvider(BaseNewsProvider):
    name = "yahoo"

    def fetch(self, symbol: str, days: int) -> list[NewsItem]:
        items: list[NewsItem] = []
        try:
            raw = yf.Ticker(symbol.upper()).news or []
        except Exception as exc:
            logger.debug("%s yahoo news failed: %s", symbol, exc)
            return items

        cutoff = datetime.now() - timedelta(days=days)
        for entry in raw[:30]:
            title = (entry.get("title") or entry.get("headline") or "").strip()
            if not title:
                continue
            published = None
            ts = entry.get("providerPublishTime") or entry.get("pubDate")
            if ts:
                try:
                    published = datetime.fromtimestamp(int(ts))
                except (TypeError, ValueError, OSError):
                    published = None
            if published and published < cutoff:
                continue
            items.append(
                NewsItem(
                    headline=title,
                    provider=self.name,
                    url=entry.get("link") or entry.get("url") or "",
                    published=published,
                    sentiment_score=score_headline(title),
                )
            )
        return items


class GoogleNewsRssProvider(BaseNewsProvider):
    name = "google_rss"

    def fetch(self, symbol: str, days: int) -> list[NewsItem]:
        items: list[NewsItem] = []
        when = "3d" if days <= 3 else "7d"
        query = quote_plus(f"{symbol.upper()} stock when:{when}")
        url = (
            f"https://news.google.com/rss/search?q={query}"
            "&hl=en-US&gl=US&ceid=US:en"
        )
        try:
            resp = requests.get(url, timeout=12, headers={"User-Agent": "V45Bot/1.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as exc:
            logger.debug("%s google rss failed: %s", symbol, exc)
            return items

        for node in root.findall(".//item")[:25]:
            title = (node.findtext("title") or "").strip()
            if not title:
                continue
            link = node.findtext("link") or ""
            published = None
            pub = node.findtext("pubDate")
            if pub:
                try:
                    from email.utils import parsedate_to_datetime

                    published = parsedate_to_datetime(pub).replace(tzinfo=None)
                except (TypeError, ValueError):
                    published = None
            items.append(
                NewsItem(
                    headline=title,
                    provider=self.name,
                    url=link,
                    published=published,
                    sentiment_score=score_headline(title),
                )
            )
        return items


class FinnhubNewsProvider(BaseNewsProvider):
    name = "finnhub"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.api_key = self.config.get("api_key") or self.config.get("finnhub_key") or ""
        self._client = None
        if self.api_key:
            try:
                import finnhub

                self._client = finnhub.Client(api_key=self.api_key)
            except Exception as exc:
                logger.warning("Finnhub client init failed: %s", exc)

    def fetch(self, symbol: str, days: int) -> list[NewsItem]:
        if not self._client:
            return []
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        try:
            raw = self._client.company_news(symbol.upper(), _from=start_date, to=end_date)
        except Exception as exc:
            logger.debug("%s finnhub news failed: %s", symbol, exc)
            return []

        items: list[NewsItem] = []
        for entry in (raw or [])[:25]:
            headline = (entry.get("headline") or "").strip()
            if not headline:
                continue
            published = None
            ts = entry.get("datetime")
            if ts:
                try:
                    published = datetime.fromtimestamp(int(ts))
                except (TypeError, ValueError, OSError):
                    published = None
            items.append(
                NewsItem(
                    headline=headline,
                    provider=self.name,
                    url=entry.get("url") or "",
                    published=published,
                    sentiment_score=score_headline(headline),
                )
            )
        return items


class AlphaVantageNewsProvider(BaseNewsProvider):
    name = "alpha_vantage"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.api_key = self.config.get("api_key") or ""

    def fetch(self, symbol: str, days: int) -> list[NewsItem]:
        if not self.api_key:
            return []
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": symbol.upper(),
            "limit": 30,
            "apikey": self.api_key,
        }
        try:
            resp = requests.get(
                "https://www.alphavantage.co/query", params=params, timeout=15
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.debug("%s alpha vantage news failed: %s", symbol, exc)
            return []

        feed = payload.get("feed") or []
        cutoff = datetime.now() - timedelta(days=days)
        items: list[NewsItem] = []
        for entry in feed:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            published = None
            ts = entry.get("time_published")
            if ts and len(ts) >= 8:
                try:
                    published = datetime.strptime(ts[:15], "%Y%m%dT%H%M%S")
                except ValueError:
                    published = None
            if published and published < cutoff:
                continue

            av_score = None
            for ticker_info in entry.get("ticker_sentiment") or []:
                if ticker_info.get("ticker", "").upper().startswith(symbol.upper()):
                    try:
                        av_score = float(ticker_info.get("ticker_sentiment_score", 0))
                    except (TypeError, ValueError):
                        av_score = None
                    break

            items.append(
                NewsItem(
                    headline=title,
                    provider=self.name,
                    url=entry.get("url") or "",
                    published=published,
                    sentiment_score=av_score if av_score is not None else score_headline(title),
                )
            )
        return items


PROVIDER_REGISTRY: dict[str, type[BaseNewsProvider]] = {
    "yahoo": YahooFinanceNewsProvider,
    "google_rss": GoogleNewsRssProvider,
    "finnhub": FinnhubNewsProvider,
    "alpha_vantage": AlphaVantageNewsProvider,
}


def build_news_providers(config: dict[str, Any] | None) -> list[BaseNewsProvider]:
    """Build enabled providers from config.news.sources or sensible defaults."""
    cfg = config or {}
    sources_cfg = cfg.get("sources")
    finnhub_key = cfg.get("finnhub_key") or cfg.get("finnhub_api_key") or ""

    if not sources_cfg:
        sources_cfg = [
            {"name": "yahoo", "enabled": True, "weight": 1.0},
            {"name": "google_rss", "enabled": True, "weight": 0.8},
        ]
        if finnhub_key:
            sources_cfg.append(
                {"name": "finnhub", "enabled": True, "weight": 1.0, "api_key": finnhub_key}
            )
        av_key = cfg.get("alpha_vantage_key") or ""
        if av_key:
            sources_cfg.append(
                {
                    "name": "alpha_vantage",
                    "enabled": True,
                    "weight": 1.2,
                    "api_key": av_key,
                }
            )

    providers: list[BaseNewsProvider] = []
    for src in sources_cfg:
        if not src.get("enabled", True):
            continue
        name = str(src.get("name", "")).lower()
        cls = PROVIDER_REGISTRY.get(name)
        if not cls:
            logger.warning("Unknown news provider: %s", name)
            continue
        provider_cfg = dict(src)
        if name == "finnhub" and not provider_cfg.get("api_key"):
            provider_cfg["api_key"] = finnhub_key
        provider = cls(provider_cfg)
        provider.weight = float(src.get("weight", 1.0))
        providers.append(provider)
    return providers


def dedupe_headlines(items: list[NewsItem]) -> list[NewsItem]:
    """Drop near-duplicate headlines across providers."""
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in items:
        key = "".join(ch for ch in item.headline.lower() if ch.isalnum())[:80]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
