import pandas as pd

class CandlePatterns:
    @staticmethod
    def identify_all(df):
        if len(df) < 5:
            return {"patterns": [], "signal": "neutral", "strength": 0, "entry": None, "stop": None}

        c0 = df.iloc[-1]
        c1 = df.iloc[-2]
        c2 = df.iloc[-3]
        c3 = df.iloc[-4]
        c4 = df.iloc[-5]

        patterns = []
        strength = 0
        entry = None
        stop = None

        body0 = abs(c0['close'] - c0['open'])
        lower0 = min(c0['close'], c0['open']) - c0['low']
        upper0 = c0['high'] - max(c0['close'], c0['open'])
        body1 = abs(c1['close'] - c1['open'])
        lower1 = min(c1['close'], c1['open']) - c1['low']
        upper1 = c1['high'] - max(c1['close'], c1['open'])

        # 單根
        if lower0 > body0 * 2 and upper0 < body0 * 0.3:
            patterns.append("鎚頭")
            strength += 0.4
            entry = c0['high'] + 0.01
            stop = c0['low'] - 0.02
        if upper0 > body0 * 2 and lower0 < body0 * 0.3:
            patterns.append("射擊之星")
            strength -= 0.4
            stop = c0['high'] + 0.02

        # 雙根
        if (c1['close'] < c1['open'] and c0['close'] > c0['open'] and
            c0['open'] < c1['close'] and c0['close'] > c1['open']):
            patterns.append("看漲吞噬")
            strength += 0.6
            entry = c0['close'] + 0.01
            stop = c0['low'] - 0.02
        if (c1['close'] > c1['open'] and c0['close'] < c0['open'] and
            c0['open'] > c1['close'] and c0['close'] < c1['open']):
            patterns.append("看跌吞噬")
            strength -= 0.6
            stop = c0['high'] + 0.02

        if body0 < (c0['high'] - c0['low']) * 0.1:
            patterns.append("十字星")
            if lower0 > upper0 * 2:
                patterns.append("（蜻蜓）")
                strength += 0.3
                entry = c0['high'] + 0.01
                stop = c0['low'] - 0.02
            elif upper0 > lower0 * 2:
                patterns.append("（墓碑）")
                strength -= 0.3
                stop = c0['high'] + 0.02

        # 三根
        if len(df) >= 5:
            body2 = abs(c2['close'] - c2['open'])
            if (c2['close'] < c2['open'] and
                body1 < (c1['high'] - c1['low']) * 0.2 and
                c0['close'] > c0['open'] and
                c0['close'] > (c2['open'] + c2['close']) / 2):
                patterns.append("晨星")
                strength += 0.8
                entry = c0['close'] + 0.01
                stop = c0['low'] - 0.02
            if (c2['close'] > c2['open'] and
                body1 < (c1['high'] - c1['low']) * 0.2 and
                c0['close'] < c0['open'] and
                c0['close'] < (c2['open'] + c2['close']) / 2):
                patterns.append("黃昏星")
                strength -= 0.8
                stop = c0['high'] + 0.02

        if strength > 0.3:
            signal = "bullish"
        elif strength < -0.3:
            signal = "bearish"
        else:
            signal = "neutral"

        return {
            "patterns": patterns,
            "signal": signal,
            "strength": round(strength, 2),
            "entry": entry,
            "stop": stop
        }