"""One-shot diagnostic for V4.5 Desktop (run from V4.5_Bot root)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "V4.5_Desktop" / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))

from core.config_loader import load_dotenv  # noqa: E402

ENV_CANDIDATES = [
    ROOT / "data" / ".env",
    ROOT / "V4.5_Desktop" / "data" / ".env",
]


def check(name: str, ok: bool, detail: str = "", *, hard: bool = True) -> bool:
    if ok:
        mark = "OK"
    elif hard:
        mark = "FAIL"
    else:
        mark = "WARN"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok if hard else True


def _load_env() -> Path | None:
    for path in ENV_CANDIDATES:
        if path.exists():
            load_dotenv(str(path))
            return path
    return None


def main() -> int:
    print(f"Project root: {ROOT}")
    print()

    env_path = _load_env()
    wrong_env = ROOT / "V4.5_Desktop" / "data" / ".env"
    correct_env = ROOT / "data" / ".env"

    hard_fails = 0
    soft_fails = 0

    if env_path is None:
        if not check("data/.env exists", False, str(correct_env)):
            hard_fails += 1
        print("       TIP: copy data\\.env.example to data\\.env (NOT V4.5_Desktop\\data\\)")
    elif env_path == wrong_env:
        if not check("data/.env location", False, f"found at wrong path: {wrong_env}", hard=True):
            hard_fails += 1
        print("       FIX: move .env to V4.5_Bot\\data\\.env then restart API")
    else:
        check("data/.env exists", True, str(env_path))

    key = os.environ.get("FINNHUB_KEY") or os.environ.get("FINNHUB_API_KEY") or ""
    if not check("FINNHUB_KEY loaded", bool(key), f"length={len(key)}" if key else "add to data/.env", hard=False):
        soft_fails += 1

    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import yfinance  # noqa: F401
        check("Python packages", True)
    except ImportError as exc:
        if not check("Python packages", False, str(exc)):
            hard_fails += 1

    dist = ROOT / "V4.5_Desktop" / "frontend" / "dist" / "index.html"
    if not check("Frontend build", dist.exists(), "run setup.bat if missing"):
        hard_fails += 1

    try:
        from services.market_cache import quote_one, fetch_ohlcv  # noqa: E402

        q = quote_one("AAPL")
        quote_ok = float(q.get("price") or 0) > 0
        if not check("AAPL quote (live price)", quote_ok, str(q)):
            hard_fails += 1

        bars = fetch_ohlcv("AAPL", period="6mo")
        if not check("AAPL K-line", len(bars) > 0, f"bars={len(bars)}", hard=False):
            soft_fails += 1
    except Exception as exc:
        if not check("Market data test", False, str(exc)):
            hard_fails += 1

    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=3) as resp:
            body = resp.read(200).decode("utf-8", errors="replace")
        check("API running", resp.status == 200, body[:100])
    except Exception as exc:
        if not check("API running", False, "run open.bat first"):
            hard_fails += 1
        print(f"       Detail: {exc}")

    print()
    if hard_fails:
        print(f"RESULT: {hard_fails} blocking error(s) — fix [FAIL] above before open.bat")
        return 1
    if soft_fails:
        print(f"RESULT: {soft_fails} warning(s) — app can run; fix [WARN] for full data")
        return 0
    print("RESULT: all checks passed — run open.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
