"""Pattern explanations for traders — loaded from patterns_catalog.yaml."""

from pathlib import Path

import yaml

_CATALOG_PATH = Path(__file__).with_name("patterns_catalog.yaml")
_CATALOG = None


def _load_catalog():
    global _CATALOG
    if _CATALOG is None:
        with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
            _CATALOG = yaml.safe_load(f).get("patterns", {})
    return _CATALOG


def explain(pattern_name):
    """Return trader-facing dict for a pattern, or a generic fallback."""
    catalog = _load_catalog()
    info = catalog.get(pattern_name)
    if not info:
        return {
            "name": pattern_name,
            "definition": "（暂无教学说明，请查阅 patterns_catalog.yaml）",
            "entry_stop": "",
            "fake_signals": [],
            "trader_tip": "",
        }
    return {"name": pattern_name, **info}


def format_explanation(pattern_name):
    """Single paragraph suitable for CLI / logs."""
    info = explain(pattern_name)
    lines = [
        f"【{info['name']}】{info.get('definition', '')}",
        f"进出场：{info.get('entry_stop', '')}",
    ]
    fakes = info.get("fake_signals") or []
    if fakes:
        lines.append("假信号：" + "；".join(fakes))
    tip = info.get("trader_tip")
    if tip:
        lines.append(f"提示：{tip}")
    return "\n".join(lines)
