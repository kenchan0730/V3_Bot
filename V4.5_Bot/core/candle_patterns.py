"""Candlestick pattern recognition.

``strength`` accumulates across every triggered pattern, but ``entry``/``stop``
are taken from the single strongest pattern so the levels always belong to the
formation that actually drives the score.
"""

import pandas as pd


class CandlePatterns:
    @staticmethod
    def identify_all(df):
        if len(df) < 5:
            return {
                "patterns": [], "signal": "neutral", "strength": 0,
                "entry": None, "stop": None, "driver": None,
            }

        c0 = df.iloc[-1]
        c1 = df.iloc[-2]
        c2 = df.iloc[-3]

        patterns = []
        triggered = []
        strength = 0

        body0 = abs(c0['close'] - c0['open'])
        lower0 = min(c0['close'], c0['open']) - c0['low']
        upper0 = c0['high'] - max(c0['close'], c0['open'])
        body1 = abs(c1['close'] - c1['open'])

        def record(name, delta, entry=None, stop=None):
            nonlocal strength
            patterns.append(name)
            strength += delta
            triggered.append({
                "name": name, "strength": delta, "entry": entry, "stop": stop,
            })

        # 單根
        if lower0 > body0 * 2 and upper0 < body0 * 0.3:
            record("鎚頭", 0.4, entry=c0['high'] + 0.01, stop=c0['low'] - 0.02)
        if upper0 > body0 * 2 and lower0 < body0 * 0.3:
            record("射擊之星", -0.4, stop=c0['high'] + 0.02)

        # 雙根
        if (c1['close'] < c1['open'] and c0['close'] > c0['open'] and
                c0['open'] < c1['close'] and c0['close'] > c1['open']):
            record("看漲吞噬", 0.6, entry=c0['close'] + 0.01, stop=c0['low'] - 0.02)
        if (c1['close'] > c1['open'] and c0['close'] < c0['open'] and
                c0['open'] > c1['close'] and c0['close'] < c1['open']):
            record("看跌吞噬", -0.6, stop=c0['high'] + 0.02)

        if body0 < (c0['high'] - c0['low']) * 0.1:
            patterns.append("十字星")
            if lower0 > upper0 * 2:
                record("（蜻蜓）", 0.3, entry=c0['high'] + 0.01, stop=c0['low'] - 0.02)
            elif upper0 > lower0 * 2:
                record("（墓碑）", -0.3, stop=c0['high'] + 0.02)

        # 三根
        if len(df) >= 5:
            if (c2['close'] < c2['open'] and
                    body1 < (c1['high'] - c1['low']) * 0.2 and
                    c0['close'] > c0['open'] and
                    c0['close'] > (c2['open'] + c2['close']) / 2):
                record("晨星", 0.8, entry=c0['close'] + 0.01, stop=c0['low'] - 0.02)
            if (c2['close'] > c2['open'] and
                    body1 < (c1['high'] - c1['low']) * 0.2 and
                    c0['close'] < c0['open'] and
                    c0['close'] < (c2['open'] + c2['close']) / 2):
                record("黃昏星", -0.8, stop=c0['high'] + 0.02)

        if strength > 0.3:
            signal = "bullish"
        elif strength < -0.3:
            signal = "bearish"
        else:
            signal = "neutral"

        driver = CandlePatterns._dominant(triggered, signal)
        entry = driver["entry"] if driver else None
        stop = driver["stop"] if driver else None

        return {
            "patterns": patterns,
            "signal": signal,
            "strength": round(strength, 2),
            "entry": entry,
            "stop": stop,
            "driver": driver["name"] if driver else None,
        }

    @staticmethod
    def _dominant(triggered, signal):
        """Strongest pattern aligned with the net signal direction."""
        if not triggered:
            return None
        if signal == "bullish":
            aligned = [p for p in triggered if p["strength"] > 0]
        elif signal == "bearish":
            aligned = [p for p in triggered if p["strength"] < 0]
        else:
            aligned = triggered
        if not aligned:
            aligned = triggered
        return max(aligned, key=lambda p: abs(p["strength"]))
