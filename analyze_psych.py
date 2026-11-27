# -*- coding: utf-8 -*-
"""心理承受力分析：连亏、回撤持续时间

回答：这套策略实盘时，人扛得住吗？
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


def backtest(df, spread=0.08, mult=100.0, lots=1.0, factor=1.4,
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
    curve = np.zeros(len(ind))
    legs = []
    trades = []          # (exit_time, pnl)
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
            trades.append((idx[i], sum(cur))); cur = []; pos = 0; stopped = True
        elif pos == -1 and high[i] >= stop_price:
            pnl = (ep - stop_price) * cur_lots * mult - cost * cur_lots
            equity += pnl; legs.append(pnl); cur.append(pnl)
            trades.append((idx[i], sum(cur))); cur = []; pos = 0; stopped = True

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
                    trades.append((idx[i], sum(cur))); cur = []; pos = 0

            if pos == 1 and not (o[i] > 0 and s[i] > 0):
                pnl = (p - ep) * cur_lots * mult - cost * cur_lots
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append((idx[i], sum(cur))); cur = []; pos = 0
            elif pos == -1 and not (o[i] < 0 and s[i] < 0):
                pnl = (ep - p) * cur_lots * mult - cost * cur_lots
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append((idx[i], sum(cur))); cur = []; pos = 0

            if pos == 0 and ((o[i] > 0 and s[i] > 0) or (o[i] < 0 and s[i] < 0)):
                if not gate[i]:
                    pos = 1 if (o[i] > 0 and s[i] > 0) else -1
                    ep = p; ei = i; cur_lots = lots; vol_cut = False; cur = []
                    init_stop_dist = atr_v[i] * stop_atr
                    stop_price = ep - init_stop_dist if pos == 1 else ep + init_stop_dist
                    be_armed = False; profit_streak = 0; max_favor = 0.0

        unreal = 0.0
        if pos == 1:
            unreal = (p - ep) * cur_lots * mult
        elif pos == -1:
            unreal = (ep - p) * cur_lots * mult
        curve[i] = equity + unreal

    return pd.Series(curve, index=idx) / equity0 * 100, trades, equity0


def analyze(name, eq, trades, equity0):
    pnls = np.array([t[1] for t in trades])
    n = len(pnls)
    if n < 10:
        print(f"{name}: 样本太少")
        return

    print(f"\n{'='*72}")
    print(f"  {name}   交易 {n} 笔   {eq.index[0]:%Y-%m-%d} → {eq.index[-1]:%Y-%m-%d}")
    print(f"{'='*72}")

    # ═══ 1. 最长连亏 ═══
    streaks = []
    cur = 0
    for p in pnls:
        if p < 0:
            cur += 1
        else:
            if cur:
                streaks.append(cur)
            cur = 0
    if cur:
        streaks.append(cur)

    print(f"  连亏分析:")
    print(f"    最长连亏 {max(streaks) if streaks else 0} 笔")
    if streaks:
        s = np.array(streaks)
        print(f"    连亏 3 笔以上: {(s>=3).sum()} 次")
        print(f"    连亏 5 笔以上: {(s>=5).sum()} 次")
        print(f"    连亏 8 笔以上: {(s>=8).sum()} 次")
        print(f"    平均连亏长度: {s.mean():.1f} 笔")

    # ═══ 2. 回撤持续时间 ═══
    peak = eq.cummax()
    underwater = eq < peak

    # 找每一段水下区间
    durations = []
    start = None
    for i, uw in enumerate(underwater):
        if uw and start is None:
            start = i
        elif not uw and start is not None:
            durations.append((start, i))
            start = None
    if start is not None:
        durations.append((start, len(eq) - 1))

    if durations:
        d_days = [(eq.index[b] - eq.index[a]).days for a, b in durations]
        d_days.sort(reverse=True)
        print(f"\n  回撤持续时间（水下）:")
        print(f"    最长 {d_days[0]} 天")
        print(f"    前5长: {d_days[:5]}")
        print(f"    中位数: {np.median(d_days):.0f} 天")
        print(f"    超过 30 天的: {sum(1 for d in d_days if d > 30)} 次")
        print(f"    超过 60 天的: {sum(1 for d in d_days if d > 60)} 次")

        # 回撤幅度分布
        dd_series = eq - peak
        print(f"\n  回撤幅度:")
        print(f"    最大 {dd_series.min():.2f}%")
        print(f"    超过 -2% 的时段占比: {(dd_series < -2).mean()*100:.1f}%")
        print(f"    超过 -3% 的时段占比: {(dd_series < -3).mean()*100:.1f}%")

    # ═══ 3. 月度表现 ═══
    monthly = eq.resample("ME").last().dropna()
    if len(monthly) > 2:
        mret = monthly.diff().dropna()
        neg = (mret < 0).sum()
        print(f"\n  月度表现（{len(mret)} 个完整月）:")
        print(f"    盈利月 {len(mret) - neg}    亏损月 {neg}    "
              f"胜率 {((len(mret)-neg)/len(mret)*100):.0f}%")
        print(f"    最好 {mret.max():+.2f}%    最差 {mret.min():+.2f}%")
        print(f"    最大连续亏损月: ", end="")
        cnt = mx = 0
        for v in mret:
            cnt = cnt + 1 if v < 0 else 0
            mx = max(mx, cnt)
        print(f"{mx} 个")


def main():
    print("=" * 72)
    print("  心理承受力分析")
    print("=" * 72)

    for sym, tf, spread, mult, name in [
        ("XAUUSD", "H1", 0.08, 100.0, "黄金 H1"),
        ("XAUUSD", "H4", 0.08, 100.0, "黄金 H4"),
        ("XAUUSD", "M5", 0.08, 100.0, "黄金 M5"),
    ]:
        df = load(sym, tf)
        if df is None:
            continue
        r = backtest(df, spread=spread, mult=mult)
        if r is None:
            continue
        eq, trades, equity0 = r
        analyze(name, eq, trades, equity0)


if __name__ == "__main__":
    main()
