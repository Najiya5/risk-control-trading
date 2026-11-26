# -*- coding: utf-8 -*-
"""回测曲线图（纯 PIL 绘制，不依赖 matplotlib）"""

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


def F(size, bold=False):
    ps = [r"C:\Windows\Fonts\msyhbd.ttc"] if bold else []
    ps += [r"C:\Windows\Fonts\msyh.ttc"]
    for p in ps:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def load(tf):
    p = os.path.join(ROOT, f"XAUUSD_{tf}_Tickmill-DemoUK.csv")
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, parse_dates=["time"]).set_index("time").sort_index()


def backtest_curve(df, factor=1.6, lot=1.0, contract=100.0,
                   equity0=1_000_000.0, stop_atr=1.5, spread=0.08):
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
    cost = spread * lot * contract

    pos = 0
    lots = lot
    ep = 0.0
    ei = 0
    vol_cut = False
    equity = 0.0
    curve = np.zeros(len(ind))
    pnls = []

    for i in range(len(ind)):
        p = price[i]

        # ★ 不可以用 continue：跳过赋值会让 curve[i] 留在初始 0，
        #   净值曲线出现假归零，回撤被算成「峰值全额」。
        #   这里改成置标记，最后统一赋值。
        stopped = False
        if pos == 1 and low[i] <= ep - atr_v[ei] * stop_atr:
            sl = ep - atr_v[ei] * stop_atr
            pnl = (sl - ep) * lots * contract - cost
            equity += pnl
            pnls.append(pnl)
            pos = 0
            stopped = True
        elif pos == -1 and high[i] >= ep + atr_v[ei] * stop_atr:
            sl = ep + atr_v[ei] * stop_atr
            pnl = (ep - sl) * lots * contract - cost
            equity += pnl
            pnls.append(pnl)
            pos = 0
            stopped = True

        if not stopped:
            if pos != 0 and gate[i] and not vol_cut:
                cut = round(lots * 0.5 / 0.01) * 0.01
                if cut > 0:
                    part = ((p - ep) if pos == 1 else (ep - p)) * cut * contract
                    part -= cost * cut / lot
                    equity += part
                    pnls.append(part)      # ★ 减仓的盈亏也要计入，否则净值涨了 PF 看不到
                    lots = round((lots - cut) / 0.01) * 0.01
                    vol_cut = True
                    if lots < 0.01:
                        pos = 0

            if pos == 1 and not (o[i] > 0 and s[i] > 0):
                pnl = (p - ep) * lots * contract - cost
                equity += pnl
                pnls.append(pnl)
                pos = 0
            elif pos == -1 and not (o[i] < 0 and s[i] < 0):
                pnl = (ep - p) * lots * contract - cost
                equity += pnl
                pnls.append(pnl)
                pos = 0

            if pos == 0 and ((o[i] > 0 and s[i] > 0) or (o[i] < 0 and s[i] < 0)):
                if not gate[i]:
                    pos = 1 if (o[i] > 0 and s[i] > 0) else -1
                    ep = p
                    ei = i
                    lots = lot
                    vol_cut = False

        if pos == 1:
            curve[i] = equity + (p - ep) * lots * contract
        elif pos == -1:
            curve[i] = equity + (ep - p) * lots * contract
        else:
            curve[i] = equity

    eq = pd.Series(curve, index=idx) / equity0 * 100.0
    return eq, np.array(pnls)


def draw_panel(d, x, y, w, h, series, title, color, is_dd, ylab):
    # 背景
    d.rectangle([x, y, x + w, y + h], fill=(255, 255, 255), outline=(210, 210, 205))
    d.text((x + 10, y + 8), title, font=F(17, True), fill=(30, 36, 48))

    pad_l, pad_r, pad_t, pad_b = 62, 14, 40, 34
    px0, py0 = x + pad_l, y + pad_t
    px1, py1 = x + w - pad_r, y + h - pad_b

    vals = series.values
    vmin, vmax = float(vals.min()), float(vals.max())
    if is_dd:
        vmax = 0.0
    margin = (vmax - vmin) * 0.12 or 0.5
    vmin -= margin
    vmax += margin

    n = len(vals)
    if n < 2:
        return

    def sx(i):
        return px0 + (px1 - px0) * i / (n - 1)

    def sy(v):
        return py1 - (py1 - py0) * (v - vmin) / (vmax - vmin)

    # 网格 + y 轴刻度
    for k in range(5):
        v = vmin + (vmax - vmin) * k / 4
        yy = sy(v)
        d.line([px0, yy, px1, yy], fill=(238, 238, 234), width=1)
        d.text((x + 8, yy - 8), f"{v:.1f}", font=F(12), fill=(120, 128, 142))

    # 零线
    if vmin < 0 < vmax:
        zy = sy(0)
        d.line([px0, zy, px1, zy], fill=(150, 150, 150), width=1)

    # 曲线（降采样到像素宽度，取每列 min/max）
    cols = min(n, px1 - px0)
    pts = []
    for c in range(cols):
        i0 = int(c * n / cols)
        i1 = max(i0 + 1, int((c + 1) * n / cols))
        seg = vals[i0:i1]
        pts.append((px0 + c, sy(float(seg.mean()))))

    if is_dd:
        poly = [(px0, sy(0))] + pts + [(pts[-1][0], sy(0))]
        d.polygon(poly, fill=(238, 190, 188))
        d.line(pts, fill=(190, 70, 66), width=2)
    else:
        d.line(pts, fill=color, width=2)

    # 轴标签
    idx = series.index
    for k, frac in enumerate([0, 0.25, 0.5, 0.75, 1.0]):
        i = int(frac * (n - 1))
        xx = sx(i)
        lab = idx[i].strftime("%y-%m")
        tw = d.textlength(lab, font=F(12))
        d.text((xx - tw / 2, py1 + 8), lab, font=F(12), fill=(120, 128, 142))
    d.text((x + 8, py0 - 24), ylab, font=F(12), fill=(120, 128, 142))


def main():
    tfs = ["M5", "H1", "H4"]
    results = []
    for tf in tfs:
        df = load(tf)
        if df is None:
            continue
        r = backtest_curve(df)
        if r is None:
            continue
        eq, pnls = r
        dd = eq - eq.cummax()
        w = pnls[pnls > 0]
        l = pnls[pnls < 0]
        results.append(dict(
            tf=tf, eq=eq, dd=dd, pnls=pnls,
            ret=float(eq.iloc[-1]), mdd=float(dd.min()),
            n=len(pnls),
            win=len(w) / len(pnls) * 100 if len(pnls) else 0,
            pf=(w.sum() / -l.sum()) if len(l) and l.sum() != 0 else np.nan,
            start=eq.index[0], end=eq.index[-1],
        ))

    W = 1700
    ROW = 300
    H = 130 + ROW * len(results) + 120
    img = Image.new("RGB", (W, H), (247, 247, 244))
    d = ImageDraw.Draw(img)

    d.text((40, 28), "OsMA + ATRP 风控策略 · 回测曲线", font=F(32, True), fill=(25, 32, 46))
    d.text((42, 74),
           "XAUUSD ｜ factor=1.4 ｜ 止损 1.5×ATR ｜ 含点差 0.08 ｜ 1 手固定仓位 ｜ 初始 100 万",
           font=F(16), fill=(120, 128, 142))

    y = 118
    for r in results:
        d.text((40, y), r["tf"], font=F(24, True), fill=(42, 111, 181))
        d.text((40, y + 32),
               f"{r['start']:%Y-%m-%d} → {r['end']:%Y-%m-%d}",
               font=F(13), fill=(130, 138, 152))

        panel_w = (W - 80 - 40) // 2
        draw_panel(d, 40, y + 58, panel_w, ROW - 78, r["eq"],
                   f"净值  最终 {r['ret']:.2f}%", (42, 111, 181), False, "收益率 %")
        draw_panel(d, 40 + panel_w + 40, y + 58, panel_w, ROW - 78, r["dd"],
                   f"回撤  最大 {r['mdd']:.2f}%", (190, 70, 66), True, "回撤 %")

        # 统计条：放在两个面板中间的空隙下方
        stats = [
            ("交易", f"{r['n']} 笔"),
            ("胜率", f"{r['win']:.1f}%"),
            ("盈亏因子", f"{r['pf']:.2f}"),
        ]
        sx = 40 + panel_w + 40 + 150
        yy = y + 62
        for k, v in stats:
            d.text((sx, yy), k, font=F(11), fill=(150, 158, 172))
            tw = d.textlength(k, font=F(11))
            d.text((sx + tw + 5, yy - 2), v, font=F(12, True), fill=(40, 48, 62))
            yy += 19

        y += ROW

    # 底部汇总
    y += 10
    d.line([40, y, W - 40, y], fill=(215, 215, 208), width=1)
    y += 18
    d.text((40, y), "汇总", font=F(18, True), fill=(30, 36, 48))
    y += 32
    head = f"{'周期':<6}{'交易':>8}{'收益%':>11}{'回撤%':>11}{'胜率%':>10}{'PF':>8}"
    d.text((50, y), head, font=F(14, True), fill=(90, 98, 112))
    y += 22
    for r in results:
        line = f"{r['tf']:<6}{r['n']:>8}{r['ret']:>11.2f}{r['mdd']:>11.2f}{r['win']:>10.1f}{r['pf']:>8.2f}"
        d.text((50, y), line, font=F(14), fill=(50, 58, 72))
        y += 20

    out = os.path.join(ROOT, "回测曲线图.png")
    img.save(out)
    print("已保存:", out, img.size)
    print()
    print(head)
    for r in results:
        print(f"{r['tf']:<6}{r['n']:>8}{r['ret']:>11.2f}{r['mdd']:>11.2f}{r['win']:>10.1f}{r['pf']:>8.2f}")


if __name__ == "__main__":
    main()
