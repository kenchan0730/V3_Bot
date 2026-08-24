"""Persist quiz progress and auto-learned pattern statistics."""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path("data/candle_learning")
STATS_FILE = DEFAULT_DIR / "auto_stats.json"
PROGRESS_FILE = DEFAULT_DIR / "progress.json"


def _ensure_dir(path=None):
    path = path or DEFAULT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_stats(stats, path=None):
    path = path or STATS_FILE
    _ensure_dir(path.parent)
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "patterns": stats,
    }
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp.replace(path)
    logger.info(f"Candle Lab 统计已保存至 {path}")
    return payload


def load_stats(path=None):
    path = path or STATS_FILE
    if not path.exists():
        return {"saved_at": None, "patterns": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning(f"读取 Candle Lab 统计失败: {exc}")
        return {"saved_at": None, "patterns": {}}
    return data


def load_progress(path=None):
    path = path or PROGRESS_FILE
    if not path.exists():
        return {"quiz": {}, "weak_spots": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning(f"读取学习进度失败: {exc}")
        return {"quiz": {}, "weak_spots": {}}


def save_progress(progress, path=None):
    path = path or PROGRESS_FILE
    _ensure_dir(path.parent)
    progress["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


def record_quiz_result(pattern_name, correct, path=None):
    progress = load_progress(path)
    quiz = progress.setdefault("quiz", {})
    entry = quiz.setdefault(pattern_name, {"correct": 0, "wrong": 0})
    if correct:
        entry["correct"] += 1
    else:
        entry["wrong"] += 1
        weak = progress.setdefault("weak_spots", {})
        weak[pattern_name] = weak.get(pattern_name, 0) + 1
    save_progress(progress, path)
    return progress


def top_weak_spots(limit=3, path=None):
    progress = load_progress(path)
    weak = progress.get("weak_spots", {})
    ranked = sorted(weak.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:limit]
