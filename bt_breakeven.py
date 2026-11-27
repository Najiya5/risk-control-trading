# -*- coding: utf-8 -*-
"""实验：加两条保本止损规则

规则一（连续盈利 K 线）：
  持仓期间，连续 N 根 K 线【收盘时】处于盈利状态
  → 止损移到入场价（成本位）
  中间断一根就清零重数

规则二（浮盈达初始止损距离）：
  最大浮盈 >= 初始止损距离 × 1 倍
  → 止损移到入场价

两条独立触发，谁先到用谁。
触发后止损不再移动（停在成本位）。

对照：不加这两条规则的原始版本
"""

import os
import sys
import itertools

import numpy as np
import pandas as pd

ROOT = r"C:\Users\26217\Documents\deepseek-harness\default-workspace"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "osma"))
sys.path.insert(0, os.path.join(ROOT, "risk"))

from indicator import osma                     # noqa: E402
from vol_event_layer import atrp                # noqa: E402

SPECS = {
    "XAUUSD": dict(spread=0.08, mult=100.0, lots=1.0,  label="黄金"),
    "DE40":   dict(spread=1.5,  mult=1.0,   lots=40.0, label="德指"),
    "US500":  dict(spread=0.5,  mult=1.0,   lots=100.0, label="标普"),
}


def load(sym, tf):
    p = os.path.join(ROOT, f"{sym}_{tf}_Tickmill-DemoUK.csv")
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, parse_dates=["time"]).set_index("time").sort_index()


def backtest(df, spread, mult, lots, factor=1.4,
             equity0=1_000_000.0, stop_atr=1.5,
             use_breakeven=False,       # ★ 是否启用两条保本规则
             profit_bars=10,            # 规则一：连续盈利 K 线根数
             be_at_r=1.0):              # 规则二：浮盈 = 初始止损距离 × 这个倍数
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
    n_block = n_cut = n_stop = n_be = 0

    # 保本状态
    stop_price = 0.0
    be_armed = False
    profit_streak = 0
    max_favor = 0.0        # 最大浮盈（价格单位）
    init_stop_dist = 0.0

    for i in range(len(ind)):
        p = price[i]
        stopped = False

        # ── 止损检查（用当前止损价，可能是成本位）──
        if pos == 1 and low[i] <= stop_price:
            fill = stop_price
            pnl = (fill - ep) * cur_lots * mult - cost_of(cur_lots)
            equity += pnl; legs.append(pnl); cur.append(pnl)
            trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei,
                               how="stop_be" if be_armed else "stop"))
            cur = []; pos = 0; n_stop += 1; stopped = True
            if be_armed:
                n_be += 1
        elif pos == -1 and high[i] >= stop_price:
            fill = stop_price
            pnl = (ep - fill) * cur_lots * mult - cost_of(cur_lots)
            equity += pnl; legs.append(pnl); cur.append(pnl)
            trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei,
                               how="stop_be" if be_armed else "stop"))
            cur = []; pos = 0; n_stop += 1; stopped = True
            if be_armed:
                n_be += 1

        if not stopped:
            # ── 保本规则检查（用当根收盘）──
            if use_breakeven and pos != 0 and not be_armed:
                favor = (p - ep) if pos == 1 else (ep - p)

                # 规则一：连续盈利 K 线
                if favor > 0:
                    profit_streak += 1
                else:
                    profit_streak = 0

                # 规则二：浮盈达初始止损距离
                if favor > max_favor:
                    max_favor = favor

                hit1 = profit_streak >= profit_bars
                hit2 = max_favor >= init_stop_dist * be_at_r

                if hit1 or hit2:
                    stop_price = ep          # 移到成本位
                    be_armed = True
                    n_be += 1            # 计数（这个变量也记录"武装次数"）

            # ── 持仓风控减半 ──
            if pos != 0 and gate[i] and not vol_cut:
                cut = round(cur_lots * 0.5 / 0.01) * 0.01
                if cut > 0:
                    part = ((p - ep) if pos == 1 else (ep - p)) * cut * mult - cost_of(cut)
                    equity += part; legs.append(part); cur.append(part)
                    cur_lots = round((cur_lots - cut) / 0.01) * 0.01
                    vol_cut = True; n_cut += 1
                    if cur_lots < 0.01:
                        trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei,
                                           how="cut_full"))
                        cur = []; pos = 0

            # ── 信号消失平仓 ──
            if pos == 1 and not (o[i] > 0 and s[i] > 0):
                pnl = (p - ep) * cur_lots * mult - cost_of(cur_lots)
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei,
                                   how="signal_be" if be_armed else "signal"))
                cur = []; pos = 0
            elif pos == -1 and not (o[i] < 0 and s[i] < 0):
                pnl = (ep - p) * cur_lots * mult - cost_of(cur_lots)
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei,
                                   how="signal_be" if be_armed else "signal"))
                cur = []; pos = 0

            # ── 开仓 ──
            if pos == 0 and ((o[i] > 0 and s[i] > 0) or (o[i] < 0 and s[i] < 0)):
                if gate[i]:
                    n_block += 1
                else:
                    pos = 1 if (o[i] > 0 and s[i] > 0) else -1
                    ep = p; ei = i; cur_lots = lots; vol_cut = False; cur = []
                    # 初始化止损
                    init_stop_dist = atr_v[i] * stop_atr
                    stop_price = ep - init_stop_dist if pos == 1 else ep + init_stop_dist
                    be_armed = False
                    profit_streak = 0
                    max_favor = 0.0

        unreal = 0.0
        if pos == 1:
            unreal = (p - ep) * cur_lots * mult
        elif pos == -1:
            unreal = (ep - p) * cur_lots * mult
        curve[i] = equity + unreal

    eq = pd.Series(curve, index=idx)
    tr = pd.DataFrame(trades)
    leg_arr = np.array(legs) if legs else np.array([0.0])

    tot = equity0 + eq
    ddp = ((tot - tot.cummax()) / tot.cummax()).min() * 100
    ret = float(eq.iloc[-1] / equity0 * 100)
    days = max((idx[-1] - idx[0]).days, 1)
    w = leg_arr[leg_arr > 0]
    l = leg_arr[leg_arr < 0]

    return dict(bars=len(ind), days=days, start=idx[0], end=idx[-1],
                n=len(tr), n_block=n_block, n_cut=n_cut, n_stop=n_stop,
                n_be_arms=n_be,
                pnl=float(eq.iloc[-1]), ret=ret,
                mdd=float(ddp),
                calmar=ret / abs(ddp) if ddp else np.nan,
                ann=((1 + ret / 100) ** (365 / days) - 1) * 100 if ret > -100 else -100,
                win=len(w) / max(len(leg_arr), 1) * 100,
                pf=(w.sum() / -l.sum()) if len(l) and l.sum() != 0 else np.inf)


def main():
    print("=" * 108)
    print("  实验：保本止损规则")
    print("=" * 108)
    print("  规则一：连续 10 根 K 线收盘盈利 → 止损移到成本位")
    print("  规则二：最大浮盈 >= 初始止损距离 × 1 → 止损移到成本位")
    print("  触发后止损不再移动")

    for tf in ["M5", "H1", "H4"]:
        frames = {}
        for sym in SPECS:
            df = load(sym, tf)
            if df is not None:
                frames[sym] = df
        if not frames:
            continue

        t0 = max(d.index[0] for d in frames.values())
        t1 = min(d.index[-1] for d in frames.values())

        print()
        print("=" * 108)
        print(f"  {tf}   {t0:%Y-%m-%d} → {t1:%Y-%m-%d}  ({(t1-t0).days} 天)")
        print("=" * 108)
        print(f"{'品种':<7}{'模式':<10}{'交易':>6}{'止损':>6}{'保本触发':>9}{'胜率%':>8}"
              f"{'PF':>7}{'收益%':>9}{'回撤%':>9}{'卡玛':>7}{'年化%':>8}")
        print("-" * 108)

        for sym, df in frames.items():
            cfg = SPECS[sym]
            seg = df.loc[t0:t1]

            base = backtest(seg, cfg["spread"], cfg["mult"], cfg["lots"],
                            use_breakeven=False)
            be = backtest(seg, cfg["spread"], cfg["mult"], cfg["lots"],
                          use_breakeven=True)

            for tag, r in [("原版", base), ("+保本", be)]:
                if r is None:
                    continue
                print(f"{cfg['label']:<7}{tag:<10}{r['n']:>6}{r['n_stop']:>6}"
                      f"{r['n_be_arms']:>9}{r['win']:>8.1f}{r['pf']:>7.2f}"
                      f"{r['ret']:>9.2f}{r['mdd']:>9.2f}{r['calmar']:>7.2f}{r['ann']:>8.1f}")

            # 差异行
            if base and be:
                d_ret = be["ret"] - base["ret"]
                d_cal = be["calmar"] - base["calmar"]
                print(f"{'':7}{'  →差异':<10}{'':>6}{'':>6}{'':>9}{'':>8}"
                      f"{'':>7}{d_ret:>+9.2f}{'':>9}{d_cal:>+7.2f}")
            print()


if __name__ == "__main__":
    main()
