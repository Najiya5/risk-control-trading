# -*- coding: utf-8 -*-
"""多周期共振策略回测：M5 信号 + M15 SAR 过滤

对照：
  A. 单 M5 信号（不加 SAR 过滤）—— 之前测过的
  B. M5 信号 + M15 SAR 同向过滤  ← 用户实盘的"单边模型 C"
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
from strategy_multi_tf import load, sar_direction, align_direction  # noqa: E402

SPECS = {
    "XAUUSD": dict(spread=0.08, mult=100.0, lots=1.0, name="黄金"),
    "DE40":   dict(spread=1.5,  mult=1.0,   lots=40.0, name="德指"),
    "US500":  dict(spread=0.5,  mult=1.0,   lots=100.0, name="标普"),
}


def backtest(df, dir15, spread, mult, lots,
             factor=1.4, equity0=1_000_000.0, stop_atr=1.5,
             use_sar=False, use_gate=True,
             use_breakeven=True, profit_bars=10, be_at_r=1.0):
    """dir15: 对齐到 M5 时间轴的 M15 SAR 方向数组"""
    ind = atrp(df, 3, 10)
    ind = ind.join(osma(df, 5, 20, 30), how="inner", rsuffix="_o")
    ind = ind.dropna(subset=["atrp", "atrp_ma", "osma", "signal"])
    if len(ind) < 100:
        return None

    # 把 dir15 对齐到 ind 的时间轴
    d_al = pd.Series(dir15, index=df.index).reindex(ind.index).fillna(0).astype(int).to_numpy()

    o = ind["osma"].to_numpy()
    s = ind["signal"].to_numpy()
    price = ind["close"].to_numpy()
    high = ind["high"].to_numpy()
    low = ind["low"].to_numpy()
    av = ind["atrp"].to_numpy()
    am = ind["atrp_ma"].to_numpy()
    atr_v = ind["atr"].to_numpy()
    idx = ind.index
    gate = (av > am * factor) if use_gate else np.zeros(len(ind), bool)

    def cost_of(l):
        return spread * l * mult

    pos = 0
    cur_lots = lots
    ep = 0.0
    ei = 0
    vol_cut = False
    equity = 0.0
    curve = np.zeros(len(ind))
    legs = []
    trades = []
    cur = []
    n_block = n_stop = n_be = n_filtered = 0

    stop_price = 0.0
    be_armed = False
    profit_streak = 0
    max_favor = 0.0
    init_stop_dist = 0.0

    for i in range(len(ind)):
        p = price[i]
        stopped = False

        if pos == 1 and low[i] <= stop_price:
            pnl = (stop_price - ep) * cur_lots * mult - cost_of(cur_lots)
            equity += pnl; legs.append(pnl); cur.append(pnl)
            trades.append(sum(cur)); cur = []; pos = 0; n_stop += 1; stopped = True
        elif pos == -1 and high[i] >= stop_price:
            pnl = (ep - stop_price) * cur_lots * mult - cost_of(cur_lots)
            equity += pnl; legs.append(pnl); cur.append(pnl)
            trades.append(sum(cur)); cur = []; pos = 0; n_stop += 1; stopped = True

        if not stopped:
            if use_breakeven and pos != 0 and not be_armed:
                favor = (p - ep) if pos == 1 else (ep - p)
                profit_streak = profit_streak + 1 if favor > 0 else 0
                max_favor = max(max_favor, favor)
                if profit_streak >= profit_bars or max_favor >= init_stop_dist * be_at_r:
                    stop_price = ep
                    be_armed = True
                    n_be += 1

            if pos != 0 and gate[i] and not vol_cut:
                cut = round(cur_lots * 0.5 / 0.01) * 0.01
                if cut > 0:
                    part = ((p - ep) if pos == 1 else (ep - p)) * cut * mult - cost_of(cut)
                    equity += part; legs.append(part); cur.append(part)
                    cur_lots = round((cur_lots - cut) / 0.01) * 0.01
                    vol_cut = True
                    if cur_lots < 0.01:
                        trades.append(sum(cur)); cur = []; pos = 0

            if pos == 1 and not (o[i] > 0 and s[i] > 0):
                pnl = (p - ep) * cur_lots * mult - cost_of(cur_lots)
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(sum(cur)); cur = []; pos = 0
            elif pos == -1 and not (o[i] < 0 and s[i] < 0):
                pnl = (ep - p) * cur_lots * mult - cost_of(cur_lots)
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(sum(cur)); cur = []; pos = 0

            if pos == 0:
                want_long = o[i] > 0 and s[i] > 0
                want_short = o[i] < 0 and s[i] < 0
                if want_long or want_short:
                    # ★ SAR 过滤
                    if use_sar:
                        ok = (want_long and d_al[i] == 1) or (want_short and d_al[i] == -1)
                        if not ok:
                            n_filtered += 1
                            want_long = want_short = False

                    if want_long or want_short:
                        if gate[i]:
                            n_block += 1
                        else:
                            pos = 1 if want_long else -1
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

    eq = pd.Series(curve, index=idx) / equity0 * 100
    leg_arr = np.array(legs) if legs else np.array([0.0])
    dd = eq - eq.cummax()
    days = max((idx[-1] - idx[0]).days, 1)
    ret = float(eq.iloc[-1])
    w = leg_arr[leg_arr > 0]
    l = leg_arr[leg_arr < 0]

    return dict(bars=len(ind), days=days, eq=eq, dd=dd,
                n=len(trades), n_block=n_block, n_stop=n_stop,
                n_be=n_be, n_filtered=n_filtered,
                ret=ret, mdd=float(dd.min()),
                calmar=ret / abs(dd.min()) if dd.min() else np.nan,
                ann=((1 + ret / 100) ** (365 / days) - 1) * 100 if ret > -100 else -100,
                win=len(w) / max(len(leg_arr), 1) * 100,
                pf=(w.sum() / -l.sum()) if len(l) and l.sum() != 0 else np.inf)


def run(sym):
    df5 = load(sym, "M5")
    df15 = load(sym, "M15")
    if df5 is None or df15 is None:
        return None
    d15 = sar_direction(df15)
    al = align_direction(d15, df5.index)
    cfg = SPECS[sym]
    return df5, al, cfg


def main():
    print("=" * 104)
    print("  多周期共振：M5 信号 + M15 Parabolic SAR 过滤")
    print("=" * 104)
    print("  SAR 参数：Step=0.02, Maximum=0.2（MT4 默认）")
    print("  保本规则：已启用（连续10根盈利 or 浮盈≥1倍止损距离）")

    for sym in ["XAUUSD", "DE40", "US500"]:
        r = run(sym)
        if r is None:
            continue
        df5, al, cfg = r
        name = cfg["name"]

        print()
        print("=" * 104)
        print(f"  {name}  M5 {len(df5)} 根  {df5.index[0]:%Y-%m-%d} → {df5.index[-1]:%Y-%m-%d}")
        print("=" * 104)
        print(f"{'模式':<26}{'交易':>7}{'SAR滤掉':>9}{'ATRP拦':>8}{'止损':>7}{'保本':>6}"
              f"{'胜率%':>8}{'PF':>7}{'收益%':>10}{'回撤%':>9}{'卡玛':>7}{'年化%':>9}")
        print("-" * 104)

        for tag, use_sar in [("A. 单 M5 信号", False),
                             ("B. M5 + M15 SAR 同向", True)]:
            rr = backtest(df5, al, cfg["spread"], cfg["mult"], cfg["lots"],
                          use_sar=use_sar)
            if rr is None:
                continue
            print(f"{tag:<26}{rr['n']:>7}{rr['n_filtered']:>9}{rr['n_block']:>8}"
                  f"{rr['n_stop']:>7}{rr['n_be']:>6}{rr['win']:>8.1f}{rr['pf']:>7.2f}"
                  f"{rr['ret']:>10.2f}{rr['mdd']:>9.2f}{rr['calmar']:>7.2f}{rr['ann']:>9.1f}")


if __name__ == "__main__":
    main()
