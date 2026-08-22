"""Theme / chokepoint registry — map market narratives to upstream tickers."""

import logging

logger = logging.getLogger(__name__)

DEFAULT_THEMES = {
    "ai_infrastructure": {
        "keywords": ["AI", "data center", "GPU"],
        "upstream": ["NVTS", "LITE", "SMCI", "AVGO", "MU"],
        "description": "瓶頸理論：賣鏟子（電源/光模組/設備）而非只追應用層",
    },
    "energy_transition": {
        "keywords": ["EV", "battery", "solar"],
        "upstream": ["PLUG", "ENPH", "FSLR", "ALB"],
    },
    "fintech_retail": {
        "keywords": ["rates", "retail trading"],
        "upstream": ["SOFI", "HOOD", "SQ"],
    },
    "healthcare_recovery": {
        "keywords": ["post-acute", "home health"],
        "upstream": ["AVAH", "ACHC", "OPCH"],
    },
}


class ThemeRegistry:
    DEFAULTS = {
        "enabled": True,
        "auto_expand_watchlist": False,
        "max_per_theme": 2,
        "themes": DEFAULT_THEMES,
        "active_themes": ["ai_infrastructure", "healthcare_recovery"],
    }

    def __init__(self, config=None):
        cfg = {**self.DEFAULTS, **(config or {})}
        themes = dict(DEFAULT_THEMES)
        themes.update(cfg.get("themes") or {})
        cfg["themes"] = themes
        self.cfg = cfg

    def active_symbols(self):
        if not self.cfg.get("enabled", True):
            return []
        symbols = []
        max_per = int(self.cfg.get("max_per_theme", 2))
        for theme_name in self.cfg.get("active_themes") or []:
            theme = self.cfg["themes"].get(theme_name, {})
            for sym in (theme.get("upstream") or [])[:max_per]:
                symbols.append(sym.upper())
        return list(dict.fromkeys(symbols))

    def suggest_for_sector(self, sector):
        mapping = {
            "Technology": "ai_infrastructure",
            "Healthcare": "healthcare_recovery",
            "Financials": "fintech_retail",
            "Energy": "energy_transition",
        }
        theme_name = mapping.get(sector)
        if not theme_name:
            return []
        return (self.cfg["themes"].get(theme_name) or {}).get("upstream", [])[:2]

    def describe(self):
        lines = []
        for name in self.cfg.get("active_themes") or []:
            t = self.cfg["themes"].get(name, {})
            lines.append(f"{name}: {t.get('description', t.get('keywords', ''))}")
        return lines
