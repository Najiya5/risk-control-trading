#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OsMA 指标（MQL4 版 osma1.mq4 的 Python 移植）

原始 MQL4 逻辑：
  1. 加权价格 = (WeightBody * (O+C)/2 + WeightShadow * (H+L)/2) / (WeightBody + WeightShadow)
  2. MACD 线  = EMA(加权价格, FastEMA) - EMA(加权价格, SlowEMA)
  3. 信号线   = EMA(MACD 线, SignalEMA)
  4. OsMA    = MACD 线 - 信号线

与 MQL4 的 iMA(..., MODE_EMA) 对齐：
  MT4 的 iMA 基于 SMA 播种的 EMA，这里用 pandas ewm(adjust=False, min_periods=period)
  并在前 period-1 根用 SMA 作为起点，尽量贴近 MT4 行为。
"""

import numpy as np
import pandas as pd


def _mt4_ema(series: pd.Series, period: int) -> pd.Series:
    """模拟 MT4 的 iMA(MODE_EMA)：用前 period 个值的 SMA 作为种子。"""
    s = series.astype(float)
    n = len(s)
    out = pd.Series(np.nan, index=s.index, dtype=float)
    if n < period or period < 1:
        return out

    alpha = 2.0 / (period + 1.0)
    # 种子：前 period 个有效值的均值
    seed = s.iloc[:period].mean()
    out.iloc[period - 1] = seed

    # 之后按递推（pandas 3.x 的 to_numpy 可能返回只读视图，这里显式复制）
    values = np.array(s.to_numpy(dtype=float), copy=True)
    res = np.array(out.to_numpy(dtype=float), copy=True)
    for i in range(period, n):
        res[i] = values[i] * alpha + res[i - 1] * (1 - alpha)
    return pd.Series(res, index=s.index)


def weighted_price(df: pd.DataFrame, weight_body: float = 0.7,
                   weight_shadow: float = 0.3) -> pd.Series:
    """加权价格：实体中点与影线中点的加权平均。"""
    body_mid = (df["open"] + df["close"]) / 2.0
    shadow_mid = (df["high"] + df["low"]) / 2.0
    total = weight_body + weight_shadow
    if total == 0:
        total = 1.0
    return (weight_body * body_mid + weight_shadow * shadow_mid) / total


def osma(df: pd.DataFrame, fast: int = 5, slow: int = 20, signal: int = 30,
         weight_body: float = 0.7, weight_shadow: float = 0.3) -> pd.DataFrame:
    """返回带 wp / macd / signal / osma 列的 DataFrame。"""
    wp = weighted_price(df, weight_body, weight_shadow)
    fast_ma = _mt4_ema(wp, fast)
    slow_ma = _mt4_ema(wp, slow)
    macd = fast_ma - slow_ma
    sig = _mt4_ema(macd, signal)
    out = df.copy()
    out["wp"] = wp
    out["macd"] = macd
    out["signal"] = sig
    out["osma"] = macd - sig
    return out
