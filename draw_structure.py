# -*- coding: utf-8 -*-
"""重画两张结构图（修连线与字形问题）"""

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
        bold = ln.startswith("★")
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
    """折线箭头"""
    for i in range(len(pts) - 2):
        d.line([pts[i], pts[i + 1]], fill=color, width=w)
    arrow(d, pts[-2][0], pts[-2][1], pts[-1][0], pts[-1][1], color, w, dash)


def divider(d, y, W):
    d.line([(54, y), (W - 54, y)], fill=(220, 220, 214), width=1)


# ══════════════════════════════════════════════════════════
def draw_risk():
    W, H = 2000, 1560
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((54, 28), "风控框架结构", font=F(36, True), fill=INK)
    d.text((56, 76), "原则：风控只防「跨日不恢复」的系统性风险，不干预盘中正常波动",
           font=F(17), fill=MUTED)

    # ── 数据 + 指标 ──
    box(d, 54, 126, 360, 120, "数据层",
        ["MT5 客户端（实时）", "本地 CSV（历史回测）", "xaus.com（备用）"],
        (232, 241, 252), (70, 116, 176))
    box(d, 474, 126, 380, 120, "指标层",
        ["OsMA：加权价格 MACD", "ATRP：(ATR3+ATR10)/2 ÷ C ×100", "MA(20) 做阈值均线"],
        (232, 246, 236), (66, 138, 96))
    arrow(d, 414, 186, 470, 186)

    divider(d, 272, W)

    # ── 风控三层 ──
    d.text((54, 288), "风控三层", font=F(23, True), fill=(80, 88, 102))

    box(d, 54, 330, 600, 200, "① 开仓前拦截",
        ["ATRP > MA(20) × 1.4       → 不开新仓",
         "昨日流动性百分位 ≥ 98%     → 不开新仓",
         "签字过期（超 24 小时）      → 不开新仓",
         "",
         "★ 只做过滤，不调配额",
         "★ ATRP factor 硬下限 1.4"],
        (250, 238, 238), (186, 78, 78))

    box(d, 700, 330, 620, 200, "② 持仓中减仓（双规则各占 50%）",
        ["ATRP 越线           → 平掉当前持仓的一半",
         "事件严重度 ≥ 0.7     → 平掉当前持仓的一半",
         "两条同时触发         → 归零",
         "",
         "★ 每次平「当前持仓」的一半（连乘）",
         "★ 每条规则每次开仓只触发一次"],
        (250, 240, 226), (186, 138, 62))

    box(d, 1366, 330, 580, 200, "③ 时间强制清空",
        ["纽约休盘前 5 分钟",
         "→ 平掉全部持仓",
         "→ 撤销全部挂单",
         "",
         "★ 让「最差情况是一天」成立",
         "★ 避开隔夜跳空"],
        (232, 238, 250), (70, 116, 176))

    divider(d, 552, W)

    # ── 触发来源 ──
    d.text((54, 568), "风控触发来源", font=F(23, True), fill=(80, 88, 102))

    box(d, 54, 610, 600, 240, "波动率风控（本地计算）",
        ["ATRP = ((ATR3 + ATR10) / 2) ÷ Close × 100",
         "",
         "ATRP > MA(20) × factor  → 触发",
         "",
         "★ 纯本地，不依赖任何外部服务",
         "★ 权重 0.5",
         "★ 全市场极端时它一定先响"],
        (232, 246, 236), (66, 138, 96))

    box(d, 700, 610, 620, 240, "事件风控（金十 + LLM）",
        ["金十快讯 → 过滤重要资讯",
         "→ 多家模型独立判断（同一 schema）",
         "   impact / severity / horizon / reason",
         "→ 去极值取平均 → 分歧检查",
         "",
         "★ 平均 severity ≥ 0.7 → 触发",
         "★ 权重 0.5"],
        (250, 240, 226), (186, 138, 62))

    box(d, 1366, 610, 580, 240, "总分析师（日线，每天一次）",
        ["已实现波动率(20) → 百分位",
         "ATR%(14) → 百分位",
         "→ 合成 0-100 百分位",
         "",
         "百分位 < 90%     → 系数 1.0",
         "90% ≤ x < 98%   → 系数 0.5",
         "百分位 ≥ 98%     → 系数 0",
         "",
         "★ 中段不压，只抓极端"],
        (238, 230, 248), (120, 92, 172))

    # 触发来源 -> 风控层（从框体左右边的空白处连）
    path(d, [(124, 610), (124, 532)])
    path(d, [ (1010, 610), (1010, 532)])
    path(d, [(1656, 610), (1656, 532)], color=(122, 132, 148), dash=True)

    divider(d, 872, W)

    # ── 执行层 ──
    d.text((54, 888), "执行层", font=F(23, True), fill=(80, 88, 102))

    box(d, 54, 930, 660, 180, "下单与平仓",
        ["手数 = 基础手数 × 压力系数 × 总系数",
         "　　　（所有系数 ≤ 1.0，只减不加）",
         "止损 = 1.5 × ATR，随单挂上",
         "平仓：信号消失 / 止损 / 风控减仓 / 休盘清空"],
        (238, 230, 248), (120, 92, 172))

    box(d, 750, 930, 560, 180, "状态持久化",
        ["state.json：持仓、权益、签字、当日盈亏",
         "程序被 kill 后重启能接上",
         "",
         "★ 每轮决策后落盘，不依赖内存"],
        (240, 240, 238), (140, 140, 136))

    path(d, [(170, 610), (170, 928)])

    divider(d, 1132, W)

    # ── 审计层 ──
    d.text((54, 1148), "审计层", font=F(23, True), fill=(80, 88, 102))

    box(d, 54, 1190, 580, 190, "每日战报",
        ["20:00 自动生成",
         "· 今日交易明细（按平仓时间归类）",
         "· 风控状态（权益 / 持仓 / 总系数）",
         "· 今日事件判断（LLM 理由）",
         "· 未来三天重要数据公布"],
        (232, 241, 252), (70, 116, 176))

    box(d, 670, 1190, 580, 190, "签字门槛",
        ["战报未滚动读完 → 签字按钮是灰的",
         "",
         "★ 签一次 = 24 小时授权",
         "★ 过期只平仓不开新仓",
         "★ 程序不中断，只是不做了"],
        (250, 238, 238), (186, 78, 78))

    box(d, 1286, 1190, 660, 190, "可追溯记录",
        ["logs/run_YYYYMMDD.log     每轮决策完整日志",
         "logs/trades.csv            每笔交易明细",
         "logs/events.csv            事件判断记录",
         "reports/战报_YYYYMMDD.txt   每日战报留档",
         "",
         "★ 出了事能倒查每一步为什么这么做"],
        (240, 240, 238), (140, 140, 136))

    path(d, [(380, 930), (380, 1188)])

    # ── 底部一句话 ──
    divider(d, H - 116, W)
    d.text((54, H - 94), "一句话", font=F(18, True), fill=MUTED)
    d.text((54, H - 62),
           "每 15 秒看一次：该平仓吗？该开仓吗？开仓前过三道拦截；休盘前全平，签字过期只平不开。",
           font=F(22, True), fill=(70, 80, 100))

    out = os.path.join(OUT, "风控框架结构图.png")
    img.save(out)
    print("saved", out)


# ══════════════════════════════════════════════════════════
def draw_strategy():
    W, H = 1780, 1200
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((54, 28), "策略实现结构", font=F(36, True), fill=INK)
    d.text((56, 76), "OsMA 双信号共振 ｜ 加权价格 MACD + 信号线 ｜ 两线同号才持仓",
           font=F(17), fill=MUTED)

    # ① 输入
    box(d, 54, 126, 330, 140, "输入 K 线",
        ["open / high / low / close", "任意周期（M5 / H1 / H4 / D1）"],
        (232, 241, 252), (70, 116, 176))

    # ② 加权价格
    box(d, 424, 126, 620, 220, "① 加权价格",
        ["body   = (open + close) / 2",
         "shadow = (high + low) / 2",
         "",
         "wp = 0.7 × body + 0.3 × shadow",
         "",
         "★ 收盘价容易被长影线带偏",
         "★ 用实体中点代表「真正争出来的价」"],
        (232, 246, 236), (66, 138, 96))
    arrow(d, 384, 196, 420, 196)

    # ③ MACD
    box(d, 1084, 126, 660, 220, "② MACD（在加权价格上算）",
        ["fast = EMA(wp, 5)    ← MT4 种子法",
         "slow = EMA(wp, 20)   ← MT4 种子法",
         "",
         "macd = fast - slow",
         "",
         "★ EMA 种子用前 N 个的 SMA",
         "★ 和 pandas.ewm() 不同，必须手动实现"],
        (232, 246, 236), (66, 138, 96))
    arrow(d, 1044, 236, 1080, 236)

    # ④ 信号线
    box(d, 54, 420, 620, 210, "③ 信号线",
        ["signal = EMA(macd, 30)",
         "osma   = macd - signal",
         "",
         "★ osma 是动量，signal 是动量的平滑",
         "★ 两者之差反映动量是否在加速"],
        (250, 240, 226), (186, 138, 62))

    # ② -> ③ 的连线（从 MACD 框下方 折到 信号线框上方）
    path(d, [(1080, 236), (1050, 236), (1050, 381), (364, 381), (364, 416)])

    # ⑤ 信号判定
    box(d, 724, 420, 700, 210, "④ 信号判定（关键）",
        ["做多：osma > 0  且  signal > 0",
         "做空：osma < 0  且  signal < 0",
         "",
         "★ 两线都在零轴同一侧才成立",
         "★ 只有一边过零轴 = 未确认，不开仓"],
        (250, 238, 238), (186, 78, 78))
    arrow(d, 674, 525, 720, 525)

    # 输出
    box(d, 1478, 420, 266, 210, "输出",
        ["wp", "macd", "signal", "osma", "", "long_ok", "short_ok"],
        (240, 240, 238), (140, 140, 136), ts=17, bs=13)
    arrow(d, 1424, 525, 1474, 525)

    # ⑥ 持仓状态机
    box(d, 54, 700, 620, 200, "⑤ 持仓状态机",
        ["空仓 + 做多条件成立 → 开多",
         "空仓 + 做空条件成立 → 开空",
         "持多 + 做多条件消失 → 平仓",
         "持空 + 做空条件消失 → 平仓",
         "",
         "★ 反向要等两个信号都翻转，不立即反手"],
        (238, 230, 248), (120, 92, 172))
    path(d, [(364, 630), (364, 697)])

    # ⑦ 止损
    box(d, 724, 700, 700, 200, "⑥ 止损",
        ["止损价 = 入场价 − 1.5 × ATR   （做多）",
         "止损价 = 入场价 + 1.5 × ATR   （做空）",
         "",
         "用 ATR 不用固定点数：不同周期波动量级差异太大",
         "",
         "★ 止损单随开仓一起挂上，程序挂了也有效"],
        (238, 230, 248), (120, 92, 172))
    arrow(d, 674, 800, 720, 800)

    # ── 两条性质 ──
    divider(d, 942, W)
    d.text((54, 960), "两条性质（strategy.py 自测里验证）", font=F(21, True), fill=INK)
    props = [
        ("互斥性", "做多与做空条件互为补集，不可能同时成立 —— 不会出现多空打架"),
        ("入场唯一性", "entry 只在条件从 false → true 的那一根触发，不重复计数"),
    ]
    y = 1000
    for name, desc in props:
        d.text((64, y), "·", font=F(17, True), fill=(66, 138, 96))
        d.text((86, y), name, font=F(17, True), fill=INK)
        tw = d.textlength(name, font=F(17, True))
        d.text((86 + tw + 14, y + 1), desc, font=F(15), fill=MUTED)
        y += 32

    divider(d, H - 108, W)
    d.text((54, H - 86), "一句话", font=F(18, True), fill=MUTED)
    d.text((54, H - 54),
           "把价格换成加权价格，在上面算 MACD；MACD 与信号线同处零轴一侧才做，任一离开就平。",
           font=F(20, True), fill=(70, 80, 100))

    out = os.path.join(OUT, "策略实现结构图.png")
    img.save(out)
    print("saved", out)


if __name__ == "__main__":
    draw_risk()
    draw_strategy()
