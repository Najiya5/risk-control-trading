# -*- coding: utf-8 -*-
"""多周期共振策略：M5 信号 + M15 Parabolic SAR 过滤

信号逻辑：
  执行周期 M5：OsMA > 0 且 Signal > 0  → 想做多
  过滤周期 M15：Parabolic SAR 点在价格下方（多头方向）
  两条同时满足 → 开多
  （做空对称）

SAR 参数：MT4 默认 Step=0.02, Maximum=0.2

对齐方式：
  每根 M5 K 线，取【它所属的 M15 K 线】的 SAR 方向
  （M5 时间落在某根 M15 的区间内，就沿用那根 M15 的 SAR 状态）

⚠ 没有使用未来数据：M15 的 SAR 只用已经收盘的 M15 计算。
"""

import os
import sys

import numpy as np
import pandas as pd

ROOT = r"C:\Users\26217\Documents\deepseek-harness\default-workspace"


def load(sym, tf):
    p = os.path.join(ROOT, f"{sym}_{tf}_Tickmill-DemoUK.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p, parse_dates=["time"]).set_index("time").sort_index()
    return df


def parabolic_sar(df, step=0.02, max_af=0.2):
    """
    计算 Parabolic SAR（MT4 标准算法）

    返回 Series，值 = SAR 点价格。
    方向判断：SAR < low → 多头；SAR > high → 空头
    """
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    n = len(high)
    if n < 2:
        return pd.Series(np.nan, index=df.index)

    sar = np.full(n, np.nan)

    # 初始方向：用前两根判断
    # 经典实现从第二根开始
    is_long = high[1] >= high[0]
    af = step

    if is_long:
        ep = high[1]          # 极值
        sar[1] = low[0]
    else:
        ep = low[1]
        sar[1] = high[0]

    for i in range(2, n):
        prev_sar = sar[i - 1]

        # 先按原方向递推
        s = prev_sar + af * (ep - prev_sar)

        if is_long:
            # 多头：SAR 不能高于前两根的最低价
            s = min(s, low[i - 1], low[i - 2])
            # 检查是否被击穿
            if low[i] < s:
                # 翻转成空头
                is_long = False
                s = ep                 # 从旧极值开始
                ep = low[i]
                af = step
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + step, max_af)
        else:
            # 空头：SAR 不能低于前两根的最高价
            s = max(s, high[i - 1], high[i - 2])
            if high[i] > s:
                is_long = True
                s = ep
                ep = high[i]
                af = step
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + step, max_af)

        sar[i] = s

    return pd.Series(sar, index=df.index)


def sar_direction(df15, step=0.02, max_af=0.2):
    """
    计算 M15 的 SAR 方向序列。
    返回 Series[int]：1 = 多头（SAR 在价格下方），-1 = 空头，0 = 未知
    """
    sar = parabolic_sar(df15, step, max_af)
    hl2 = (df15["high"] + df15["low"]) / 2.0
    direction = pd.Series(0, index=df15.index, dtype=int)
    direction[sar < hl2] = 1
    direction[sar > hl2] = -1
    direction[sar.isna()] = 0
    return direction


def align_direction(dir15: pd.Series, index5: pd.DatetimeIndex) -> np.ndarray:
    """
    把 M15 的方向对齐到 M5 时间轴。

    规则：M5 时间 t 对应「最近一根已收盘的 M15」。
      M15 的一根从 10:00 到 10:15，在 10:15 收盘。
      所以 M5 的 10:00 / 10:05 / 10:10 三根，应该用【上一根 M15（09:45-10:00）】的方向。

    实现：把 M15 的 index 往后推 15 分钟（表示"这根 M15 的收盘时刻"），
          然后用 ffill 对齐到 M5 时间轴。
    """
    # 往前推：M15 索引代表"开盘时刻"，收盘时刻 = +15min
    close_time = dir15.index + pd.Timedelta(minutes=15)
    s = pd.Series(dir15.to_numpy(), index=close_time)
    # 对齐：对每个 M5 时刻，取 <= 它的最近一个 M15 收盘
    aligned = s.reindex(s.index.union(index5)).ffill().reindex(index5)
    return aligned.fillna(0).astype(int).to_numpy()


if __name__ == "__main__":
    # 自测
    for sym in ["XAUUSD", "DE40", "US500"]:
        df5 = load(sym, "M5")
        df15 = load(sym, "M15")
        if df5 is None or df15 is None:
            print(f"{sym}: 缺数据")
            continue
        d15 = sar_direction(df15)
        al = align_direction(d15, df5.index)
        print(f"{sym}:")
        print(f"  M5 {len(df5)} 根, M15 {len(df15)} 根")
        print(f"  M15 方向分布: 多 {int((d15==1).sum())}, 空 {int((d15==-1).sum())}, 未知 {int((d15==0).sum())}")
        print(f"  对齐到 M5 后: 多 {(al==1).sum()}, 空 {(al==-1).sum()}, 未知 {(al==0).sum()}")
