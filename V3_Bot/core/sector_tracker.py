import yfinance as yf
import time

class SectorTracker:
    SECTORS = {
        "XLK": "Technology",
        "XLE": "Energy",
        "XLV": "Healthcare",
        "SMH": "Semiconductor"
    }

    @staticmethod
    def get_relative_strength(period="5d"):
        spy = 0
        try:
            spy_data = yf.download("SPY", period=period, interval="1d", progress=False)
            if len(spy_data) >= 2:
                spy = (spy_data["Close"].iloc[-1] / spy_data["Close"].iloc[0] - 1) * 100
        except:
            spy = 0
        relative = {}
        for etf, name in SectorTracker.SECTORS.items():
            try:
                data = yf.download(etf, period=period, interval="1d", progress=False)
                if len(data) >= 2:
                    perf = (data["Close"].iloc[-1] / data["Close"].iloc[0] - 1) * 100
                    relative[name] = round(perf - spy, 2)
                else:
                    relative[name] = 0
            except:
                relative[name] = 0
        return relative

    @staticmethod
    def get_sector_rating():
        rel_5d = SectorTracker.get_relative_strength("5d")
        rel_10d = SectorTracker.get_relative_strength("10d")
        weights = {}
        alerts = []
        for sector in SectorTracker.SECTORS.values():
            avg = (rel_5d.get(sector, 0) + rel_10d.get(sector, 0)) / 2
            weights[sector] = 100 if avg > -1 else max(100 - abs(avg) * 12, 50)
        if weights.get("Semiconductor", 100) < weights.get("Technology", 100) - 15:
            alerts.append("SMH 跑輸 XLK，半導體內部出現問題")
        return {"weights": weights, "alerts": alerts}