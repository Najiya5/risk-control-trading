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
                        atr_window: int = 14,
                        vix: pd.Series = None) -> pd.DataFrame:
    """
    输入日线 OHLC（可选 VIX），输出每天的百分位和系数。

    三路独立信号（各自算自己的历史百分位）：
      已实现波动率（20日）  ← 黄金自己
      ATR%（14日）         ← 黄金自己
      VIX（日线）          ← 市场恐慌/流动性前瞻

    ★ 取最大值：任何一路报警就算报警
    ★ 阈值：≥98% 暂停，90-98% 减半，<90% 正常

    返回 DataFrame：rv_pct / atr_pct_pct / vix_pct / max_pct / driving / coeff
    """
    rv = realized_vol(d1, vol_window)
    ap = atr_pct(d1, atr_window)

    rv_pct = rolling_percentile(rv, lookback)
    ap_pct = rolling_percentile(ap, lookback)

    cols = {"rv": rv, "atr_pct": ap,
            "rv_pct": rv_pct, "atr_pct_pct": ap_pct}

    if vix is not None and len(vix) > 0:
        # VIX 对齐到黄金的日线时间轴（用 ffill，保证没有未来数据）
        v = vix.reindex(d1.index.union(vix.index)).ffill().reindex(d1.index)
        cols["vix_pct"] = rolling_percentile(v.astype(float), lookback)
    else:
        cols["vix_pct"] = pd.Series(float("nan"), index=d1.index)

    out = pd.DataFrame(cols)

    # 取三路最大
    pct_cols = ["rv_pct", "atr_pct_pct", "vix_pct"]
    mats = out[pct_cols]
    out["max_pct"] = mats.max(axis=1, skipna=True)

    # 记录是哪一路驱动
    def _which(row):
        best, name = float("-inf"), ""
        for c in pct_cols:
            v = row[c]
            if pd.notna(v) and v > best:
                best, name = v, c
        return name

    out["driving"] = mats.apply(_which, axis=1)
    out["coeff"] = out["max_pct"].apply(pct_to_coeff)

    # 兼容旧字段名
    out["combined_pct"] = out["max_pct"]
    return out


def load_vix_daily(cfg: dict, n: int = 2000):
    """
    从 MT5 拉 VIX 日线（收盘价）。

    失败返回 None —— 总分析师退回两路合成，不影响主流程。
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None

    symbol = cfg.get("daily_analyst", {}).get("vix_symbol", "VIX")
    mcfg = cfg.get("broker", {}).get("mt5", {})

    try:
        kwargs = {}
        if mcfg.get("path"):
            kwargs["path"] = mcfg["path"]
        # 用全局单例（如果已经初始化过）
        try:
            from mt5_broker import MT5Client
            client = MT5Client.shared(
                login=mcfg.get("login"), password=mcfg.get("password"),
                server=mcfg.get("server"), path=mcfg.get("path") or None)
            ready = client._ready
        except Exception:
            ready = False

        if not ready:
            if not mt5.initialize(**kwargs):
                return None

        if not mt5.symbol_select(symbol, True):
            return None

        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, n)
        if rates is None or len(rates) == 0:
            return None

        ts = pd.to_datetime([r[0] for r in rates], unit="s")
        close = [float(r[4]) for r in rates]
        s = pd.Series(close, index=ts).sort_index()
        return s
    except Exception:
        return None


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

    vix = None
    use_vix = da.get("use_vix", True)
    if use_vix:
        vix = load_vix_daily(cfg)
        if vix is None or len(vix) < 100:
            vix = None

    state = compute_daily_state(d1, lookback, vol_w, atr_w, vix=vix)
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

    vix_pct = float(prev["vix_pct"]) if "vix_pct" in prev and not pd.isna(prev["vix_pct"]) else None
    driving = str(prev.get("driving", ""))
    label = {"rv_pct": "已实现波动率", "atr_pct_pct": "ATR%", "vix_pct": "VIX"}.get(driving, driving)
    if label:
        reason += f"（由 {label} {pct:.1f}% 驱动）"
    return dict(ok=True, coeff=coeff, pct=pct,
                rv_pct=float(prev["rv_pct"]),
                atr_pct=float(prev["atr_pct_pct"]),
                vix_pct=vix_pct,
                vix_used=vix is not None,
                driving=driving,
                date=str(valid.index[-2]),
                reason=reason)
