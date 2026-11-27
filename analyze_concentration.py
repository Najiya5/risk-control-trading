# -*- coding: utf-8 -*-
"""收益集中度分析：去掉最赚的 N 笔，还剩多少？

回答一个问题：PF 1.3 是真本事，还是几笔运气？
"""

import os
import sys

import numpy as np
import pandas as pd

ROOT = r"C:\Users\26217\Documents\deepseek-harness\default-workspace"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "osma"))
sys.path.insert(0, os.path.join(ROOT, "risk"))

from indicator import osma                     # noqa: E402
from vol_event_layer import atrp                # noqa: E402


def load(sym, tf):
    p = os.path.join(ROOT, f"{sym}_{tf}_Tickmill-DemoUK.csv")
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, parse_dates=["time"]).set_index("time").sort_index()


def backtest_trades(df, spread=0.08, mult=100.0, lots=1.0, factor=1.4,
                    equity0=1_000_000.0, stop_atr=1.5,
                    use_breakeven=True, profit_bars=10, be_at_r=1.0):
    ind = atrp(df, 3, 10)
    ind = ind.join(osma(df, 5, 20, 30), how="inner", rsuffix="_o")
    ind = ind.dropna(subset=["atrp", "atrp_ma", "osma", "signal"])
    if len(ind) < 100:
        return None

    o = ind["osma"].to_numpy()
    s = ind["signal"].to_numpy()
    price = ind["close"].to_numpy()
    high = ind["high"].to_numpy()
    low = ind["low"].to_numpy()
    av = ind["atrp"].to_numpy()
    am = ind["atrp_ma"].to_numpy()
    atr_v = ind["atr"].to_numpy()
    idx = ind.index
    gate = av > am * factor

    cost = spread * mult

    pos = 0
    cur_lots = lots
    ep = 0.0
    ei = 0
    vol_cut = False
    equity = 0.0
    legs = []
    trades = []          # 完整交易（含减仓腿汇总）
    cur = []

    stop_price = 0.0
    be_armed = False
    profit_streak = 0
    max_favor = 0.0
    init_stop_dist = 0.0

    for i in range(len(ind)):
        p = price[i]
        stopped = False

        if pos == 1 and low[i] <= stop_price:
            pnl = (stop_price - ep) * cur_lots * mult - cost * cur_lots
            equity += pnl; legs.append(pnl); cur.append(pnl)
            trades.append(sum(cur)); cur = []; pos = 0; stopped = True
        elif pos == -1 and high[i] >= stop_price:
            pnl = (ep - stop_price) * cur_lots * mult - cost * cur_lots
            equity += pnl; legs.append(pnl); cur.append(pnl)
            trades.append(sum(cur)); cur = []; pos = 0; stopped = True

        if not stopped:
            if use_breakeven and pos != 0 and not be_armed:
                favor = (p - ep) if pos == 1 else (ep - p)
                profit_streak = profit_streak + 1 if favor > 0 else 0
                max_favor = max(max_favor, favor)
                if profit_streak >= profit_bars or max_favor >= init_stop_dist * be_at_r:
                    stop_price = ep
                    be_armed = True

            if pos != 0 and gate[i] and not vol_cut:
                cut = round(cur_lots * 0.5 / 0.01) * 0.01
                part = ((p - ep) if pos == 1 else (ep - p)) * cut * mult - cost * cut
                equity += part; legs.append(part); cur.append(part)
                cur_lots = round((cur_lots - cut) / 0.01) * 0.01
                vol_cut = True
                if cur_lots < 0.01:
                    trades.append(sum(cur)); cur = []; pos = 0

            if pos == 1 and not (o[i] > 0 and s[i] > 0):
                pnl = (p - ep) * cur_lots * mult - cost * cur_lots
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(sum(cur)); cur = []; pos = 0
            elif pos == -1 and not (o[i] < 0 and s[i] < 0):
                pnl = (ep - p) * cur_lots * mult - cost * cur_lots
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(sum(cur)); cur = []; pos = 0

            if pos == 0 and ((o[i] > 0 and s[i] > 0) or (o[i] < 0 and s[i] < 0)):
                if not gate[i]:
                    pos = 1 if (o[i] > 0 and s[i] > 0) else -1
                    ep = p; ei = i; cur_lots = lots; vol_cut = False; cur = []
                    init_stop_dist = atr_v[i] * stop_atr
                    stop_price = ep - init_stop_dist if pos == 1 else ep + init_stop_dist
                    be_armed = False; profit_streak = 0; max_favor = 0.0

    leg_arr = np.array(legs) if legs else np.array([0.0])
    return leg_arr, trades


def analyze(name, pnls):
    pnls = np.array(pnls)
    n = len(pnls)
    if n < 10:
        print(f"{name}: 样本太少")
        return

    w = pnls[pnls > 0]
    l = pnls[pnls < 0]
    total = pnls.sum()
    pf = w.sum() / -l.sum() if len(l) and l.sum() != 0 else np.inf

    # 按金额排序
    sorted_p = np.sort(pnls)[::-1]

    print(f"\n{'='*70}")
    print(f"  {name}    交易 {n} 笔    净盈亏 {total:+,.0f}    PF {pf:.2f}")
    print(f"{'='*70}")
    print(f"  盈利单 {len(w)} 笔，合计 {w.sum():+,.0f}")
    print(f"  亏损单 {len(l)} 笔，合计 {l.sum():+,.0f}")
    print()

    # 去掉最大的 N 笔后
    print(f"  {'去掉最赚的N笔':<16}{'净盈亏':>16}{'PF':>8}{'还剩%':>10}")
    print("  " + "-" * 52)
    for k in [0, 1, 3, 5, 10, 20]:
        if k >= n:
            break
        rest = sorted_p[k:]
        rw = rest[rest > 0]
        rl = rest[rest < 0]
        rtot = rest.sum()
        rpf = rw.sum() / -rl.sum() if len(rl) and rl.sum() != 0 else np.inf
        pct = rtot / total * 100 if total != 0 else 0
        print(f"  {('前 ' + str(k) + ' 笔' if k else '全部'):<16}"
              f"{rtot:>16,.0f}{rpf:>8.2f}{pct:>9.1f}%")

    # 收益集中度
    print()
    if total > 0:
        cum = np.cumsum(sorted_p)
        for pct in [0.01, 0.05, 0.10, 0.20]:
            k = max(1, int(n * pct))
            share = cum[k-1] / total * 100
            print(f"  前 {k:>3} 笔（{pct*100:>4.0f}%）贡献了总收益的 {share:>6.1f}%")

    # 最大单笔占比
    print()
    print(f"  最大单笔盈利: {sorted_p[0]:+,.0f}  占总盈亏 {sorted_p[0]/total*100:.1f}%" if total > 0
          else f"  最大单笔盈利: {sorted_p[0]:+,.0f}")
    print(f"  最大单笔亏损: {sorted_p[-1]:+,.0f}")


def main():
    print("=" * 70)
    print("  收益集中度分析：PF 1.3 是真本事还是运气？")
    print("=" * 70)

    for sym, tf, spread, mult, name in [
        ("XAUUSD", "H1", 0.08, 100.0, "黄金 H1"),
        ("XAUUSD", "H4", 0.08, 100.0, "黄金 H4"),
        ("XAUUSD", "M5", 0.08, 100.0, "黄金 M5"),
    ]:
        df = load(sym, tf)
        if df is None:
            continue
        r = backtest_trades(df, spread=spread, mult=mult)
        if r is None:
            continue
        leg_arr, trades = r
        analyze(name, trades)


if __name__ == "__main__":
    main()
