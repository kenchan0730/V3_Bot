# core/news_sentiment.py
"""Multi-source news sentiment aggregator with Finnhub-free defaults."""

from __future__ import annotations

import logging
import time
from datetime import datetime

from core.news_providers import (
    NewsItem,
    build_news_providers,
    dedupe_headlines,
    score_headline,
)

logger = logging.getLogger(__name__)


class NewsSentiment:
    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.threshold = float(self.config.get("sentiment_threshold", -0.2))
        self.days = int(self.config.get("days_to_analyze", 3))
        self.cache_ttl = int(self.config.get("cache_ttl_seconds", 300))
        self.fail_mode = str(self.config.get("fail_mode", "open")).lower()
        self.block_on_negative = bool(self.config.get("block_on_negative", True))
        self.max_headlines = int(self.config.get("max_headlines", 20))

        self.providers = build_news_providers(self.config)
        self._cache: dict[str, tuple[float, dict]] = {}

        # Backward compatibility for tests / legacy callers
        self.api_key = self.config.get("finnhub_key", "")
        self.client = None
        for provider in self.providers:
            if provider.name == "finnhub" and hasattr(provider, "_client"):
                self.client = provider._client
                break

        self.positive_words = [
            "beat", "surpass", "growth", "upgrade", "buy", "strong",
            "record", "high", "rise", "gain",
        ]
        self.negative_words = [
            "miss", "downgrade", "sell", "weak", "low", "fall",
            "drop", "loss", "decline", "cut",
        ]

    def get_sentiment(self, symbol):
        """Aggregate news sentiment across providers (-1 to +1)."""
        if not self.enabled:
            return self._neutral()

        cached = self._cache.get(symbol.upper())
        if cached and (time.time() - cached[0]) < self.cache_ttl:
            return cached[1]

        if not self.providers:
            result = self._neutral(reason="no providers configured")
            self._cache[symbol.upper()] = (time.time(), result)
            return result

        all_items: list[NewsItem] = []
        source_counts: dict[str, int] = {}
        errors = 0

        for provider in self.providers:
            try:
                items = provider.fetch(symbol, self.days)
                source_counts[provider.name] = len(items)
                all_items.extend(items)
            except Exception as exc:
                errors += 1
                logger.warning("%s news provider %s failed: %s", symbol, provider.name, exc)

        if not all_items:
            if errors and self.fail_mode == "closed":
                result = {
                    "score": 0,
                    "sentiment": "unknown",
                    "total": 0,
                    "details": [],
                    "sources": source_counts,
                    "blocked_reason": "all providers failed",
                }
            else:
                result = self._neutral(sources=source_counts)
            self._cache[symbol.upper()] = (time.time(), result)
            return result

        unique = dedupe_headlines(all_items)
        unique.sort(
            key=lambda item: item.published or datetime.min,
            reverse=True,
        )
        analyzed = unique[: self.max_headlines]

        weighted_sum = 0.0
        weight_total = 0.0
        details = []
        for item in analyzed:
            provider_weight = next(
                (p.weight for p in self.providers if p.name == item.provider),
                1.0,
            )
            score = item.sentiment_score if item.sentiment_score is not None else score_headline(item.headline)
            weighted_sum += score * provider_weight
            weight_total += provider_weight
            details.append(
                {
                    "headline": item.headline[:80] + "..." if len(item.headline) > 80 else item.headline,
                    "score": round(score, 3),
                    "provider": item.provider,
                }
            )

        avg_score = weighted_sum / weight_total if weight_total else 0.0
        if avg_score > abs(self.threshold):
            sentiment = "positive"
        elif avg_score < self.threshold:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        result = {
            "score": round(avg_score, 3),
            "sentiment": sentiment,
            "total": len(analyzed),
            "details": details[:5],
            "sources": source_counts,
        }
        self._cache[symbol.upper()] = (time.time(), result)
        return result

    def is_sentiment_ok(self, symbol):
        """Hard gate: block when aggregated sentiment is negative."""
        result = self.get_sentiment(symbol)
        if not self.block_on_negative:
            return True, self._format_message(result)

        if result.get("sentiment") == "negative":
            src = ", ".join(f"{k}:{v}" for k, v in (result.get("sources") or {}).items())
            return False, f"📰 新聞情緒負面 (評分 {result['score']}, 來源 {src or 'n/a'})"
        if result.get("sentiment") == "unknown" and self.fail_mode == "closed":
            return False, "📰 新聞來源全部失敗，fail_mode=closed 阻擋進場"
        return True, self._format_message(result)

    def _format_message(self, result):
        src = ", ".join(f"{k}:{v}" for k, v in (result.get("sources") or {}).items())
        return f"📰 新聞情緒 {result['sentiment']} (評分 {result['score']}, 來源 {src or 'n/a'})"

    @staticmethod
    def _neutral(reason=None, sources=None):
        payload = {
            "score": 0,
            "sentiment": "neutral",
            "total": 0,
            "details": [],
            "sources": sources or {},
        }
        if reason:
            payload["reason"] = reason
        return payload

    def _analyze_headline(self, headline):
        """Backward-compatible lexicon scorer for tests."""
        return score_headline(headline)
