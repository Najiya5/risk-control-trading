# -*- coding: utf-8 -*-
"""画黄金 H1 的对比曲线：原版 vs 加保本规则"""

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
C_BASE = (70, 130, 200)      # 原版 蓝
C_BE = (230, 110, 60)        # 保本 橙
GRID = (236, 236, 232)


def F(size, bold=False):
    ps = [r"C:\Windows\Fonts\msyhbd.ttc"] if bold else []
    ps += [r"C:\Windows\Fonts\msyh.ttc"]
    for p in ps:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def load(sym, tf):
    p = os.path.join(ROOT, f"{sym}_{tf}_Tickmill-DemoUK.csv")
    return pd.read_csv(p, parse_dates=["time"]).set_index("time").sort_index()


def backtest(df, spread=0.08, mult=100.0, lots=1.0, factor=1.4,
             equity0=1_000_000.0, stop_atr=1.5,
             use_breakeven=False, profit_bars=10, be_at_r=1.0,
             return_curve=False):
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
    n_stop = n_be_arms = n_be_hits = 0

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
            trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei,
                               stop_px=stop_price, entry=ep, side=pos,
                               be=be_armed))
            cur = []; pos = 0; n_stop += 1; stopped = True
            if be_armed:
                n_be_hits += 1
        elif pos == -1 and high[i] >= stop_price:
            pnl = (ep - stop_price) * cur_lots * mult - cost_of(cur_lots)
            equity += pnl; legs.append(pnl); cur.append(pnl)
            trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei,
                               stop_px=stop_price, entry=ep, side=pos,
                               be=be_armed))
            cur = []; pos = 0; n_stop += 1; stopped = True
            if be_armed:
                n_be_hits += 1

        if not stopped:
            if use_breakeven and pos != 0 and not be_armed:
                favor = (p - ep) if pos == 1 else (ep - p)
                if favor > 0:
                    profit_streak += 1
                else:
                    profit_streak = 0
                if favor > max_favor:
                    max_favor = favor
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
                        trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei,
                                           stop_px=np.nan, entry=ep, side=pos,
                                           be=be_armed))
                        cur = []; pos = 0

            if pos == 1 and not (o[i] > 0 and s[i] > 0):
                pnl = (p - ep) * cur_lots * mult - cost_of(cur_lots)
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei,
                                   stop_px=np.nan, entry=ep, side=pos,
                                   be=be_armed))
                cur = []; pos = 0
            elif pos == -1 and not (o[i] < 0 and s[i] < 0):
                pnl = (ep - p) * cur_lots * mult - cost_of(cur_lots)
                equity += pnl; legs.append(pnl); cur.append(pnl)
                trades.append(dict(exit=idx[i], pnl=sum(cur), bars=i - ei,
                                   stop_px=np.nan, entry=ep, side=pos,
                                   be=be_armed))
                cur = []; pos = 0

            if pos == 0 and ((o[i] > 0 and s[i] > 0) or (o[i] < 0 and s[i] < 0)):
                if not gate[i]:
                    pos = 1 if (o[i] > 0 and s[i] > 0) else -1
                    ep = p; ei = i; cur_lots = lots; vol_cut = False; cur = []
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

    eq = pd.Series(curve, index=idx) / equity0 * 100
    tr = pd.DataFrame(trades)
    leg_arr = np.array(legs) if legs else np.array([0.0])
    dd = eq - eq.cummax()
    w = leg_arr[leg_arr > 0]
    l = leg_arr[leg_arr < 0]
    days = max((idx[-1] - idx[0]).days, 1)
    ret = float(eq.iloc[-1])

    return dict(eq=eq, dd=dd, tr=tr, days=days,
                ret=ret, mdd=float(dd.min()),
                calmar=ret / abs(dd.min()) if dd.min() else np.nan,
                win=len(w) / max(len(leg_arr), 1) * 100,
                pf=(w.sum() / -l.sum()) if len(l) and l.sum() != 0 else np.inf,
                n=len(tr), n_stop=n_stop,
                n_be_arms=n_be_arms, n_be_hits=n_be_hits,
                ann=((1 + ret / 100) ** (365 / days) - 1) * 100 if ret > -100 else -100)


def draw(r_base, r_be):
    W, H = 1900, 1420
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((54, 30), "黄金 H1 · 保本止损实验", font=F(36, True), fill=INK)
    d.text((56, 78),
           "规则一：连续10根K线收盘盈利 → 止损移成本位   ｜   "
           "规则二：最大浮盈≥初始止损距离×1 → 止损移成本位",
           font=F(16), fill=MUTED)

    # ══ 面板 1：净值曲线（两条叠一起）══
    PX, PY, PW, PH = 54, 130, W - 108, 420
    d.rectangle([PX, PY, PX + PW, PY + PH], fill=(255, 255, 255), outline=(214, 214, 208))

    pl, pr, pt, pb = 76, 30, 46, 42
    x0, y0 = PX + pl, PY + pt
    x1, y1 = PX + PW - pr, PY + PH - pb

    eb, ebe = r_base["eq"], r_be["eq"]
    vmin = min(eb.min(), ebe.min())
    vmax = max(eb.max(), ebe.max())
    mg = (vmax - vmin) * 0.1 or 1
    vmin -= mg
    vmax += mg

    n = len(eb)

    def sx(i):
        return x0 + (x1 - x0) * i / (n - 1)

    def sy(v):
        return y1 - (y1 - y0) * (v - vmin) / (vmax - vmin)

    for k in range(6):
        v = vmin + (vmax - vmin) * k / 5
        yy = sy(v)
        d.line([x0, yy, x1, yy], fill=GRID, width=1)
        d.text((PX + 14, yy - 8), f"{v:.1f}%", font=F(13), fill=MUTED)

    if vmin < 0 < vmax:
        d.line([x0, sy(0), x1, sy(0)], fill=(160, 160, 160), width=1)

    cols = min(n, x1 - x0)
    for series, color in [(eb, C_BASE), (ebe, C_BE)]:
        vals = series.to_numpy()
        pts = []
        for c in range(cols):
            i0 = int(c * n / cols)
            i1 = max(i0 + 1, int((c + 1) * n / cols))
            pts.append((x0 + c, sy(float(vals[i0:i1].mean()))))
        d.line(pts, fill=color, width=2)

    idx = eb.index
    for frac in [0, 0.2, 0.4, 0.6, 0.8, 1.0]:
        i = int(frac * (n - 1))
        lab = idx[i].strftime("%y-%m-%d")
        tw = d.textlength(lab, font=F(12))
        d.text((sx(i) - tw / 2, y1 + 10), lab, font=F(12), fill=MUTED)

    # 图例
    lx = X1 = PX + PW - 320
    d.line([lx, PY + 22, lx + 28, PY + 22], fill=C_BASE, width=3)
    d.text((lx + 36, PY + 14), f"原版  {r_base['ret']:+.2f}%", font=F(15, True), fill=INK)
    d.line([lx + 150, PY + 22, lx + 178, PY + 22], fill=C_BE, width=3)
    d.text((lx + 186, PY + 14), f"+保本  {r_be['ret']:+.2f}%", font=F(15, True), fill=INK)

    # ══ 面板 2：回撤对比（上下两条带）══
    PY2 = PY + PH + 46
    PH2 = 300
    d.rectangle([PX, PY2, PX + PW, PY2 + PH2], fill=(255, 255, 255), outline=(214, 214, 208))
    d.text((PX + 16, PY2 + 12), "回撤曲线", font=F(18, True), fill=INK)

    y0b, y1b = PY2 + 60, PY2 + PH2 - 34
    dmin = min(r_base["dd"].min(), r_be["dd"].min())
    dmax = 0.0
    md = abs(dmin) * 1.1 or 1

    def sy2(v):
        return y1b - (y1b - y0b) * (v - dmax) / (dmin * 1.1 - dmax)

    for k in range(5):
        v = dmax + (dmin * 1.1 - dmax) * k / 4
        yy = sy2(v)
        d.line([x0, yy, x1, yy], fill=GRID, width=1)
        d.text((PX + 14, yy - 8), f"{v:.1f}%", font=F(13), fill=MUTED)

    for series, color, alpha_fill in [
            (r_base["dd"], C_BASE, (210, 226, 244)),
            (r_be["dd"], C_BE, (250, 226, 212))]:
        vals = series.to_numpy()
        pts = []
        for c in range(cols):
            i0 = int(c * n / cols)
            i1 = max(i0 + 1, int((c + 1) * n / cols))
            pts.append((x0 + c, sy2(float(vals[i0:i1].mean()))))
        d.polygon([(x0, sy2(0))] + pts + [(pts[-1][0], sy2(0))], fill=alpha_fill)
        d.line(pts, fill=color, width=2)

    for frac in [0, 0.2, 0.4, 0.6, 0.8, 1.0]:
        i = int(frac * (n - 1))
        lab = idx[i].strftime("%y-%m-%d")
        tw = d.textlength(lab, font=F(12))
        d.text((sx(i) - tw / 2, y1b + 10), lab, font=F(12), fill=MUTED)

    lx = PX + PW - 360
    d.line([lx, PY2 + 22, lx + 28, PY2 + 22], fill=C_BASE, width=3)
    d.text((lx + 36, PY2 + 14), f"原版 {r_base['mdd']:.2f}%", font=F(14, True), fill=INK)
    d.line([lx + 170, PY2 + 22, lx + 198, PY2 + 22], fill=C_BE, width=3)
    d.text((lx + 206, PY2 + 14), f"+保本 {r_be['mdd']:.2f}%", font=F(14, True), fill=INK)

    # ══ 下方汇总表 ══
    TY = PY2 + PH2 + 46
    d.line([54, TY, W - 54, TY], fill=(212, 212, 205), width=1)

    heads = ["", "交易", "止损", "保本触发", "胜率", "PF", "总收益", "年化", "最大回撤", "卡玛"]
    widths = [140, 110, 100, 120, 110, 100, 120, 120, 120, 100]
    xx = 60
    for hd, wd in zip(heads, widths):
        d.text((xx, TY + 20), hd, font=F(15, True), fill=(96, 104, 118))
        xx += wd

    def row(y, name, r, color):
        vals = [name, str(r["n"]), str(r["n_stop"]),
                str(r["n_be_arms"]) if r["n_be_arms"] else "—",
                f"{r['win']:.1f}%", f"{r['pf']:.2f}",
                f"{r['ret']:+.2f}%", f"{r['ann']:+.1f}%",
                f"{r['mdd']:.2f}%", f"{r['calmar']:.2f}"]
        xx = 60
        for v, wd in zip(vals, widths):
            d.text((xx, y), v, font=F(15), fill=color)
            xx += wd

    row(TY + 54, "原版", r_base, C_BASE)
    row(TY + 84, "+保本规则", r_be, C_BE)

    # 差异
    d.text((60, TY + 122),
           f"差异    收益 {r_be['ret'] - r_base['ret']:+.2f}%    "
           f"年化 {r_be['ann'] - r_base['ann']:+.1f}%    "
           f"回撤 {r_be['mdd'] - r_base['mdd']:+.2f}%    "
           f"卡玛 {r_be['calmar'] - r_base['calmar']:+.2f}    "
           f"胜率 {r_be['win'] - r_base['win']:+.1f}%",
           font=F(15, True), fill=(60, 68, 84))

    out = os.path.join(ROOT, "黄金H1_保本规则对比.png")
    img.save(out)
    print("saved", out)


if __name__ == "__main__":
    df = load("XAUUSD", "H1")
    print(f"黄金 H1: {len(df)} 根  {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}")

    base = backtest(df, use_breakeven=False)
    be = backtest(df, use_breakeven=True)

    for tag, r in [("原版", base), ("+保本", be)]:
        print(f"  {tag}: 交易{r['n']} 止损{r['n_stop']} 保本{r['n_be_arms']} "
              f"胜率{r['win']:.1f}% PF{r['pf']:.2f} "
              f"收益{r['ret']:+.2f}% 回撤{r['mdd']:.2f}% 卡玛{r['calmar']:.2f}")

    draw(base, be)
