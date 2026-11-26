# -*- coding: utf-8 -*-
"""同时间段对比：三个周期截取同一区间，才有可比性

区间取三者交集：2025-08-14 → 2026-07-03
（M5 起点最晚、H1 终点最早，取交集）
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

LOT = 1.0
CONTRACT = 100.0
EQUITY0 = 1_000_000.0
STOP_ATR = 1.5
SPREAD = 0.08
SLIPPAGE = 0.05
FACTOR = 1.4


def load(tf):
    p = os.path.join(ROOT, f"XAUUSD_{tf}_Tickmill-DemoUK.csv")
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, parse_dates=["time"]).set_index("time").sort_index()


def backtest(df, factor=FACTOR):
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
    atrp_v = ind["atrp"].to_numpy()
    atrp_ma = ind["atrp_ma"].to_numpy()
    atr_v = ind["atr"].to_numpy()
    idx = ind.index

    gate = atrp_v > atrp_ma * factor

    def cost_of(l):
        return SPREAD * l * CONTRACT

    pos = 0
    lots = LOT
    ep = 0.0
    ei = 0
    vol_cut = False
    equity = 0.0
    curve = np.zeros(len(ind))
    legs = []
    trades = []
    cur = []
    n_block = n_cut = n_stop = 0

    for i in range(len(ind)):
        p = price[i]
        stopped = False

        if pos == 1:
            sl = ep - atr_v[ei] * STOP_ATR
            if low[i] <= sl:
                fill = sl - SLIPPAGE
                pnl = (fill - ep) * lots * CONTRACT - cost_of(lots)
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei))
                cur = []; pos = 0; n_stop += 1; stopped = True
        elif pos == -1:
            sl = ep + atr_v[ei] * STOP_ATR
            if high[i] >= sl:
                fill = sl + SLIPPAGE
                pnl = (ep - fill) * lots * CONTRACT - cost_of(lots)
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei))
                cur = []; pos = 0; n_stop += 1; stopped = True

        if not stopped:
            if pos != 0 and gate[i] and not vol_cut:
                cut = round(lots * 0.5 / 0.01) * 0.01
                if cut > 0:
                    part = ((p - ep) if pos == 1 else (ep - p)) * cut * CONTRACT - cost_of(cut)
                    equity += part; legs.append(part); cur.append(part)
                    lots = round((lots - cut) / 0.01) * 0.01
                    vol_cut = True; n_cut += 1
                    if lots < 0.01:
                        trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei))
                        cur = []; pos = 0

            if pos == 1 and not (o[i] > 0 and s[i] > 0):
                pnl = (p - ep) * lots * CONTRACT - cost_of(lots)
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei))
                cur = []; pos = 0
            elif pos == -1 and not (o[i] < 0 and s[i] < 0):
                pnl = (ep - p) * lots * CONTRACT - cost_of(lots)
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei))
                cur = []; pos = 0

            if pos == 0 and ((o[i] > 0 and s[i] > 0) or (o[i] < 0 and s[i] < 0)):
                if gate[i]:
                    n_block += 1
                else:
                    pos = 1 if (o[i] > 0 and s[i] > 0) else -1
                    ep = p; ei = i; lots = LOT; vol_cut = False; cur = []

        if pos == 1:
            curve[i] = equity + (p - ep) * lots * CONTRACT
        elif pos == -1:
            curve[i] = equity + (ep - p) * lots * CONTRACT
        else:
            curve[i] = equity

    eq = pd.Series(curve, index=idx) / EQUITY0 * 100.0
    leg_arr = np.array(legs) if legs else np.array([0.0])
    tr = pd.DataFrame(trades)
    dd = eq - eq.cummax()

    days = max((idx[-1] - idx[0]).days, 1)
    ret = float(eq.iloc[-1])
    ann = ((1 + ret / 100) ** (365 / days) - 1) * 100 if ret > -100 else -100

    daily = eq.resample("1D").last().dropna()
    dret = daily.diff().dropna()
    sharpe = (dret.mean() / dret.std() * np.sqrt(252)) if len(dret) > 2 and dret.std() > 0 else 0

    w = leg_arr[leg_arr > 0]
    l = leg_arr[leg_arr < 0]

    return dict(bars=len(ind), days=days, start=idx[0], end=idx[-1],
                n_trades=len(tr), n_block=n_block, n_cut=n_cut, n_stop=n_stop,
                ret=ret, ann=ann, mdd=float(dd.min()),
                calmar=ret / abs(dd.min()) if dd.min() else np.nan,
                sharpe=sharpe, win=len(w) / max(len(leg_arr), 1) * 100,
                pf=(w.sum() / -l.sum()) if len(l) and l.sum() != 0 else np.inf,
                avg_bars=float(tr.bars.mean()) if len(tr) else 0)


def main():
    # 找三个周期的交集
    frames = {}
    for tf in ["M5", "H1", "H4"]:
        df = load(tf)
        if df is not None:
            frames[tf] = df

    starts = [df.index[0] for df in frames.values()]
    ends = [df.index[-1] for df in frames.values()]
    t0 = max(starts)
    t1 = min(ends)

    print("=" * 96)
    print("  同时间段对比")
    print("=" * 96)
    print(f"  交集区间：{t0} → {t1}   ({(t1 - t0).days} 天)")
    print()
    for tf, df in frames.items():
        print(f"  {tf} 原始范围：{df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}  {len(df)} 根")
    print()

    print(f"{'周期':<6}{'K线数':>8}{'交易':>7}{'拦截':>7}{'减仓':>7}{'止损':>7}"
          f"{'收益%':>9}{'年化%':>9}{'回撤%':>9}{'卡玛':>7}{'夏普':>7}{'胜率%':>8}{'PF':>7}")
    print("-" * 96)

    rows = []
    for tf in ["M5", "H1", "H4"]:
        df = frames.get(tf)
        if df is None:
            continue
        seg = df.loc[t0:t1]
        r = backtest(seg)
        if r is None:
            continue
        print(f"{tf:<6}{r['bars']:>8}{r['n_trades']:>7}{r['n_block']:>7}{r['n_cut']:>7}"
              f"{r['n_stop']:>7}{r['ret']:>9.2f}{r['ann']:>9.1f}{r['mdd']:>9.2f}"
              f"{r['calmar']:>7.2f}{r['sharpe']:>7.2f}{r['win']:>8.1f}{r['pf']:>7.2f}")
        rows.append(dict(tf=tf, **r))

    print()
    if rows:
        df_out = pd.DataFrame(rows)
        p = os.path.join(ROOT, "回测_同时间段对比.csv")
        df_out.to_csv(p, index=False, encoding="utf-8-sig")
        print(f"结果 -> {p}")


if __name__ == "__main__":
    main()
