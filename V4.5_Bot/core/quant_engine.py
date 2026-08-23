"""Four-factor quantitative score (momentum, volume, volatility, relative strength).

Weight calibration status: the default 35/25/20/20 split is an *unvalidated
engineering prior*, not a statistically fitted result. Run
``scripts/factor_sensitivity.py`` to grid-search weights against realised
profit factor before treating any split as evidence-based.

The volatility factor needs >= 120 bars (60 warm-up + 60 z-score window). With
a shorter history it returns 0.0 and its weight is silently redistributed, so
``dynamic_score`` reports ``factors_active`` to make that observable.
"""

import pandas as pd
import numpy as np
from core.data_utils import normalize_columns

DEFAULT_WEIGHTS = {
    "momentum": 0.35,
    "volume": 0.25,
    "volatility": 0.20,
    "relative_strength": 0.20,
}

MIN_BARS_FOR_SCORE = 60
MIN_BARS_FOR_VOLATILITY = 120


class QuantEngine:
    
    @staticmethod
    def _get_columns(df):
        normalize_columns(df)
        return 'close', 'high', 'low', 'volume'

    @staticmethod
    def _to_float(val):
        """安全轉換為 float，支援 Series"""
        if hasattr(val, 'iloc'):
            return float(val.iloc[-1])
        if hasattr(val, 'values'):
            return float(val.values[-1])
        return float(val)

    @staticmethod
    def calculate_zscore(series, window=60):
        """計算 Z-Score，確保回傳 Series"""
        mean = series.rolling(window).mean()
        std = series.rolling(window).std()
        return (series - mean) / (std + 1e-6)

    @staticmethod
    def calculate_rsi(df, period=14):
        """計算 RSI，確保回傳單一 float"""
        close_col, _, _, _ = QuantEngine._get_columns(df)
        close = df[close_col]
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        loss = loss + 1e-6
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        # 強制轉為 float
        try:
            rsi_value = float(rsi.iloc[-1])
        except (ValueError, TypeError, AttributeError):
            rsi_value = 50.0
        
        if pd.isna(rsi_value) or not np.isfinite(rsi_value):
            return 50.0
        return rsi_value

    @staticmethod
    def resolve_weights(weights=None):
        """Merge caller/config weights over the defaults and renormalise to 1.0."""
        merged = {**DEFAULT_WEIGHTS, **(weights or {})}
        clean = {}
        for key in DEFAULT_WEIGHTS:
            try:
                clean[key] = max(0.0, float(merged.get(key, DEFAULT_WEIGHTS[key])))
            except (TypeError, ValueError):
                clean[key] = DEFAULT_WEIGHTS[key]
        total = sum(clean.values())
        if total <= 0:
            return dict(DEFAULT_WEIGHTS)
        return {key: value / total for key, value in clean.items()}

    @staticmethod
    def compression_series(high, low, short_window=14, long_window=50):
        """Vectorised volatility-compression score (was an O(N) Python loop).

        Replaces the per-bar loop that made repeated ``dynamic_score`` calls in
        backtests O(N^2); results match the previous implementation.
        """
        atr_short = high.rolling(short_window).max() - low.rolling(short_window).min()
        atr_long = high.rolling(long_window).max() - low.rolling(long_window).min()
        ratio = (atr_short / atr_long.replace(0, np.nan)).fillna(1.0)
        raw = np.where(
            ratio <= 0.85, 1.5,
            np.where(ratio >= 1.3, -1.5, (1.3 - ratio) / (1.3 - 0.85) * 1.5 - 1.5),
        )
        return pd.Series(raw, index=high.index), ratio

    @staticmethod
    def dynamic_score(df, weights=None):
        df = normalize_columns(df)
        resolved = QuantEngine.resolve_weights(weights)
        if len(df) < MIN_BARS_FOR_SCORE:
            return {
                "z_score": 0.0,
                "z_momentum": 0.0,
                "z_volume": 0.0,
                "z_volatility": 0.0,
                "z_rs": 0.0,
                "compression_ratio": 1.0,
                "rsi": 50.0,
                "weights": resolved,
                "factors_active": [],
                "volatility_factor_active": False,
            }

        close_col, high_col, low_col, volume_col = QuantEngine._get_columns(df)

        close = df[close_col]
        volume = df[volume_col]
        high = df[high_col]
        low = df[low_col]

        # ----- 1. 價格動能（權重 35%） -----
        roc = (close / close.shift(20) - 1) * 100
        z_momentum_series = QuantEngine.calculate_zscore(roc, 60)
        z_momentum = QuantEngine._to_float(z_momentum_series.iloc[-1])
        if pd.isna(z_momentum) or not np.isfinite(z_momentum):
            z_momentum = 0.0

        # ----- 2. 成交量配合（權重 25%） -----
        z_volume_raw_series = QuantEngine.calculate_zscore(volume, 60)
        z_volume_raw = QuantEngine._to_float(z_volume_raw_series.iloc[-1])
        if pd.isna(z_volume_raw) or not np.isfinite(z_volume_raw):
            z_volume_raw = 0.0

        # 獲取最新收盤價（確保是 float）
        price_curr = QuantEngine._to_float(close.iloc[-1])
        price_prev = QuantEngine._to_float(close.iloc[-2]) if len(close) >= 2 else price_curr

        price_change = (price_curr / price_prev - 1) * 100 if price_prev != 0 else 0.0

        if abs(price_change) < 0.1:
            vol_score = 0.0
        elif price_curr > price_prev:
            vol_score = z_volume_raw
        else:
            vol_score = -z_volume_raw

        # ----- 3. 波動率壓縮/擴張（需 >=120 根 K 線才會生效） -----
        raw_series, ratio_series = QuantEngine.compression_series(high, low)
        vol_series = raw_series.iloc[MIN_BARS_FOR_SCORE:].reset_index(drop=True)
        # The factor is only computable once there is a full z-score window on
        # top of the warm-up; below that its weight is silently redistributed.
        volatility_computable = len(vol_series) >= 60
        if volatility_computable:
            z_volatility_series = QuantEngine.calculate_zscore(vol_series, 60)
            z_volatility = QuantEngine._to_float(z_volatility_series.iloc[-1])
        else:
            z_volatility = 0.0

        if pd.isna(z_volatility) or not np.isfinite(z_volatility):
            z_volatility = 0.0

        compression_ratio = QuantEngine._to_float(ratio_series.iloc[-1])
        if pd.isna(compression_ratio) or not np.isfinite(compression_ratio):
            compression_ratio = 1.0

        # ----- 4. 相對強弱（權重 20%） -----
        ma20 = close.rolling(20).mean()
        atr_series = (high.rolling(14).max() - low.rolling(14).min())
        relative_raw = (close - ma20) / (atr_series + 1e-6)
        z_rs_series = QuantEngine.calculate_zscore(relative_raw, 60)
        z_rs = QuantEngine._to_float(z_rs_series.iloc[-1])
        if pd.isna(z_rs) or not np.isfinite(z_rs):
            z_rs = 0.0
        z_rs = max(-3.0, min(3.0, z_rs))

        # ----- 加權總分（權重來自 config.zscore.weights） -----
        final_score = (
            z_momentum * resolved["momentum"]
            + vol_score * resolved["volume"]
            + z_volatility * resolved["volatility"]
            + z_rs * resolved["relative_strength"]
        )
        final_score = max(-3.0, min(3.0, final_score))

        # ----- 5日升幅懲罰 -----
        if len(df) >= 6:
            price_5d_ago = QuantEngine._to_float(close.iloc[-6])
            gain_5d = (price_curr / price_5d_ago - 1) * 100 if price_5d_ago != 0 else 0.0
            if gain_5d > 15.0 and final_score > 1.8:
                final_score = min(final_score, 1.4)

        rsi = QuantEngine.calculate_rsi(df)

        active = []
        if z_momentum != 0.0:
            active.append("momentum")
        if vol_score != 0.0:
            active.append("volume")
        if z_volatility != 0.0:
            active.append("volatility")
        if z_rs != 0.0:
            active.append("relative_strength")

        return {
            "z_score": round(float(final_score), 2),
            "z_momentum": round(float(z_momentum), 2),
            "z_volume": round(float(vol_score), 2),
            "z_volatility": round(float(z_volatility), 2),
            "z_rs": round(float(z_rs), 2),
            "compression_ratio": round(float(compression_ratio), 2),
            "rsi": round(float(rsi), 1),
            "weights": resolved,
            "factors_active": active,
            "volatility_factor_active": volatility_computable,
        }

    @staticmethod
    def get_rsi_alert(rsi, z_score):
        if pd.isna(rsi):
            return "neutral", None
        if rsi > 80 and z_score > 1.8:
            return "overheat", "目標 2 縮減為 2R"
        elif rsi < 20:
            return "oversold", "超賣警報，等待確認"
        else:
            return "neutral", None