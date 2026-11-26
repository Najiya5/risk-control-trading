#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""风控程序逻辑图（代码执行流程）"""

import os
from PIL import Image, ImageDraw, ImageFont

W, H = 2200, 1900
BG = (250, 250, 248)
INK = (32, 40, 54)
MUTED = (120, 130, 146)

C_START = (226, 238, 252), (62, 106, 176)
C_LOOP = (250, 240, 224), (186, 138, 62)
C_CHECK = (232, 246, 232), (66, 138, 92)
C_DECIDE = (246, 228, 228), (186, 80, 80)
C_ACT = (238, 230, 248), (120, 92, 172)
C_EXIT = (240, 240, 240), (140, 140, 140)
C_NOTE = (252, 248, 236), (198, 168, 96)


def font(size, bold=False):
    ps = [r"C:\Windows\Fonts\msyhbd.ttc"] if bold else []
    ps += [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]
    for p in ps:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)


def box(x, y, w, h, colors, title, lines, ts=20, bs=15, lh=6):
    fill, edge = colors
    d.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=fill, outline=edge, width=2)
    d.text((x + 13, y + 8), title, font=font(ts, True), fill=INK)
    yy = y + 8 + ts + 9
    for ln in lines:
        if yy + bs > y + h - 4:
            break
        b = ln.startswith("★")
        d.text((x + 13, yy), ln, font=font(bs, b), fill=INK)
        yy += bs + lh


def arrow(x1, y1, x2, y2, color=(120, 130, 146), width=2, dash=False):
    import math
    if dash:
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L:
            n = max(2, int(L / 12))
            for k in range(n):
                if k % 2:
                    continue
                d.line([x1 + dx * k / n, y1 + dy * k / n,
                        x1 + dx * (k + 1) / n, y1 + dy * (k + 1) / n],
                       fill=color, width=width)
    else:
        d.line([x1, y1, x2, y2], fill=color, width=width)
    a = math.atan2(y2 - y1, x2 - x1)
    for b in (a + 2.55, a - 2.55):
        d.line([x2, y2, x2 + 11 * math.cos(b), y2 + 11 * math.sin(b)],
               fill=color, width=width)


def label(x, y, t, c, s=14):
    d.text((x, y), t, font=font(s, True), fill=c)


# ══ 标题 ══
d.text((60, 22), "风控程序 · 执行逻辑", font=font(42, True), fill=INK)
d.text((62, 78), "run_once() 每 15 秒跑一轮，下面是一条完整路径", font=font(20), fill=MUTED)

# ══ 启动 ══
box(60, 130, 420, 150, C_START, "启动", [
    "读取 config.json",
    "初始化行情源（MT5 / xaus / csv）",
    "加载 state.json（持仓、权益、签字）",
    "★ 签字有效期 24 小时",
], ts=21, bs=15)

arrow(480, 205, 540, 205)

# ══ 主循环 ══
box(544, 130, 340, 150, C_LOOP, "主循环（每 15 秒）", [
    "run_once() 被调用",
    "",
    "顺序执行下面四步",
], ts=21, bs=15)

# ══ 四步 ══
# 步骤 1
box(60, 330, 470, 175, C_CHECK, "① 日内平仓检查", [
    "现在是否在「纽约休盘前 5 分钟」？",
    "",
    "夏令时 21:00 UTC / 冬令时 22:00 UTC",
    "→ 是：平掉所有持仓 + 撤销挂单",
    "→ 每天只做一次（flat_done_for 标记）",
], ts=21, bs=15)

# 步骤 2
box(570, 330, 470, 175, C_CHECK, "② 新交易日重置", [
    "日期变了吗？",
    "",
    "→ 是：daily_pnl = 0",
    "→ 检查签字是否还有效",
    "  （过期 = 不开新仓，但继续跑）",
], ts=21, bs=15)

# 步骤 3
box(1080, 330, 500, 175, C_DECIDE, "③ 信号与平仓", [
    "长头 = OsMA>0 且 signal>0",
    "空头 = OsMA<0 且 signal<0",
    "",
    "已有持仓 → 信号消失就平仓",
    "空仓 → 看能不能开新仓",
], ts=21, bs=15)

# 步骤 4
box(60, 545, 690, 260, C_DECIDE, "④ 开仓前：三道拦截（任一触发就不开）", [
    "拦截 1：签字",
    "  未签字 / 超过 24 小时 → 不开",
    "",
    "拦截 2：ATRP 波动率",
    "  ATRP > MA(20) × 1.4 → 不开",
    "  ★ 1.4 是硬下限，不许调低",
    "",
    "拦截 3：总系数",
    "  昨天算出的总系数 < 0.99 → 不开",
], ts=21, bs=15)

# 步骤 5
box(790, 545, 620, 260, C_ACT, "⑤ 通过拦截：算仓位", [
    "波动压力 = vol_pressure(ATRP 超阈值幅度)",
    "事件压力 = 金十事件 × 多模型判断",
    "",
    "合成压力 = 0.9 × 波动 + 0.1 × 事件",
    "仓位系数 = 1 - 合成压力",
    "",
    "手数 = floor(基础手数 × 系数 / 0.01) × 0.01",
    "★ 上限 = 基础手数（只减不加）",
    "★ 不足 0.01 手 → 不开",
], ts=21, bs=15)

# 步骤 6
box(1450, 545, 690, 260, C_ACT, "⑥ 下单 / 平仓", [
    "开仓：",
    "  方向 = 多头 / 空头",
    "  手数 = 上一步算出来",
    "  止损 = 1.5 × ATR",
    "",
    "平仓（信号消失）：",
    "  按当前价平掉，盈亏计入权益",
    "",
    "★ 写 trades.csv + 更新 state.json",
], ts=21, bs=15)

# ══ 事件层（独立循环）══
box(60, 850, 640, 230, C_NOTE, "事件层（每 5 分钟，独立于主循环）", [
    "拉金十快讯 → 过滤 important=1",
    "",
    "→ 各家模型独立判断（同一 schema）",
    "  impact / severity / horizon / reason",
    "",
    "→ 去极值取平均 → 分歧度",
    "",
    "★ 分歧大 → 事件压力 = 1（等同归零）",
    "★ 全挂 → 压力 = 0（降级，不中断）",
], ts=21, bs=15)

# ══ 总分析师（每晚一次）══
box(740, 850, 640, 230, C_NOTE, "总分析师（每晚收盘后一次）", [
    "日线数据：",
    "  已实现波动率（20日）→ 百分位",
    "  ATR 百分比（14日）→ 百分位",
    "",
    "→ 合成流动性百分位（0–100）",
    "",
    "百分位 > 98 → 总系数 = 0（明天不开新仓）",
    "百分位 ≤ 98 → 总系数 = 1",
    "",
    "★ 中段完全不压，只在极端时出手",
], ts=21, bs=15)

# ══ 数据写入 ══
box(1420, 850, 720, 230, C_EXIT, "输出：全部落盘（可审计）", [
    "state.json     当前持仓、权益、签字、今日盈亏",
    "logs/run_*.log 每轮决策的完整日志",
    "logs/trades.csv 每笔交易（开平时间、手数、价格、盈亏）",
    "reports/       待审计的日报",
    "",
    "★ 程序被 kill 后重启，从 state.json 接上",
    "★ 人在审计报告上签字，规则才允许改",
], ts=21, bs=15)

# ══ 连线 ══
arrow(884, 280, 884, 326)          # 主循环 -> 步骤
arrow(295, 505, 295, 541)          # 步骤1 -> 步骤4 区
arrow(805, 505, 900, 541)
arrow(1330, 505, 1200, 541)
arrow(690, 675, 786, 675)
arrow(1414, 675, 1446, 675)
arrow(60, 805, 60, 846, dash=True)
arrow(1080, 805, 1080, 846, dash=True)
arrow(1080, 1080, 1080, 1120, dash=True)

# 反馈回路
arrow(1780, 1080, 1780, 1130, dash=True)
arrow(1780, 1130, 240, 1130, dash=True)
arrow(240, 1130, 240, 810, dash=True)

d.text((1200, 1160), "每轮循环读取 state.json → 决策 → 写回 state.json",
       font=font(17, True), fill=MUTED)

# ══ 底部说明 ══
d.line([(60, 1210), (W - 60, 1210)], fill=(222, 222, 216), width=2)

y = 1245
d.text((60, y), "三条硬约束", font=font(24, True), fill=INK)
y += 46
rules = [
    ("签字 24 小时", "过期只平仓不开新仓，程序继续跑 —— 不会中断，只是不做了"),
    ("休盘前 5 分钟全平", "平持仓 + 撤挂单 —— 避免隔夜跳空，也让「最差一天」成立"),
    ("只减不加", "所有系数、压力、手数上限都是 1.0，永不越过基准"),
]
for name, desc in rules:
    d.text((70, y), "·", font=font(18, True), fill=C_DECIDE[1])
    d.text((92, y), name, font=font(18, True), fill=INK)
    wpx = d.textlength(name, font=font(18, True))
    d.text((92 + wpx + 16, y + 1), desc, font=font(17), fill=MUTED)
    y += 34

y += 16
d.text((60, y), "降级行为", font=font(24, True), fill=INK)
y += 46
fallbacks = [
    ("LLM 全挂", "事件压力按 0，主循环照常跑"),
    ("金十接口失败", "同上，记日志"),
    ("MT5 断连", "本轮跳过，下一轮重试"),
    ("数据不足", "跳过这一轮，不报错退出"),
]
for name, desc in fallbacks:
    d.text((70, y), "·", font=font(18, True), fill=C_NOTE[1])
    d.text((92, y), name, font=font(18, True), fill=INK)
    wpx = d.textlength(name, font=font(18, True))
    d.text((92 + wpx + 16, y + 1), desc, font=font(17), fill=MUTED)
    y += 34

# ══ 一句话 ══
d.line([(60, H - 120), (W - 60, H - 120)], fill=(222, 222, 216), width=2)
d.text((60, H - 98), "一句话", font=font(20, True), fill=MUTED)
d.text((60, H - 62),
       "每 15 秒看一眼：该平仓吗？该开仓吗？开仓前过三道拦截；休盘前全平，签字过期只平不开。",
       font=font(23, True), fill=(70, 80, 100))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "程序逻辑图.png")
img.save(out)
print("saved", out, img.size)
