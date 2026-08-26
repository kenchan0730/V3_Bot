"""Global yfinance rate limiter (avoids Yahoo 429 blocks)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_last_call = 0.0
MIN_INTERVAL = 0.55


def throttled(fn: Callable[..., T], *args, **kwargs) -> T:
    global _last_call
    with _lock:
        now = time.time()
        wait = MIN_INTERVAL - (now - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        return fn(*args, **kwargs)


def silence_yfinance_logs() -> None:
    for name in ("yfinance", "yfinance.base", "yfinance.scrapers", "yfinance.scrapers.quote"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
