# -*- coding: utf-8 -*-
"""重画风控框架结构图 —— 反映最新改动

新增/变更：
  · 总分析师改为三路取最大（已实现波动率 / ATR% / VIX）
  · 休盘平仓前 10 分钟
  · 保本止损规则（回测验证，程序暂未启用，图中标注）
  · 日历降级（金十 → 备用源）
"""

import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
BG = (248, 248, 245)
INK = (28, 34, 46)
MUTED = (128, 136, 150)


def F(size, bold=False):
    ps = [r"C:\Windows\Fonts\msyhbd.ttc"] if bold else []
    ps += [r"C:\Windows\Fonts\msyh.ttc"]
    for p in ps:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def box(d, x, y, w, h, title, lines, fill, edge, ts=19, bs=14, lh=7):
    d.rounded_rectangle([x, y, x + w, y + h], radius=9, fill=fill, outline=edge, width=2)
    d.text((x + 13, y + 9), title, font=F(ts, True), fill=INK)
    yy = y + 9 + ts + 10
    for ln in lines:
        if yy + bs > y + h - 3:
            break
        bold = ln.startswith("\u2605")
        d.text((x + 13, yy), ln, font=F(bs, bold), fill=INK)
        yy += bs + lh


def arrow(d, x1, y1, x2, y2, color=(122, 132, 148), w=2, dash=False):
    import math
    if dash:
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        n = max(2, int(L / 11))
        for k in range(n):
            if k % 2 == 0:
                d.line([x1 + dx * k / n, y1 + dy * k / n,
                        x1 + dx * (k + 1) / n, y1 + dy * (k + 1) / n], fill=color, width=w)
    else:
        d.line([x1, y1, x2, y2], fill=color, width=w)
    a = math.atan2(y2 - y1, x2 - x1)
    for b in (a + 2.55, a - 2.55):
        d.line([x2, y2, x2 + 10 * math.cos(b), y2 + 10 * math.sin(b)], fill=color, width=w)


def path(d, pts, dash=False, color=(122, 132, 148), w=2):
    for i in range(len(pts) - 2):
        d.line([pts[i], pts[i + 1]], fill=color, width=w)
    arrow(d, pts[-2][0], pts[-2][1], pts[-1][0], pts[-1][1], color, w, dash)


def divider(d, y, W):
    d.line([(54, y), (W - 54, y)], fill=(220, 220, 214), width=1)


def draw():
    W, H = 2000, 1660
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((54, 28), "风控框架结构", font=F(36, True), fill=INK)
    d.text((56, 76), "原则：风控只防「跨日不恢复」的系统性风险，不干预盘中正常波动",
           font=F(17), fill=MUTED)

    # ══ 顶层：数据 / 指标 / 外部 ══
    box(d, 54, 126, 380, 150, "数据层",
        ["MT5（实时行情 + VIX）", "本地 CSV（历史回测）",
         "金十快讯 / 财经日历"],
        (232, 241, 252), (70, 116, 176))

    box(d, 474, 126, 420, 150, "指标层",
        ["OsMA：加权价格 MACD + 信号线",
         "ATRP：(ATR3+ATR10)/2 ÷ C ×100",
         "Parabolic SAR（M15，可选过滤）"],
        (232, 246, 236), (66, 138, 96))
    arrow(d, 434, 201, 470, 201)

    box(d, 934, 126, 470, 150, "外部数据",
        ["VIX  ← MT5（D1，2020 起）",
         "财经日历 ← 金十，失败降级",
         "事件 ← 金十快讯 + LLM"],
        (250, 246, 232), (168, 148, 88))
    arrow(d, 894, 201, 930, 201)

    divider(d, 302, W)

    # ══ 风控三层 ══
    d.text((54, 318), "风控三层", font=F(23, True), fill=(80, 88, 102))

    box(d, 54, 360, 600, 220, "① 开仓前拦截",
        ["ATRP > MA(20) × 1.4         → 不开",
         "总分析师百分位 ≥ 98%          → 不开",
         "签字过期（超 24 小时）         → 不开",
         "",
         "★ 只做过滤，不调配额",
         "★ ATRP factor 硬下限 1.4"],
        (250, 238, 238), (186, 78, 78))

    box(d, 700, 360, 620, 220, "② 持仓中减仓（双规则各占 50%）",
        ["ATRP 越线            → 平掉当前持仓的一半",
         "事件严重度 ≥ 0.7      → 平掉当前持仓的一半",
         "两条同时触发          → 归零",
         "",
         "★ 每次平「当前持仓」的一半（连乘）",
         "★ 每条规则每次开仓只触发一次"],
        (250, 240, 226), (186, 138, 62))

    box(d, 1366, 360, 580, 220, "③ 时间强制清空",
        ["纽约休盘前 10 分钟",
         "→ 平掉全部持仓",
         "→ 撤销全部挂单",
         "",
         "★ 让「最差情况是一天」成立",
         "★ 夏令时 21:00 / 冬令时 22:00 UTC"],
        (232, 238, 250), (70, 116, 176))

    divider(d, 602, W)

    # ══ 触发来源 ══
    d.text((54, 618), "风控触发来源", font=F(23, True), fill=(80, 88, 102))

    box(d, 54, 660, 600, 270, "波动率风控（本地计算）",
        ["ATRP = ((ATR3 + ATR10) / 2) ÷ Close × 100",
         "",
         "ATRP > MA(20) × factor  → 触发",
         "",
         "★ 纯本地，不依赖任何外部服务",
         "★ 权重 0.5",
         "★ 全市场极端时它一定先响"],
        (232, 246, 236), (66, 138, 96))

    box(d, 700, 660, 620, 270, "事件风控（金十 + LLM）",
        ["金十快讯 → 过滤重要资讯",
         "→ 多家模型独立判断（同一 schema）",
         "   impact / severity / horizon / reason",
         "→ 去极值取平均 → 分歧检查",
         "",
         "★ 平均 severity ≥ 0.7 → 触发",
         "★ 权重 0.5",
         "★ 全挂 → 压力按 0，不中断"],
        (250, 240, 226), (186, 138, 62))

    box(d, 1366, 660, 580, 270, "总分析师（日线，每天一次）",
        ["三路独立信号，各算自己的历史百分位：",
         "  已实现波动率(20)   ← 黄金价格",
         "  ATR%(14)          ← 黄金价格",
         "  VIX               ← 市场恐慌 ★新增",
         "",
         "★ 取最大值：任一路报警就算报警",
         "  ≥98% → 暂停开仓",
         "  90-98% → 仓位减半",
         "  <90% → 正常"],
        (238, 230, 248), (120, 92, 172))

    path(d, [(124, 660), (124, 584)])
    path(d, [(1010, 660), (1010, 584)])
    path(d, [(1656, 660), (1656, 584)], dash=True)

    divider(d, 952, W)

    # ══ 执行层 ══
    d.text((54, 968), "执行层", font=F(23, True), fill=(80, 88, 102))

    box(d, 54, 1010, 660, 190, "下单与平仓",
        ["手数 = 基础手数 × 压力系数 × 总系数",
         "　　　（所有系数 ≤ 1.0，只减不加）",
         "止损 = 1.5 × ATR，随单挂上",
         "平仓：信号消失 / 止损 / 风控减仓 / 休盘清空"],
        (238, 230, 248), (120, 92, 172))

    box(d, 750, 1010, 560, 190, "断点续跑",
        ["state.json：持仓、权益、签字、当日盈亏",
         "程序被 kill 后重启能接上",
         "",
         "★ 每轮决策后落盘，不依赖内存",
         "★ 签字字段只由 UI 写，主循环不覆盖"],
        (240, 240, 238), (140, 140, 136))

    path(d, [(40, 660), (40, 1008), (48, 1008)])

    divider(d, 1222, W)

    # ══ 审计层 ══
    d.text((54, 1238), "审计层", font=F(23, True), fill=(80, 88, 102))

    box(d, 54, 1280, 580, 210, "每日战报（20:00 自动生成）",
        ["· 今日交易明细（按平仓时间归类）",
         "· 风控状态（权益 / 持仓 / 三路明细）",
         "· 今日事件判断（LLM 理由）",
         "· 未来三天重要数据（金十→备用降级）",
         "",
         "★ 数据源异常写进日志和战报"],
        (232, 241, 252), (70, 116, 176))

    box(d, 670, 1280, 580, 210, "签字门槛",
        ["战报未滚动读完 → 签字按钮是灰的",
         "",
         "★ 签一次 = 24 小时授权",
         "★ 过期只平仓不开新仓",
         "★ 程序不中断，只是不做了"],
        (250, 238, 238), (186, 78, 78))

    box(d, 1286, 1280, 660, 210, "可追溯记录",
        ["logs/run_YYYYMMDD.log        每轮决策完整日志",
         "logs/events.csv             事件判断（JSON 行）",
         "logs/calendar_source.log    日历数据源降级记录",
         "logs/trades.csv             每笔交易明细",
         "",
         "★ 出了事能倒查每一步为什么这么做"],
        (240, 240, 238), (140, 140, 136))

    path(d, [(40, 1200), (40, 1278), (48, 1278)])

    # ══ 底部：未启用的规则 ══
    divider(d, H - 196, W)
    d.text((54, H - 176), "回测已验证、但程序暂未启用的规则", font=F(20, True), fill=(150, 110, 60))
    d.text((54, H - 140),
           "保本止损：连续 10 根 K 线收盘盈利，或最大浮盈达到初始止损距离的 1 倍 → 止损移到成本位",
           font=F(16), fill=(90, 96, 110))
    d.text((60, H - 114),
           "回测效果（黄金 H1）：收益 +0.95%、卡玛 +0.10；代价是胜率 -3.6 个点、止损次数 +28%",
           font=F(16), fill=(90, 96, 110))

    divider(d, H - 86, W)
    d.text((54, H - 64),
           "每 15 秒看一次：该平仓吗？该开仓吗？开仓前过三道拦截；休盘前全平，签字过期只平不开。",
           font=F(20, True), fill=(70, 80, 100))

    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, "风控框架结构图.png")
    img.save(out)
    print("saved", out, img.size)


if __name__ == "__main__":
    draw()
