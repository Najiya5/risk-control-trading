# -*- coding: utf-8 -*-
"""修正休盘平仓判断：按「休市前最后一根 K 线」触发

原来的问题：
  H1 数据只有整点，21:50-22:00 这个 10 分钟窗口里没有任何 K 线，
  所以按分钟判断永远触发不了。

正确做法：
  找出「下一根 K 线的时间跳变超过正常间隔」的那根 —— 它就是休市前最后一根。
  在这根的收盘价平仓。

实现：对每根 K 线 i，看 i+1 的时间差。
  如果 t[i+1] - t[i] > 1.5 × 正常间隔 → 说明 i 之后休市了 → 在 i 平仓。
"""

import pandas as pd
import numpy as np


def build_flat_mask(idx: pd.DatetimeIndex, tf_minutes: int = 60,
                    gap_factor: float = 1.5) -> np.ndarray:
    """
    返回布尔数组：True 表示「这根 K 线之后会休市，应该在这根平仓」

    tf_minutes: 该周期的分钟数（H1 = 60, M5 = 5）
    gap_factor: 时间间隔超过 正常间隔 × 这个倍数，就认为是休市
    """
    n = len(idx)
    mask = np.zeros(n, dtype=bool)
    if n < 2:
        return mask

    ts = pd.DatetimeIndex(idx).to_numpy()
    diffs = np.diff(ts).astype("timedelta64[m]").astype(float)

    normal = tf_minutes
    threshold = normal * gap_factor

    # 最后一根之后也算（收盘）
    mask[-1] = True

    for i in range(n - 1):
        if diffs[i] > threshold:
            mask[i] = True

    return mask


def describe_gaps(idx: pd.DatetimeIndex, tf_minutes: int = 60, top: int = 8):
    """打印最常见的间隔，用来确认休市点在哪儿"""
    ts = pd.DatetimeIndex(idx).to_numpy()
    diffs = np.diff(ts).astype("timedelta64[m]").astype(float)

    # 统计
    vals, counts = np.unique(diffs, return_counts=True)
    order = np.argsort(-counts)
    print(f"  K 线间隔分布（共 {len(diffs)} 个间隔）:")
    for k in order[:top]:
        gap = int(vals[k])
        print(f"    {gap:>5} 分钟  {int(counts[k]):>6} 次")

    # 找出大间隔出现的时刻
    big = np.where(diffs > tf_minutes * 1.5)[0]
    if len(big):
        hours = pd.Series(pd.DatetimeIndex(idx)[big].hour).value_counts().sort_index()
        print(f"  大间隔出现在这些小时（取前一根的时间）:")
        for h, c in hours.items():
            print(f"    {h:02d}:00  {c} 次")
    return diffs


if __name__ == "__main__":
    import os
    DATA = r"C:\Users\26217\Documents\deepseek-harness\default-workspace\data\yahoo"
    for key in ["GOLD", "WTI"]:
        p = os.path.join(DATA, f"{key}_1h.csv")
        df = pd.read_csv(p, parse_dates=["time"]).set_index("time")
        print("=" * 60)
        print(f"  {key}")
        print("=" * 60)
        describe_gaps(df.index, 60)
        mask = build_flat_mask(df.index, 60)
        print(f"  标记为「休市前最后一根」: {mask.sum()} / {len(mask)}  ({mask.mean()*100:.1f}%)")
        print()
