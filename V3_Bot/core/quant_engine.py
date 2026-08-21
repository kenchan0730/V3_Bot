# core/quant_engine.py - 最終穩定版
import pandas as pd
import numpy as np


class QuantEngine:
    
    @staticmethod
    def _get_columns(df):
        """自動偵測欄位名稱大小寫"""
        close_col = 'close' if 'close' in df.columns else 'Close'
        high_col = 'high' if 'high' in df.columns else 'High'
        low_col = 'low' if 'low' in df.columns else 'Low'
        volume_col = 'volume' if 'volume' in df.columns else 'Volume'
        return close_col, high_col, low_col, volume_col

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
    def dynamic_score(df):
        if len(df) < 60:
            return {
                "z_score": 0.0,
                "z_momentum": 0.0,
                "z_volume": 0.0,
                "z_volatility": 0.0,
                "z_rs": 0.0,
                "compression_ratio": 1.0,
                "rsi": 50.0
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

        # ----- 3. 波動率壓縮/擴張（權重 20%） -----
        compression_scores = []
        for i in range(60, len(df)):
            # 使用 .max() 和 .min() 後強制轉為 float
            high_slice = high.iloc[i-13:i+1]
            low_slice = low.iloc[i-13:i+1]
            atr_14 = float(high_slice.max()) - float(low_slice.min())
            
            high_slice_50 = high.iloc[i-49:i+1]
            low_slice_50 = low.iloc[i-49:i+1]
            atr_50 = float(high_slice_50.max()) - float(low_slice_50.min())
            
            if atr_50 > 0:
                ratio = atr_14 / atr_50
            else:
                ratio = 1.0
            
            if ratio <= 0.85:
                raw = 1.5
            elif ratio >= 1.3:
                raw = -1.5
            else:
                raw = (1.3 - ratio) / (1.3 - 0.85) * 1.5 - 1.5
            compression_scores.append(raw)

        vol_series = pd.Series(compression_scores)
        if len(vol_series) >= 60:
            z_volatility_series = QuantEngine.calculate_zscore(vol_series, 60)
            z_volatility = QuantEngine._to_float(z_volatility_series.iloc[-1])
        else:
            z_volatility = 0.0

        if pd.isna(z_volatility) or not np.isfinite(z_volatility):
            z_volatility = 0.0

        # 當前壓縮比
        atr_14_curr = float(high.iloc[-13:].max()) - float(low.iloc[-13:].min())
        atr_50_curr = float(high.iloc[-49:].max()) - float(low.iloc[-49:].min())
        compression_ratio = atr_14_curr / atr_50_curr if atr_50_curr > 0 else 1.0

        # ----- 4. 相對強弱（權重 20%） -----
        ma20 = close.rolling(20).mean()
        atr_series = (high.rolling(14).max() - low.rolling(14).min())
        relative_raw = (close - ma20) / (atr_series + 1e-6)
        z_rs_series = QuantEngine.calculate_zscore(relative_raw, 60)
        z_rs = QuantEngine._to_float(z_rs_series.iloc[-1])
        if pd.isna(z_rs) or not np.isfinite(z_rs):
            z_rs = 0.0
        z_rs = max(-3.0, min(3.0, z_rs))

        # ----- 加權總分 -----
        final_score = z_momentum * 0.35 + vol_score * 0.25 + z_volatility * 0.20 + z_rs * 0.20
        final_score = max(-3.0, min(3.0, final_score))

        # ----- 5日升幅懲罰 -----
        if len(df) >= 6:
            price_5d_ago = QuantEngine._to_float(close.iloc[-6])
            gain_5d = (price_curr / price_5d_ago - 1) * 100 if price_5d_ago != 0 else 0.0
            if gain_5d > 15.0 and final_score > 1.8:
                final_score = min(final_score, 1.4)

        rsi = QuantEngine.calculate_rsi(df)

        return {
            "z_score": round(float(final_score), 2),
            "z_momentum": round(float(z_momentum), 2),
            "z_volume": round(float(vol_score), 2),
            "z_volatility": round(float(z_volatility), 2),
            "z_rs": round(float(z_rs), 2),
            "compression_ratio": round(float(compression_ratio), 2),
            "rsi": round(float(rsi), 1)
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