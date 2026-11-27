# -*- coding: utf-8 -*-
"""三品种 × 三周期：原版 vs 加保本规则，全部画成曲线图

品种：XAUUSD / DE40 / US500
周期：M5 / H1 / H4
每格：两条净值线 + 两条回撤线
"""

import os
import sys

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = r"C:\Users\26217\Documents\deepseek-harness\default-workspace"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "osma"))
sys.path.insert(0, os.path.join(ROOT, "risk"))

from indicator import osma                     # noqa: E402
from vol_event_layer import atrp                # noqa: E402

BG = (247, 247, 244)
INK = (26, 32, 44)
MUTED = (126, 134, 148)
C_BASE = (70, 130, 200)
C_BE = (230, 110, 60)
GRID = (238, 238, 234)

SPECS = {
    "XAUUSD": dict(spread=0.08, mult=100.0, lots=1.0, name="黄金"),
    "DE40":   dict(spread=1.5,  mult=1.0,   lots=40.0, name="德指"),
    "US500":  dict(spread=0.5,  mult=1.0,   lots=100.0, name="标普"),
}


def F(size, bold=False):
    ps = [r"C:\Windows\Fonts\msyhbd.ttc"] if bold else []
    ps += [r"C:\Windows\Fonts\msyh.ttc"]
    for p in ps:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def load(sym, tf):
    p = os.path.join(ROOT, f"{sym}_{tf}_Tickmill-DemoUK.csv")
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, parse_dates=["time"]).set_index("time").sort_index()


def backtest(df, spread, mult, lots, factor=1.4,
             equity0=1_000_000.0, stop_atr=1.5,
             use_breakeven=False, profit_bars=10, be_at_r=1.0):
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
    n_stop = n_be_arms = 0

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
                    n_be_arms += 1

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

    eq = pd.Series(curve, index=idx) / equity0 * 100
    leg_arr = np.array(legs) if legs else np.array([0.0])
    dd = eq - eq.cummax()
    days = max((idx[-1] - idx[0]).days, 1)
    ret = float(eq.iloc[-1])
    w = leg_arr[leg_arr > 0]
    l = leg_arr[leg_arr < 0]

    return dict(eq=eq, dd=dd, days=days, ret=ret, mdd=float(dd.min()),
                calmar=ret / abs(dd.min()) if dd.min() else np.nan,
                win=len(w) / max(len(leg_arr), 1) * 100,
                pf=(w.sum() / -l.sum()) if len(l) and l.sum() != 0 else np.inf,
                n=len(trades), n_stop=n_stop, n_be=n_be_arms,
                ann=((1 + ret / 100) ** (365 / days) - 1) * 100 if ret > -100 else -100)


def mini_panel(d, x, y, w, h, r_base, r_be, title, sub):
    d.rectangle([x, y, x + w, y + h], fill=(255, 255, 255), outline=(216, 216, 210))
    d.text((x + 14, y + 10), title, font=F(17, True), fill=INK)
    d.text((x + 14, y + 32), sub, font=F(12), fill=MUTED)

    # 净值区（上 60%）
    nh = int((h - 90) * 0.62)
    dd_h = (h - 90) - nh - 12

    x0, x1 = x + 66, x + w - 20
    ny0, ny1 = y + 58, y + 58 + nh
    dy0, dy1 = ny1 + 30, ny1 + 30 + dd_h

    # 净值
    eb, ebe = r_base["eq"], r_be["eq"]
    vmin = min(eb.min(), ebe.min())
    vmax = max(eb.max(), ebe.max())
    mg = (vmax - vmin) * 0.12 or 1
    vmin -= mg; vmax += mg
    n = len(eb)

    def sy(v):
        return ny1 - (ny1 - ny0) * (v - vmin) / (vmax - vmin)

    for k in range(4):
        v = vmin + (vmax - vmin) * k / 3
        yy = sy(v)
        d.line([x0, yy, x1, yy], fill=GRID, width=1)
        d.text((x + 8, yy - 7), f"{v:.0f}", font=F(10), fill=MUTED)

    if vmin < 0 < vmax:
        d.line([x0, sy(0), x1, sy(0)], fill=(170, 170, 170), width=1)

    cols = min(n, x1 - x0)
    for series, color in [(eb, C_BASE), (ebe, C_BE)]:
        vals = series.to_numpy()
        pts = []
        for c in range(cols):
            i0 = int(c * n / cols)
            i1 = max(i0 + 1, int((c + 1) * n / cols))
            pts.append((x0 + c, sy(float(vals[i0:i1].mean()))))
        d.line(pts, fill=color, width=1 if cols > 800 else 2)

    # 回撤
    dmin = min(r_base["dd"].min(), r_be["dd"].min()) * 1.1
    if dmin == 0:
        dmin = -1

    def sy2(v):
        return dy1 - (dy1 - dy0) * (v - 0) / (dmin - 0)

    for series, color, fill_c in [(r_base["dd"], C_BASE, (214, 228, 245)),
                                   (r_be["dd"], C_BE, (250, 228, 214))]:
        vals = series.to_numpy()
        pts = []
        for c in range(cols):
            i0 = int(c * n / cols)
            i1 = max(i0 + 1, int((c + 1) * n / cols))
            pts.append((x0 + c, sy2(float(vals[i0:i1].mean()))))
        d.polygon([(x0, sy2(0))] + pts + [(pts[-1][0], sy2(0))], fill=fill_c)
        d.line(pts, fill=color, width=1 if cols > 800 else 2)

    d.line([x0, dy0, x1, dy0], fill=(160, 160, 160), width=1)
    d.text((x + 8, dy0 - 7), "0", font=F(10), fill=MUTED)
    d.text((x + 8, dy1 - 10), f"{dmin:.0f}", font=F(10), fill=MUTED)

    # 时间轴
    idx = eb.index
    for frac in [0, 0.5, 1.0]:
        i = int(frac * (n - 1))
        lab = idx[i].strftime("%y-%m")
        xx = x0 + (x1 - x0) * frac
        tw = d.textlength(lab, font=F(10))
        d.text((xx - tw / 2, dy1 + 4), lab, font=F(10), fill=MUTED)

    # 底部统计
    ty = y + h - 24
    d.text((x + 14, ty),
           f"{r_base['ret']:+.1f}% → {r_be['ret']:+.1f}%   "
           f"回撤 {r_base['mdd']:.1f}% → {r_be['mdd']:.1f}%   "
           f"卡玛 {r_base['calmar']:.1f} → {r_be['calmar']:.1f}   "
           f"胜率 {r_base['win']:.0f}% → {r_be['win']:.0f}%",
           font=F(12), fill=(50, 58, 72))


def main():
    TFS = ["M5", "H1", "H4"]
    SYMS = ["XAUUSD", "DE40", "US500"]

    # 先算
    results = {}
    for tf in TFS:
        for sym in SYMS:
            df = load(sym, tf)
            if df is None:
                continue
            cfg = SPECS[sym]
            b = backtest(df, cfg["spread"], cfg["mult"], cfg["lots"], use_breakeven=False)
            e = backtest(df, cfg["spread"], cfg["mult"], cfg["lots"], use_breakeven=True)
            if b and e:
                results[(sym, tf)] = (b, e)

    # 画图：每行一个品种，三列三个周期
    NW, NH = 560, 330
    W = 60 + NW * 3 + 40
    H = 170 + NH * 3 + 60
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((54, 28), "保本止损规则 · 三品种 × 三周期", font=F(34, True), fill=INK)
    d.text((56, 76),
           "蓝 = 原版　　橙 = 加保本规则（连续10根盈利K线 或 浮盈≥1倍止损距离 → 止损移成本位）",
           font=F(15), fill=MUTED)

    for ri, sym in enumerate(SYMS):
        y = 130 + ri * NH
        d.text((54, y + 6), SPECS[sym]["name"], font=F(22, True), fill=(40, 108, 178))
        for ci, tf in enumerate(TFS):
            key = (sym, tf)
            x = 130 + ci * NW
            if key not in results:
                continue
            b, e = results[key]
            sub = f"{b['eq'].index[0]:%y-%m}→{b['eq'].index[-1]:%y-%m}  {b['n']}笔"
            mini_panel(d, x, y, NW - 24, NH - 24, b, e, tf, sub)

    # 底部汇总
    ty = 130 + 3 * NH + 10
    d.line([54, ty, W - 54, ty], fill=(212, 212, 205), width=1)
    d.text((54, ty + 14), "汇总：收益变化 / 卡玛变化（保本 − 原版）", font=F(17, True), fill=INK)

    heads = ["品种", "M5 收益", "M5 卡玛", "H1 收益", "H1 卡玛", "H4 收益", "H4 卡玛"]
    widths = [120, 150, 130, 150, 130, 150, 130]
    xx = 60
    yy = ty + 46
    for hd, wd in zip(heads, widths):
        d.text((xx, yy), hd, font=F(14, True), fill=(96, 104, 118))
        xx += wd
    yy += 26
    for sym in SYMS:
        xx = 60
        d.text((xx, yy), SPECS[sym]["name"], font=F(14, True), fill=INK)
        xx += widths[0]
        for tf in TFS:
            key = (sym, tf)
            if key in results:
                b, e = results[key]
                dret = e["ret"] - b["ret"]
                dcal = e["calmar"] - b["calmar"]
                d.text((xx, yy), f"{dret:+.2f}%",
                       font=F(14), fill=(30, 140, 80) if dret > 0 else (190, 60, 60))
                xx += widths[1]
                d.text((xx, yy), f"{dcal:+.2f}",
                       font=F(14), fill=(30, 140, 80) if dcal > 0 else (190, 60, 60))
                xx += widths[2]
        yy += 24

    out = os.path.join(ROOT, "保本规则_三品种三周期.png")
    img.save(out)
    print("saved", out, img.size)

    print("\n" + "=" * 88)
    print(f"{'品种':<8}{'周期':<6}{'原版收益%':>11}{'保本收益%':>11}{'差异':>9}"
          f"{'原版卡玛':>10}{'保本卡玛':>10}{'差异':>9}{'胜率变化':>10}")
    print("-" * 88)
    for sym in SYMS:
        for tf in TFS:
            key = (sym, tf)
            if key not in results:
                continue
            b, e = results[key]
            print(f"{SPECS[sym]['name']:<8}{tf:<6}{b['ret']:>11.2f}{e['ret']:>11.2f}"
                  f"{e['ret']-b['ret']:>+9.2f}{b['calmar']:>10.2f}{e['calmar']:>10.2f}"
                  f"{e['calmar']-b['calmar']:>+9.2f}{e['win']-b['win']:>+10.1f}")


if __name__ == "__main__":
    main()
