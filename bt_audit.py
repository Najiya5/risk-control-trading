# -*- coding: utf-8 -*-
"""回测全面审查版

修正清单：
  1. 点差：开仓 + 平仓各扣一次（原来是单边）
  2. 手续费：每手每边固定金额
  3. 滑点：止损出场时多亏 N 个点
  4. 与净值恒等校验：pnls 合计 必须 == 净值终值
  5. 分笔统计：区分「完整交易」和「减仓腿」

另外做参数扫描：单边 vs 双边点差，看差多少。
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


def load(tf):
    p = os.path.join(ROOT, f"XAUUSD_{tf}_Tickmill-DemoUK.csv")
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, parse_dates=["time"]).set_index("time").sort_index()


def backtest(df, factor=1.4, lot=1.0, contract=100.0,
             equity0=1_000_000.0, stop_atr=1.5,
             spread=0.08, spread_sides=2,        # ★ 点差扣几边
             commission_per_lot=0.0,             # ★ 手续费/手/边
             slippage=0.0,                       # ★ 滑点（美元/盎司）
             use_gate=True, use_cut=True,
             allow_reentry_same_bar=False):
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

    gate = (atrp_v > atrp_ma * factor) if use_gate else np.zeros(len(ind), bool)

    def cost_of(l):
        """l 手，一次往返的成本””（按 spread_sides 边算）"""
        sp = spread * l * contract * (spread_sides / 2.0)
        cm = commission_per_lot * l * 2      # 开+平
        return sp + cm

    pos = 0
    lots = lot
    ep = 0.0
    ei = 0
    vol_cut = False
    equity = 0.0
    curve = np.zeros(len(ind))
    legs = []           # 每次平仓腿的盈亏
    trades = []         # 完整交易（含减仓腿汇总）
    cur_legs = []       # 当前持仓期间的腿
    n_block = n_cut = n_stop = 0

    for i in range(len(ind)):
        p = price[i]
        stopped = False

        # ── 止损 ──
        if pos == 1:
            sl = ep - atr_v[ei] * stop_atr
            if low[i] <= sl:
                fill = sl - slippage          # ★ 滑点：比止损价更差
                pnl = (fill - ep) * lots * contract - cost_of(lots)
                equity += pnl
                legs.append(pnl)
                cur_legs.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur_legs),
                                   bars=i - ei, why="stop"))
                cur_legs = []
                pos = 0
                n_stop += 1
                stopped = True
        elif pos == -1:
            sl = ep + atr_v[ei] * stop_atr
            if high[i] >= sl:
                fill = sl + slippage
                pnl = (ep - fill) * lots * contract - cost_of(lots)
                equity += pnl
                legs.append(pnl)
                cur_legs.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur_legs),
                                   bars=i - ei, why="stop"))
                cur_legs = []
                pos = 0
                n_stop += 1
                stopped = True

        if not stopped:
            # ── 持仓风控减半 ──
            if use_cut and pos != 0 and gate[i] and not vol_cut:
                cut = round(lots * 0.5 / 0.01) * 0.01
                if cut > 0:
                    part = ((p - ep) if pos == 1 else (ep - p)) * cut * contract
                    part -= cost_of(cut)
                    equity += part
                    legs.append(part)
                    cur_legs.append(part)
                    lots = round((lots - cut) / 0.01) * 0.01
                    vol_cut = True
                    n_cut += 1
                    if lots < 0.01:
                        trades.append(dict(exit=idx[i], pnl=sum(cur_legs),
                                           bars=i - ei, why="cut_full"))
                        cur_legs = []
                        pos = 0

            # ── 信号消失 ──
            if pos == 1 and not (o[i] > 0 and s[i] > 0):
                pnl = (p - ep) * lots * contract - cost_of(lots)
                equity += pnl
                legs.append(pnl)
                cur_legs.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur_legs),
                                   bars=i - ei, why="signal"))
                cur_legs = []
                pos = 0
            elif pos == -1 and not (o[i] < 0 and s[i] < 0):
                pnl = (ep - p) * lots * contract - cost_of(lots)
                equity += pnl
                legs.append(pnl)
                cur_legs.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur_legs),
                                   bars=i - ei, why="signal"))
                cur_legs = []
                pos = 0

            # ── 开仓 ──
            can_open = (not stopped) if not allow_reentry_same_bar else True
            if pos == 0 and can_open and ((o[i] > 0 and s[i] > 0) or (o[i] < 0 and s[i] < 0)):
                if gate[i]:
                    n_block += 1
                else:
                    pos = 1 if (o[i] > 0 and s[i] > 0) else -1
                    ep = p
                    ei = i
                    lots = lot
                    vol_cut = False
                    cur_legs = []

        if pos == 1:
            curve[i] = equity + (p - ep) * lots * contract
        elif pos == -1:
            curve[i] = equity + (ep - p) * lots * contract
        else:
            curve[i] = equity

    eq = pd.Series(curve, index=idx)
    leg_arr = np.array(legs) if legs else np.array([0.0])
    tr = pd.DataFrame(trades)

    tot = equity0 + eq
    ddp = ((tot - tot.cummax()) / tot.cummax()).min() * 100
    ret = float(eq.iloc[-1] / equity0 * 100)

    # ★ 恒等校验
    diff = abs(leg_arr.sum() - eq.iloc[-1])
    if diff > 1.0:
        print(f"  ⚠ 校验失败：legs 合计 {leg_arr.sum():,.0f} ≠ 净值 {eq.iloc[-1]:,.0f}")

    w = leg_arr[leg_arr > 0]
    l = leg_arr[leg_arr < 0]
    out = dict(
        factor=factor, n_trades=len(tr), n_legs=len(leg_arr),
        ret=ret, mdd_pct=float(ddp),
        calmar=ret / abs(ddp) if ddp else np.nan,
        n_block=n_block, n_cut=n_cut, n_stop=n_stop,
        win_legs=len(w) / max(len(leg_arr), 1) * 100,
        pf_legs=(w.sum() / -l.sum()) if len(l) and l.sum() != 0 else np.inf,
        cost_total=float(leg_arr.sum() and (n_stop + len(tr)) * 0),  # 占位
    )
    if len(tr):
        tw = tr[tr.pnl > 0]
        tl = tr[tr.pnl < 0]
        out.update(
            win_trades=len(tw) / len(tr) * 100 if len(tr) else 0,
            pf_trades=(tw.pnl.sum() / -tl.pnl.sum()) if len(tl) and tl.pnl.sum() != 0 else np.inf,
            avg_bars=float(tr.bars.mean()),
        )
    return out, tr, eq


def main():
    print("=" * 104)
    print("  回测全面审查")
    print("=" * 104)

    scenarios = [
        ("① 无成本",            dict(spread=0.0,  spread_sides=1, commission_per_lot=0, slippage=0)),
        ("② A: 单边+无佣金",     dict(spread=0.08, spread_sides=1, commission_per_lot=0, slippage=0)),
        ("③ B: 单边+滑点",       dict(spread=0.08, spread_sides=1, commission_per_lot=0, slippage=0.05)),
        ("④ C: 单边+滑点+佣金7",  dict(spread=0.08, spread_sides=1, commission_per_lot=7.0, slippage=0.05)),
        ("⑤ 压力:双边+佣金7",     dict(spread=0.08, spread_sides=2, commission_per_lot=7.0, slippage=0.05)),
    ]

    all_rows = []
    for tf in ["M5", "H1", "H4"]:
        df = load(tf)
        if df is None:
            continue
        print(f"\n〔{tf}〕{df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}   {len(df)} 根")
        print(f"{'情景':<24}{'笔数':>7}{'收益%':>10}{'回撤%':>9}{'卡玛':>7}"
              f"{'胜率%':>8}{'PF(腿)':>9}{'PF(笔)':>9}")
        print("-" * 104)
        for label, kw in scenarios:
            r = backtest(df, **kw)
            if r is None:
                continue
            s, tr, eq = r
            print(f"{label:<24}{s['n_trades']:>7}{s['ret']:>10.2f}{s['mdd_pct']:>9.2f}"
                  f"{s['calmar']:>7.2f}{s['win_legs']:>8.1f}"
                  f"{s['pf_legs']:>9.2f}{s.get('pf_trades', float('nan')):>9.2f}")
            all_rows.append(dict(tf=tf, scenario=label, **s))

    out = pd.DataFrame(all_rows)
    p = os.path.join(ROOT, "回测_全面审查.csv")
    out.to_csv(p, index=False, encoding="utf-8-sig")
    print(f"\n结果 -> {p}")


if __name__ == "__main__":
    main()
