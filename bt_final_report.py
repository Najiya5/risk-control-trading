# -*- coding: utf-8 -*-
"""最终版回测 + 年化 + 曲线图

口径（已确认）：
  - 数据源：MT4 .hst 导出的 OHLC（bid 价）
  - 点差：单边 0.08（做多做空各承担一次）
  - 佣金：0（Tickmill 无佣金，成本在点差里）
  - 滑点：止损出场 0.05
  - 止损：1.5 × ATR
  - 持仓风控：ATRP 越线减半
  - 仓位：1 手固定
  - 初始：100 万

年化：
  简单年化 = 总收益 / 天数 × 365
  复合年化 = (1 + 总收益)^(365/天数) - 1
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


# ═══ 固定口径 ═══
LOT = 1.0
CONTRACT = 100.0
EQUITY0 = 1_000_000.0
STOP_ATR = 1.5
SPREAD = 0.08
SLIPPAGE = 0.05
COMMISSION = 0.0
FACTOR = 1.4
CUT_RATIO = 0.5


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
        return SPREAD * l * CONTRACT + COMMISSION * l * 2

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
                cut = round(lots * CUT_RATIO / 0.01) * 0.01
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
    mdd = float(dd.min())

    # 年化
    ann_simple = ret / days * 365
    ann_compound = ((1 + ret / 100) ** (365 / days) - 1) * 100 if ret > -100 else -100

    # 夏普（按日收益）
    daily = eq.resample("1D").last().dropna()
    if len(daily) > 2:
        dret = daily.diff().dropna()
        sharpe = dret.mean() / dret.std() * np.sqrt(252) if dret.std() > 0 else 0
    else:
        sharpe = 0

    w = leg_arr[leg_arr > 0]
    l = leg_arr[leg_arr < 0]

    return dict(
        tf=None, bars=len(ind), days=days,
        start=idx[0], end=idx[-1],
        n_trades=len(tr), n_legs=len(leg_arr),
        n_block=n_block, n_cut=n_cut, n_stop=n_stop,
        ret=ret, mdd=mdd,
        calmar=ret / abs(mdd) if mdd else np.nan,
        ann_simple=ann_simple, ann_compound=ann_compound,
        sharpe=sharpe,
        win_legs=len(w) / max(len(leg_arr), 1) * 100,
        pf=(w.sum() / -l.sum()) if len(l) and l.sum() != 0 else np.inf,
        eq=eq, dd=dd,
        check_diff=abs(leg_arr.sum() - eq.iloc[-1] / 100 * EQUITY0),
    )


# ══════════════════════════════════════════════
# 画图
# ══════════════════════════════════════════════

def box(d, x, y, w, h, fill=(255, 255, 255), edge=(214, 214, 208)):
    d.rectangle([x, y, x + w, y + h], fill=fill, outline=edge)


def panel(d, x, y, w, h, series, title, sub, color, is_dd, ylab):
    box(d, x, y, w, h)
    d.text((x + 14, y + 10), title, font=F(17, True), fill=(28, 34, 46))
    if sub:
        d.text((x + 14, y + 32), sub, font=F(12), fill=(130, 138, 152))

    pl, pr, pt, pb = 62, 16, 58, 36
    x0, y0 = x + pl, y + pt
    x1, y1 = x + w - pr, y + h - pb

    vals = series.values
    vmin, vmax = float(vals.min()), float(vals.max())
    if is_dd:
        vmax = 0.0
    mg = (vmax - vmin) * 0.12 or 0.5
    vmin -= mg
    vmax += mg

    n = len(vals)
    if n < 2:
        return
    def sx(i): return x0 + (x1 - x0) * i / (n - 1)
    def sy(v): return y1 - (y1 - y0) * (v - vmin) / (vmax - vmin)

    for k in range(5):
        v = vmin + (vmax - vmin) * k / 4
        yy = sy(v)
        d.line([x0, yy, x1, yy], fill=(240, 240, 236), width=1)
        d.text((x + 10, yy - 8), f"{v:.1f}", font=F(12), fill=(120, 128, 142))

    if vmin < 0 < vmax:
        zy = sy(0)
        d.line([x0, zy, x1, zy], fill=(150, 150, 150), width=1)

    cols = min(n, x1 - x0)
    pts = []
    for c in range(cols):
        i0 = int(c * n / cols)
        i1 = max(i0 + 1, int((c + 1) * n / cols))
        pts.append((x0 + c, sy(float(vals[i0:i1].mean()))))

    if is_dd:
        d.polygon([(x0, sy(0))] + pts + [(pts[-1][0], sy(0))], fill=(240, 194, 192))
        d.line(pts, fill=(188, 66, 62), width=2)
    else:
        d.line(pts, fill=color, width=2)

    idx = series.index
    for frac in [0, 0.25, 0.5, 0.75, 1.0]:
        i = int(frac * (n - 1))
        xx = sx(i)
        lab = idx[i].strftime("%y-%m")
        tw = d.textlength(lab, font=F(12))
        d.text((xx - tw / 2, y1 + 9), lab, font=F(12), fill=(120, 128, 142))
    d.text((x + 10, y0 - 20), ylab, font=F(11), fill=(140, 148, 162))


def draw(results):
    W = 1760
    ROW = 310
    H = 150 + ROW * len(results) + 210
    img = Image.new("RGB", (W, H), (246, 246, 243))
    d = ImageDraw.Draw(img)

    d.text((44, 26), "OsMA + ATRP 风控策略 · 回测曲线与年化", font=F(30, True), fill=(24, 30, 42))
    d.text((46, 70),
           "XAUUSD ｜ factor=1.4 ｜ 止损 1.5×ATR ｜ 单边点差 0.08 + 滑点 0.05 ｜ 无佣金 ｜ 1 手固定 ｜ 初始 100 万",
           font=F(14), fill=(120, 128, 142))

    y = 116
    for r in results:
        d.text((44, y), r["tf"], font=F(24, True), fill=(40, 108, 178))
        d.text((44, y + 30),
               f"{r['start']:%Y-%m-%d} → {r['end']:%Y-%m-%d}   {r['days']} 天",
               font=F(13), fill=(132, 140, 154))

        pw = (W - 88 - 36) // 2
        panel(d, 44, y + 56, pw, ROW - 76, r["eq"],
              f"净值   {r['ret']:+.2f}%", f"年化 {r['ann_compound']:+.1f}%",
              (40, 108, 178), False, "收益率 %")
        panel(d, 44 + pw + 36, y + 56, pw, ROW - 76, r["dd"],
              f"回撤   最大 {r['mdd']:.2f}%", None,
              (188, 66, 62), True, "回撤 %")
        y += ROW

    # ── 汇总表 ──
    y += 6
    d.line([44, y, W - 44, y], fill=(212, 212, 205), width=1)
    y += 16
    d.text((44, y), "年化汇总", font=F(19, True), fill=(28, 34, 46))
    y += 32

    heads = ["周期", "天数", "交易", "总收益", "年化(复合)", "年化(简单)",
             "最大回撤", "卡玛", "夏普", "胜率", "PF"]
    widths = [70, 80, 90, 110, 130, 120, 110, 90, 90, 90, 80]
    x = 52
    for hd, wd in zip(heads, widths):
        d.text((x, y), hd, font=F(14, True), fill=(96, 104, 118))
        x += wd
    y += 24
    d.line([52, y - 4, W - 60, y - 4], fill=(228, 228, 222), width=1)

    for r in results:
        vals = [r["tf"], str(r["days"]), str(r["n_trades"]),
                f"{r['ret']:+.2f}%", f"{r['ann_compound']:+.1f}%",
                f"{r['ann_simple']:+.1f}%", f"{r['mdd']:.2f}%",
                f"{r['calmar']:.2f}", f"{r['sharpe']:.2f}",
                f"{r['win_legs']:.1f}%", f"{r['pf']:.2f}"]
        x = 52
        for v, wd in zip(vals, widths):
            bold = v in ("M5", "H1", "H4")
            d.text((x, y), v, font=F(14, bold), fill=(44, 52, 66))
            x += wd
        y += 24

    # 说明
    y += 20
    d.line([44, y, W - 44, y], fill=(212, 212, 205), width=1)
    y += 14
    notes = [
        "年化(复合) = (1+总收益)^(365/天数) - 1    年化(简单) = 总收益 / 天数 × 365",
        "夏普 = 日收益均值 / 日收益标准差 × √252（无风险利率按 0）",
        "各周期数据长度不同，比较请用年化而不是总收益",
    ]
    for nt in notes:
        d.text((52, y), nt, font=F(12), fill=(140, 148, 162))
        y += 19

    out = os.path.join(ROOT, "回测曲线图.png")
    img.save(out)
    return out


def main():
    print("=" * 96)
    print("  最终回测（单边点差 0.08 + 滑点 0.05，无佣金）")
    print("=" * 96)

    results = []
    for tf in ["M5", "H1", "H4"]:
        df = load(tf)
        if df is None:
            continue
        r = backtest(df)
        if r is None:
            continue
        r["tf"] = tf
        results.append(r)
        print(f"\n〔{tf}〕{r['start']:%Y-%m-%d} → {r['end']:%Y-%m-%d}  "
              f"{r['days']} 天  {r['bars']} 根")
        print(f"  交易 {r['n_trades']} 笔（{r['n_legs']} 腿）  "
              f"拦截 {r['n_block']}  减仓 {r['n_cut']}  止损 {r['n_stop']}")
        print(f"  总收益 {r['ret']:+.2f}%   年化(复合) {r['ann_compound']:+.2f}%   "
              f"年化(简单) {r['ann_simple']:+.2f}%")
        print(f"  最大回撤 {r['mdd']:.2f}%   卡玛 {r['calmar']:.2f}   夏普 {r['sharpe']:.2f}")
        print(f"  胜率 {r['win_legs']:.1f}%   PF {r['pf']:.2f}")
        if r["check_diff"] > 100:
            print(f"  ⚠ 校验偏差 {r['check_diff']:.0f}")

    out = draw(results)
    print(f"\n图已保存: {out}")


if __name__ == "__main__":
    main()
