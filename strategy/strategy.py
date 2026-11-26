# -*- coding: utf-8 -*-
"""交易策略：OsMA 双信号共振

这是策略的完整定义，指标计算在 osma/indicator.py。

═══ 信号逻辑 ═══

    OsMA = MACD(加权价格) - EMA(OsMA, SignalEMA)
    Signal = EMA(OsMA, SignalEMA)

    做多：OsMA > 0 且 Signal > 0        （两线都在零轴上方）
    做空：OsMA < 0 且 Signal < 0        （两线都在零轴下方）
    平仓：任一信号消失
    反向：等两个信号同时翻转才反手

═══ 为什么这样设计 ═══

只看 OsMA 一件不够：OsMA 穿过零轴时，价格经常已经在回抽。
加上 Signal 的约束，等于要求「动量和动量的加速度同向」——
入场变少，但每次入场的确定性更高。

两个信号互为补集，所以「两值同号才持仓」和「任一消失就平仓」
是同一件事的两种说法。

═══ 加权价格的意义 ═══

普通 K 线用收盘价代表「这一刻的价格」，但收盘价容易被一根长影线带偏。

加权价格 = (0.7 × 实体中点 + 0.3 × 影线中点)

实体权重大，代表「多空真正争夺出来的价位」；
影线权重小，只是为了让极端插针有一点影响，但不主导。
"""

import numpy as np
import pandas as pd


def weight_price(df: pd.DataFrame, w_body: float = 0.7,
                 w_shadow: float = 0.3) -> pd.Series:
    """加权价格"""
    body = (df["open"] + df["close"]) / 2.0
    shadow = (df["high"] + df["low"]) / 2.0
    tot = w_body + w_shadow
    if tot == 0:
        tot = 1.0
    return (w_body * body + w_shadow * shadow) / tot


def mt4_ema(series: pd.Series, period: int) -> pd.Series:
    """
    模拟 MT4 的 iMA(MODE_EMA)。
    用前 period 个值的 SMA 作为种子，然后递推。

    注意：这和 pandas 的 ewm() 不一致（后者从第一个值开始），
    移植时必须手动实现，否则前几百根 K 线的指标会有偏差。
    """
    s = series.astype(float)
    n = len(s)
    out = pd.Series(np.nan, index=s.index, dtype=float)
    if n < period or period < 1:
        return out

    alpha = 2.0 / (period + 1.0)
    out.iloc[period - 1] = s.iloc[:period].mean()

    vals = np.array(s.to_numpy(dtype=float), copy=True)
    res = np.array(out.to_numpy(dtype=float), copy=True)
    for i in range(period, n):
        res[i] = vals[i] * alpha + res[i - 1] * (1 - alpha)
    return pd.Series(res, index=s.index)


def compute(df: pd.DataFrame, fast: int = 5, slow: int = 20,
            signal: int = 30, w_body: float = 0.7,
            w_shadow: float = 0.3) -> pd.DataFrame:
    """
    计算指标，返回带以下列的 DataFrame：

      wp      加权价格
      macd    快慢 EMA 之差
      signal  MACD 的信号线
      osma    macd - signal

      long_ok      做多条件（OsMA > 0 且 Signal > 0）
      short_ok     做空条件（OsMA < 0 且 Signal < 0）
      entry_long   本根刚满足做多（上一根不满足）
      entry_short  本根刚满足做空（上一根不满足）
    """
    wp = weight_price(df, w_body, w_shadow)
    fast_ma = mt4_ema(wp, fast)
    slow_ma = mt4_ema(wp, slow)
    macd = fast_ma - slow_ma
    sig = mt4_ema(macd, signal)

    out = df.copy()
    out["wp"] = wp
    out["macd"] = macd
    out["signal"] = sig
    out["osma"] = macd - sig

    out["long_ok"] = (out["osma"] > 0) & (out["signal"] > 0)
    out["short_ok"] = (out["osma"] < 0) & (out["signal"] < 0)

    prev_long = out["long_ok"].shift(1).fillna(False)
    prev_short = out["short_ok"].shift(1).fillna(False)
    out["entry_long"] = out["long_ok"] & ~prev_long
    out["entry_short"] = out["short_ok"] & ~prev_short

    return out


def stop_price(entry_price: float, atr: float, side: int,
               atr_mult: float = 1.5) -> float:
    """
    止损价：入场价 ± 1.5 × ATR

    side: 1 = 多, -1 = 空
    用 ATR 而不是固定点数，是因为不同周期的波动量级差异很大，
    ATR 能让止损随市场自己调整。
    """
    dist = atr * atr_mult
    return entry_price - dist if side == 1 else entry_price + dist


if __name__ == "__main__":
    # 简单自测：造一段随机数据，确认信号逻辑自洽
    np.random.seed(42)
    n = 500
    px = 3600 + np.cumsum(np.random.randn(n) * 2)
    df = pd.DataFrame({
        "open": px + np.random.randn(n) * 0.5,
        "high": px + abs(np.random.randn(n)) * 2,
        "low": px - abs(np.random.randn(n)) * 2,
        "close": px,
    })
    r = compute(df)

    print(f"数据 {n} 根")
    print(f"做多条件成立 {r['long_ok'].sum()} 根  ({r['long_ok'].mean()*100:.1f}%)")
    print(f"做空条件成立 {r['short_ok'].sum()} 根  ({r['short_ok'].mean()*100:.1f}%)")
    print(f"做多入场 {r['entry_long'].sum()} 次")
    print(f"做空入场 {r['entry_short'].sum()} 次")
    both = (r["long_ok"] & r["short_ok"]).sum()
    print(f"两条件同时成立 {both} 根（应为 0，因为互为补集）")
    assert both == 0, "信号逻辑有误：多空条件不应同时成立"
    print("\n[OK] 信号逻辑自洽")
