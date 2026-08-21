import urllib.request
import csv
from datetime import datetime
from io import StringIO

class MarketBreadth:
    SOURCES = [
        "https://tradermonty.github.io/market-breadth-analysis/market_breadth_summary.csv",
        "https://raw.githubusercontent.com/tradermonty/claude-trading-skills/main/skills/market-breadth-analyzer/references/market_breadth_summary.csv"
    ]

    @staticmethod
    def fetch_csv(url):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            print(f"⚠️ 獲取數據失敗 ({url}): {e}")
            return None

    @staticmethod
    def get_breadth_score():
        for source in MarketBreadth.SOURCES:
            csv_data = MarketBreadth.fetch_csv(source)
            if not csv_data:
                continue
            try:
                reader = csv.DictReader(StringIO(csv_data))
                rows = list(reader)
                if not rows:
                    continue
                latest = rows[-1]
                score = float(latest.get("composite_score", 50))
                date = latest.get("date", datetime.now().strftime("%Y-%m-%d"))
                return {
                    "score": score,
                    "zone": latest.get("health_zone", "NEUTRAL"),
                    "date": date,
                    "components": {
                        "breadth_level_trend": float(latest.get("breadth_level_trend", 0)),
                        "ma_crossover": float(latest.get("ma_crossover", 0)),
                        "peak_trough": float(latest.get("peak_trough", 0)),
                        "bearish_signal": float(latest.get("bearish_signal", 0)),
                        "historical_percentile": float(latest.get("historical_percentile", 0)),
                        "sp500_divergence": float(latest.get("sp500_divergence", 0))
                    }
                }
            except Exception as e:
                print(f"⚠️ 解析數據失敗 ({source}): {e}")
                continue
        print("⚠️ 所有數據源失敗，使用默認值 (50/100)")
        return {
            "score": 50,
            "zone": "NEUTRAL",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "components": {
                "breadth_level_trend": 0,
                "ma_crossover": 0,
                "peak_trough": 0,
                "bearish_signal": 0,
                "historical_percentile": 0,
                "sp500_divergence": 0
            }
        }

    @staticmethod
    def get_health_zone(score):
        if score >= 80:
            return "STRONG", "✅ 市場寬度強勁"
        elif score >= 60:
            return "HEALTHY", "✅ 市場健康"
        elif score >= 40:
            return "NEUTRAL", "⏳ 市場中性"
        elif score >= 20:
            return "WEAKENING", "⚠️ 市場轉弱"
        else:
            return "CRITICAL", "🔴 市場危急"

    @staticmethod
    def get_exposure_recommendation(score):
        if score >= 80:
            return 100
        elif score >= 60:
            return 75
        elif score >= 40:
            return 50
        elif score >= 20:
            return 25
        else:
            return 0