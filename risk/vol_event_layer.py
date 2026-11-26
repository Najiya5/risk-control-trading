#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""二级风控层：波动率为主 + 事件为辅

结构：
    标的系数 = 1 - (w_vol × 波动率压力 + w_event × 事件压力)

其中：
    w_vol   = 0.9   （波动率主导）
    w_event = 0.1   （事件只做微调）

波动率压力：用 ATRP 指标（你的 MQL4 逻辑）
    ATRP > MA(20) × factor  → 压力 = (ATRP - 阈值) / 阈值，上限 1
    否则压力 = 0

事件压力：多模型判断 severity 归一化到 0-1

系数下限 0（归零），上限 1（只减不加）。
"""

import numpy as np
import pandas as pd


# ────────────────────────────────────────────────
# ATRP 指标（MQL4 版移植）
# ────────────────────────────────────────────────

def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder ATR，和 MT4 的 iATR 一致（用 SMA 播种，再接递推）"""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low,
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    # MT4 的 iATR：前 period 根用简单平均播种，之后接 Wilder 平滑
    atr_vals = np.full(len(tr), np.nan)
    tr_np = tr.to_numpy(dtype=float)
    if len(tr_np) < period:
        return pd.Series(atr_vals, index=tr.index)

    first = np.nanmean(tr_np[:period])
    atr_vals[period - 1] = first
    for i in range(period, len(tr_np)):
        atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr_np[i]) / period
    return pd.Series(atr_vals, index=tr.index)


def atrp(df: pd.DataFrame, period1: int = 3, period2: int = 10,
         weight1: float = 50.0, weight2: float = 50.0) -> pd.DataFrame:
    """
    ATRP 指标（对应你的 ATRP.mq4）：
      加权 ATR = (ATR(p1)*w1 + ATR(p2)*w2) / (w1+w2)
      ATRP%   = 加权 ATR / close × 100
      阈值线  = MA(ATRP%, 20) × factor
    """
    a1 = atr(df, period1)
    a2 = atr(df, period2)
    wsum = weight1 + weight2
    weighted = (a1 * (weight1 / wsum)) + (a2 * (weight2 / wsum))
    atrp_val = weighted / df["close"] * 100.0

    out = df.copy()
    out["atr"] = weighted
    out["atrp"] = atrp_val
    out["atrp_ma"] = atrp_val.rolling(20, min_periods=20).mean()
    return out


def vol_pressure(ind: pd.DataFrame, factor: float = 1.4,
                 exclude_ratio: float = 0.5) -> pd.Series:
    """
    波动率压力（0-1）：
      ATRP > MA × factor  →  (ATRP/阈值 - 1) / exclude_ratio，夹到 [0,1]

    factor 不可低于 1.4（低于会严重耽误策略运行——这是硬约束）
    exclude_ratio：超过阈值多少倍算"满压力"，默认 0.5 即超出 50% 计满。
    """
    factor = max(factor, 1.4)          # 硬约束：不低于 1.4
    threshold = ind["atrp_ma"] * factor
    excess = (ind["atrp"] / threshold) - 1.0
    pressure = (excess / exclude_ratio).clip(lower=0.0, upper=1.0)
    return pressure.fillna(0.0)


# ────────────────────────────────────────────────
# 事件压力
# ────────────────────────────────────────────────

def event_pressure(severity: float, dispersion: float = 0.0,
                   blocked: bool = False) -> float:
    """
    事件压力（0-1）：
      severity 0-1 直接用
      分歧大或多模型方向不一致 → 直接给 1（等同于归零）
    """
    if blocked:
        return 1.0
    return float(np.clip(severity, 0.0, 1.0))


# ────────────────────────────────────────────────
# 合成
# ────────────────────────────────────────────────

def target_coeff(vol_press: float, evt_press: float,
                 w_vol: float = 0.9, w_event: float = 0.1,
                 daily_coeff: float = 1.0) -> dict:
    """
    标的系数 = 1 - (w_vol × 波动压力 + w_event × 事件压力)，再乘当日总系数

    返回明细，方便审计。
    """
    raw_pressure = w_vol * vol_press + w_event * evt_press
    base = 1.0 - raw_pressure
    final = base * daily_coeff
    # 只减不加
    final = float(np.clip(final, 0.0, 1.0))

    return {
        "vol_pressure": round(float(vol_press), 4),
        "event_pressure": round(float(evt_press), 4),
        "w_vol": w_vol,
        "w_event": w_event,
        "pressure": round(float(raw_pressure), 4),
        "base_coeff": round(float(base), 4),
        "daily_coeff": round(float(daily_coeff), 4),
        "final_coeff": round(final, 4),
    }


def combine_weights(w_vol: float, w_event: float) -> tuple:
    """权重归一化，保证和不超过 1"""
    s = w_vol + w_event
    if s <= 0:
        return 1.0, 0.0
    return w_vol / s, w_event / s
