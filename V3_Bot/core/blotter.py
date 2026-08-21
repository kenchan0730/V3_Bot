"""Append-only trade blotter for audit and compliance.

Every signal decision and every execution is written as an immutable row.
"""

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

FIELDS = [
    "timestamp_utc",
    "timestamp_local",
    "event_type",
    "symbol",
    "signal",
    "action",
    "z_score",
    "rsi",
    "vol_ratio",
    "shares",
    "price",
    "entry_price",
    "stop_price",
    "target_price",
    "order_id",
    "fill_price",
    "filled_qty",
    "status",
    "realized_pnl",
    "exposure_pct",
    "reason",
]


class Blotter:
    """CSV blotter opened in append mode; rows are never rewritten."""

    def __init__(self, path="logs/trade_blotter.csv"):
        self.path = Path(path)
        self._ensure_header()

    def _ensure_header(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists() or self.path.stat().st_size == 0:
                with open(self.path, "a", newline="", encoding="utf-8") as f:
                    csv.DictWriter(f, fieldnames=FIELDS).writeheader()
        except Exception as e:
            logger.error(f"Blotter 初始化失敗: {e}")

    def _write(self, row):
        payload = {field: "" for field in FIELDS}
        now = datetime.now(timezone.utc)
        payload["timestamp_utc"] = now.isoformat(timespec="seconds")
        payload["timestamp_local"] = datetime.now().isoformat(timespec="seconds")
        for key, value in row.items():
            if key in payload:
                payload[key] = value
        try:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=FIELDS).writerow(payload)
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            logger.error(f"Blotter 寫入失敗: {e}")

    def log_signal(self, symbol, signal, quant=None, vol_ratio=None, exposure_pct=None, reason=""):
        quant = quant or {}
        self._write({
            "event_type": "SIGNAL",
            "symbol": symbol,
            "signal": signal.get("action", ""),
            "z_score": quant.get("z_score", ""),
            "rsi": quant.get("rsi", ""),
            "vol_ratio": round(vol_ratio, 3) if vol_ratio is not None else "",
            "entry_price": signal.get("entry", ""),
            "stop_price": signal.get("stop", ""),
            "target_price": signal.get("target1", ""),
            "exposure_pct": exposure_pct if exposure_pct is not None else "",
            "reason": reason or signal.get("reason", ""),
        })

    def log_rejection(self, symbol, reason, stage="PRE_TRADE"):
        self._write({"event_type": f"REJECT_{stage}", "symbol": symbol, "reason": reason})

    def log_order(self, symbol, action, shares, order_id, entry, stop, target, status="SUBMITTED", reason=""):
        self._write({
            "event_type": "ORDER",
            "symbol": symbol,
            "action": action,
            "shares": shares,
            "order_id": order_id,
            "entry_price": entry,
            "stop_price": stop,
            "target_price": target,
            "status": status,
            "reason": reason,
        })

    def log_fill(self, symbol, action, filled_qty, fill_price, order_id, realized_pnl=None, status="FILLED"):
        self._write({
            "event_type": "FILL",
            "symbol": symbol,
            "action": action,
            "filled_qty": filled_qty,
            "fill_price": fill_price,
            "order_id": order_id,
            "realized_pnl": realized_pnl if realized_pnl is not None else "",
            "status": status,
        })

    def log_event(self, event_type, symbol="", reason="", **extra):
        row = {"event_type": event_type, "symbol": symbol, "reason": reason}
        row.update(extra)
        self._write(row)
