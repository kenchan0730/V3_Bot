"""Shared OHLCV helpers: column normalisation and data quality validation."""

import logging
from datetime import date

import pandas as pd

from core.market_calendar import MarketCalendar

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def normalize_columns(df):
    """Convert all column names to lowercase and return the transformed DataFrame."""
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(col).lower() for col in df.columns]
    return df


def latest_bar_date(df):
    """Best-effort extraction of the most recent bar date."""
    if df is None or len(df) == 0:
        return None
    if "date" in df.columns:
        try:
            return pd.to_datetime(df["date"].iloc[-1]).date()
        except Exception:
            pass
    try:
        index_value = df.index[-1]
        parsed = pd.to_datetime(index_value)
        return parsed.date()
    except Exception:
        return None


def previous_trading_day(reference=None):
    """Previous NYSE session, skipping weekends and market holidays."""
    return MarketCalendar.previous_trading_day(reference)


def trading_days_between(older, newer):
    """Count NYSE sessions strictly after `older` up to and including `newer`."""
    return MarketCalendar.trading_days_between(older, newer)


def validate_freshness(df, max_age_trading_days=2, reference=None):
    """Reject stale OHLCV data.

    Returns (is_fresh, age_in_trading_days, message).
    """
    reference = reference or date.today()
    bar_date = latest_bar_date(df)
    if bar_date is None:
        return False, None, "無法判定最後一根 K 線日期"

    age = trading_days_between(bar_date, reference)
    if age == 0:
        return True, 0, f"數據為今日 ({bar_date})"
    if age <= max_age_trading_days:
        return True, age, f"數據為 {bar_date}，落後 {age} 個交易日"
    return False, age, f"數據過期: 最後一根 K 線 {bar_date}，落後 {age} 個交易日"


def validate_ohlcv(df, min_bars=60):
    """Structural and sanity checks before the data reaches strategy code."""
    if df is None or len(df) == 0:
        return False, "數據為空"
    if len(df) < min_bars:
        return False, f"數據不足 ({len(df)} < {min_bars})"

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        return False, f"缺少欄位: {', '.join(missing)}"

    tail = df.tail(min_bars)
    if tail[list(REQUIRED_COLUMNS)].isna().any().any():
        return False, "近期數據含缺失值"

    last = df.iloc[-1]
    if float(last["close"]) <= 0:
        return False, f"收盤價異常: {last['close']}"
    if not (float(last["low"]) <= float(last["close"]) <= float(last["high"])):
        return False, "最後一根 K 線的高低收不一致"
    if float(last["volume"]) < 0:
        return False, "成交量為負數"

    return True, "OK"


def detect_price_outlier(df, max_daily_move_pct=40.0):
    """Flag an implausible single-day move that usually signals bad data."""
    if df is None or len(df) < 2 or "close" not in df.columns:
        return False, 0.0
    try:
        current = float(df["close"].iloc[-1])
        previous = float(df["close"].iloc[-2])
    except (TypeError, ValueError):
        return False, 0.0
    if previous <= 0:
        return False, 0.0
    move = (current / previous - 1) * 100
    return abs(move) > max_daily_move_pct, move


def intraday_quality_report(df, min_bars=12, max_bar_move_pct=10.0):
    """Quality gate for minute bars, mirroring the daily checks.

    Freshness is not re-checked here (the intraday fetcher already filters to
    today's session), but structure and per-bar outliers are, so minute data is
    held to the same standard as daily data.
    """
    if df is None or len(df) == 0:
        return {"ok": False, "stage": "structure", "message": "盤中數據為空"}
    if len(df) < min_bars:
        return {
            "ok": False, "stage": "structure",
            "message": f"盤中數據不足 ({len(df)} < {min_bars})",
        }

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        return {
            "ok": False, "stage": "structure",
            "message": f"盤中缺少欄位: {', '.join(missing)}",
        }
    if df[list(REQUIRED_COLUMNS)].isna().any().any():
        return {"ok": False, "stage": "structure", "message": "盤中數據含缺失值"}

    last = df.iloc[-1]
    if float(last["close"]) <= 0:
        return {
            "ok": False, "stage": "structure",
            "message": f"盤中收盤價異常: {last['close']}",
        }
    if not (float(last["low"]) <= float(last["close"]) <= float(last["high"])):
        return {"ok": False, "stage": "structure", "message": "盤中高低收不一致"}

    is_outlier, move = detect_price_outlier(df, max_bar_move_pct)
    if is_outlier:
        return {
            "ok": False, "stage": "outlier",
            "message": f"單根分鐘棒波動 {move:.1f}% 超出 {max_bar_move_pct}%，疑似錯誤數據",
        }

    return {"ok": True, "stage": "passed", "message": f"盤中數據 {len(df)} 根，品質正常"}


def quality_report(df, min_bars=60, max_age_trading_days=2, max_daily_move_pct=40.0, reference=None):
    """Run every check and return a single verdict used by the trading loop."""
    ok_structure, structure_msg = validate_ohlcv(df, min_bars)
    if not ok_structure:
        return {"ok": False, "stage": "structure", "message": structure_msg, "age": None}

    is_fresh, age, fresh_msg = validate_freshness(df, max_age_trading_days, reference)
    if not is_fresh:
        return {"ok": False, "stage": "freshness", "message": fresh_msg, "age": age}

    is_outlier, move = detect_price_outlier(df, max_daily_move_pct)
    if is_outlier:
        return {
            "ok": False, "stage": "outlier", "age": age,
            "message": f"單日波動 {move:.1f}% 超出 {max_daily_move_pct}%，疑似錯誤數據",
        }

    return {"ok": True, "stage": "passed", "message": fresh_msg, "age": age}
