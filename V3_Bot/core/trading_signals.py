from core.candle_patterns import CandlePatterns
from core.data_utils import normalize_columns

class TradingSignals:
    @staticmethod
    def get_combined_signal(df, price, vix, z_score, vol_ratio, ma20, ma50):
        df = normalize_columns(df)
        candle = CandlePatterns.identify_all(df)
        tech_bullish = (0.5 <= z_score <= 1.5 and vix <= 25 and
                        price > ma20 > ma50 and (vol_ratio > 1.5 or vol_ratio < 0.8))

        if candle["signal"] == "bullish" and candle["strength"] >= 0.4 and tech_bullish:
            entry = candle["entry"] or price + 0.01
            stop = candle["stop"] or price - (price * 0.02)
            risk = entry - stop
            target1 = round(entry + risk * 1.5, 2)
            target2 = round(entry + risk * 3.0, 2)
            return {
                "action": "STRONG_BUY",
                "entry": round(entry, 2),
                "stop": round(stop, 2),
                "target1": target1,
                "target2": target2,
                "confidence": "HIGH",
                "reason": f"K線信號: {', '.join(candle['patterns'])} + V4.0確認"
            }
        elif candle["signal"] == "bearish" and candle["strength"] <= -0.4:
            return {
                "action": "STRONG_SELL",
                "reason": f"K線形態: {', '.join(candle['patterns'])}"
            }
        else:
            return {
                "action": "HOLD",
                "reason": f"無強力信號 (K線強度 {candle['strength']})"
            }