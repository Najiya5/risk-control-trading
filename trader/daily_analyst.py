# -*- coding: utf-8 -*-
"""总分析师：日线百分位 → 仓位系数

规则（用户定义）：
  百分位 < 90%       → 系数 1.0（不干预）
  90% ≤ 百分位 < 98% → 系数 0.5（仓位减半）
  百分位 ≥ 98%       → 系数 0.0（暂停开仓）

百分位计算：
  用日线数据算两个指标的历史分位，合成一个 0~100 的综合百分位：
    - 已实现波动率（20日）
    - ATR 百分比（14日）
  两者分别算分位后取平均。
"""

import os
import sys

import numpy as np
import pandas as pd

ROOT = r"C:\Users\26217\Documents\deepseek-harness\default-workspace"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "risk"))


def realized_vol(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """已实现波动率：对数收益的滚动标准差，年化"""
    close = df["close"].astype(float)
    ret = np.log(close / close.shift(1))
    return ret.rolling(window).std() * np.sqrt(252)


def atr_pct(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """ATR 百分比：ATR / 收盘价"""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / window, adjust=False).mean()
    return atr / close


def rolling_percentile(series: pd.Series, lookback: int = 250) -> pd.Series:
    """
    point-in-time 滚动百分位：只用当天及以前的数据。
    返回 0~100。
    """
    out = pd.Series(index=series.index, dtype=float)
    vals = series.to_numpy()
    n = len(vals)
    for i in range(n):
        if i < lookback:
            continue
        window = vals[i - lookback + 1: i + 1]
        window = window[~np.isnan(window)]
        if len(window) < lookback * 0.5 or np.isnan(vals[i]):
            continue
        out.iloc[i] = (window <= vals[i]).mean() * 100.0
    return out


def compute_daily_state(d1: pd.DataFrame,
                        lookback: int = 250,
                        vol_window: int = 20,
                        atr_window: int = 14) -> pd.DataFrame:
    """
    输入日线 OHLC，输出每天的百分位和系数。
    返回 DataFrame：vol_pct, atr_pct, combined_pct, coeff
    """
    rv = realized_vol(d1, vol_window)
    ap = atr_pct(d1, atr_window)

    rv_pct = rolling_percentile(rv, lookback)
    ap_pct = rolling_percentile(ap, lookback)

    combined = (rv_pct + ap_pct) / 2.0

    out = pd.DataFrame({
        "rv": rv, "atr_pct": ap,
        "rv_pct": rv_pct, "atr_pct_pct": ap_pct,
        "combined_pct": combined,
    })
    out["coeff"] = out["combined_pct"].apply(pct_to_coeff)
    return out


def pct_to_coeff(pct: float) -> float:
    """百分位 → 仓位系数"""
    if pd.isna(pct):
        return 1.0
    if pct >= 98.0:
        return 0.0        # 暂停开仓
    if pct >= 90.0:
        return 0.5        # 仓位减半
    return 1.0


def get_prev_day_coeff(d1: pd.DataFrame, cfg: dict) -> dict:
    """
    取「昨天」的系数（point-in-time，避免未来函数）。

    返回：
      {ok, coeff, pct, rv_pct, atr_pct, date, reason}
    """
    da = cfg.get("daily_analyst", {})
    lookback = da.get("lookback_days", 250)
    vol_w = da.get("vol_window", 20)
    atr_w = da.get("atr_window", 14)

    state = compute_daily_state(d1, lookback, vol_w, atr_w)
    valid = state.dropna(subset=["combined_pct"])
    if len(valid) < 2:
        return dict(ok=False, coeff=1.0, reason="历史数据不足，按 1.0 处理")

    # 昨天 = 倒数第二行（最后一行是今天，还没走完）
    prev = valid.iloc[-2]
    pct = float(prev["combined_pct"])
    coeff = pct_to_coeff(pct)

    if pct >= 98.0:
        reason = f"百分位 {pct:.1f}% ≥ 98% → 暂停开仓"
    elif pct >= 90.0:
        reason = f"百分位 {pct:.1f}% 在 90~98% → 仓位减半"
    else:
        reason = f"百分位 {pct:.1f}% < 90% → 正常"

    return dict(ok=True, coeff=coeff, pct=pct,
                rv_pct=float(prev["rv_pct"]),
                atr_pct=float(prev["atr_pct_pct"]),
                date=str(valid.index[-2]),
                reason=reason)
