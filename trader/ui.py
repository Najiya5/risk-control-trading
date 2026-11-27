#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""风控程序 · 图形界面

三个页签：
  ① 状态   —— 实时看：签字、持仓、权益、指标、最近日志
  ② 签字   —— 一键签字 / 查看剩余有效期
  ③ 参数   —— 编辑 config.json（保存前会校验）

后台线程跑主循环，UI 线程只读状态，两者通过 state.json 和内存日志队列通信。
"""

import io
import os
import sys
import json
import time
import queue
import threading
import datetime
import traceback

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "osma"))
sys.path.insert(0, os.path.join(ROOT, "risk"))

import main as M  # noqa: E402

# ─────────────── 配色 ───────────────
BG = "#1e2128"
CARD = "#272b34"
FG = "#d8dde6"
MUTED = "#7d8797"
ACCENT = "#4a9eff"
OKC = "#3ecf8e"
WARNC = "#f0b429"
ERRC = "#ef5350"
INPUT_BG = "#1a1d23"


class App:
    def __init__(self, root):
        self.root = root
        self.cfg_path = os.path.join(HERE, "config.json")
        self.cfg = M.load_cfg(self.cfg_path)
        self.state_path = os.path.join(HERE, self.cfg["logging"]["state_file"])

        self.log_queue = queue.Queue()
        self.running = False
        self.thread = None
        self.stop_flag = threading.Event()

        root.title("风控程序 · XAUUSD")
        root.geometry("1000x720")
        root.configure(bg=BG)
        root.minsize(860, 620)

        self._build_style()
        self._build_header()
        self._build_tabs()

        self.refresh_loop()

    # ─────────── 样式 ───────────
    def _build_style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=BG, foreground=FG,
                     fieldbackground=INPUT_BG, borderwidth=0)
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=CARD, foreground=MUTED,
                     padding=(22, 9), borderwidth=0, font=("Microsoft YaHei UI", 10))
        st.map("TNotebook.Tab",
               background=[("selected", ACCENT)],
               foreground=[("selected", "#ffffff")])
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=CARD)
        st.configure("TLabel", background=BG, foreground=FG, font=("Microsoft YaHei UI", 10))
        st.configure("Card.TLabel", background=CARD, foreground=FG, font=("Microsoft YaHei UI", 10))
        st.configure("Muted.TLabel", background=CARD, foreground=MUTED,
                     font=("Microsoft YaHei UI", 9))
        st.configure("Big.TLabel", background=CARD, foreground=FG,
                     font=("Microsoft YaHei UI", 17, "bold"))
        st.configure("TButton", background="#333844", foreground=FG,
                     font=("Microsoft YaHei UI", 10), padding=(16, 7), borderwidth=0)
        st.map("TButton", background=[("active", "#3d4350")])
        st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                     font=("Microsoft YaHei UI", 10, "bold"), padding=(18, 9))
        st.map("Accent.TButton", background=[("active", "#3d8be6")])
        st.configure("Danger.TButton", background=ERRC, foreground="#ffffff",
                     font=("Microsoft YaHei UI", 10, "bold"), padding=(18, 9))
        st.map("Danger.TButton", background=[("active", "#d94440")])

    # ─────────── 顶栏 ───────────
    def _build_header(self):
        head = tk.Frame(self.root, bg=CARD, height=64)
        head.pack(fill="x")
        head.pack_propagate(False)

        left = tk.Frame(head, bg=CARD)
        left.pack(side="left", padx=20, pady=12)
        tk.Label(left, text="风控程序", bg=CARD, fg=FG,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        tk.Label(left, text="XAUUSD · 波动率为主 + 事件为辅",
                 bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        right = tk.Frame(head, bg=CARD)
        right.pack(side="right", padx=20)

        self.dot = tk.Canvas(right, width=10, height=10, bg=CARD, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 8))
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill=MUTED, outline="")

        self.status_lbl = tk.Label(right, text="已停止", bg=CARD, fg=MUTED,
                                   font=("Microsoft YaHei UI", 10, "bold"))
        self.status_lbl.pack(side="left", padx=(0, 18))

        self.btn_start = ttk.Button(right, text="启动", style="Accent.TButton",
                                    command=self.on_start)
        self.btn_start.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(right, text="停止", style="Danger.TButton",
                                   command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)

    # ─────────── 页签 ───────────
    def _build_tabs(self):
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(12, 6))

        self.tab_status = ttk.Frame(self.nb)
        self.tab_approve = ttk.Frame(self.nb)
        self.tab_config = ttk.Frame(self.nb)
        self.nb.add(self.tab_status, text="  状态  ")
        self.nb.add(self.tab_approve, text="  签字  ")
        self.nb.add(self.tab_config, text="  参数  ")

        self._build_status_tab()
        self._build_approve_tab()
        self._build_config_tab()

    # ═══════════ ① 状态 ═══════════
    def _card(self, parent, title):
        wrap = tk.Frame(parent, bg=CARD)
        tk.Label(wrap, text=title, bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=14, pady=(10, 0))
        body = tk.Frame(wrap, bg=CARD)
        body.pack(fill="both", expand=True, padx=14, pady=(4, 12))
        return wrap, body

    def _build_status_tab(self):
        pad = tk.Frame(self.tab_status, bg=BG)
        pad.pack(fill="both", expand=True, padx=6, pady=6)

        # 上排：四个指标卡
        row1 = tk.Frame(pad, bg=BG)
        row1.pack(fill="x")

        self.k_approve = self._stat_card(row1, "签字状态")
        self.k_equity = self._stat_card(row1, "账户权益")
        self.k_position = self._stat_card(row1, "当前持仓")
        self.k_atrp = self._stat_card(row1, "ATRP / 阈值")
        self.k_source = self._stat_card(row1, "数据源")

        for c in (self.k_approve, self.k_equity, self.k_position, self.k_atrp, self.k_source):
            c["wrap"].pack(side="left", fill="both", expand=True, padx=6, pady=6)

        # 中排：指标详情
        row2 = tk.Frame(pad, bg=BG)
        row2.pack(fill="x")
        wrap, body = self._card(row2, "指标")
        wrap.pack(fill="x", padx=6, pady=6)
        self.ind_lbl = tk.Label(body, text="等待数据…", bg=CARD, fg=FG, justify="left",
                                 font=("Consolas", 10))
        self.ind_lbl.pack(anchor="w")

        # 日志
        row3 = tk.Frame(pad, bg=BG)
        row3.pack(fill="both", expand=True)
        wrap, body = self._card(row3, "运行日志")
        wrap.pack(fill="both", expand=True, padx=6, pady=6)
        self.log = scrolledtext.ScrolledText(
            body, bg=INPUT_BG, fg=MUTED, insertbackground=FG,
            font=("Consolas", 9), relief="flat", height=10, wrap="none")
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("ok", foreground=OKC)
        self.log.tag_config("warn", foreground=WARNC)
        self.log.tag_config("err", foreground=ERRC)

    def _stat_card(self, parent, title):
        wrap, body = self._card(parent, title)
        val = tk.Label(body, text="—", bg=CARD, fg=FG,
                       font=("Microsoft YaHei UI", 16, "bold"))
        val.pack(anchor="w")
        return {"wrap": wrap, "val": val}

    # ═══════════ ② 签字 ═══════════
    def _build_approve_tab(self):
        pad = tk.Frame(self.tab_approve, bg=BG)
        pad.pack(fill="both", expand=True, padx=6, pady=6)

        # ── 上方：签字状态 ──
        wrap, body = self._card(pad, "当前签字状态")
        wrap.pack(fill="x", padx=6, pady=(6, 3))
        self.ap_status = tk.Label(body, text="读取中…", bg=CARD, fg=FG,
                                   font=("Microsoft YaHei UI", 14, "bold"))
        self.ap_status.pack(anchor="w", pady=(2, 4))
        self.ap_detail = tk.Label(body, text="", bg=CARD, fg=MUTED, justify="left",
                                   font=("Microsoft YaHei UI", 9))
        self.ap_detail.pack(anchor="w")

        # ── 中间：每日战报 ──
        wrap2, body2 = self._card(pad, "每日战报（签字前必读）")
        wrap2.pack(fill="both", expand=True, padx=6, pady=3)

        self.report_text = scrolledtext.ScrolledText(
            body2, bg=INPUT_BG, fg=MUTED, insertbackground=FG,
            font=("Consolas", 9), relief="flat", wrap="word", height=18)
        self.report_text.pack(fill="both", expand=True)
        self.report_text.insert("1.0", "（等待生成…）")
        self.report_text.config(state="disabled")

        # 滚动到底部就标记已读
        self.report_text.bind("<Configure>", lambda e: self._check_report_read())
        self.report_text.bind("<MouseWheel>", lambda e: self.root.after(120, self._check_report_read))
        self.report_text.bind("<KeyRelease>", lambda e: self._check_report_read())

        bar2 = tk.Frame(body2, bg=CARD)
        bar2.pack(fill="x", pady=(6, 0))
        ttk.Button(bar2, text="重新生成", command=self.on_regen_report).pack(side="left")
        self.report_msg = tk.Label(bar2, text="", bg=CARD, fg=MUTED,
                                    font=("Microsoft YaHei UI", 9))
        self.report_msg.pack(side="left", padx=10)

        # ── 下方：签字操作 ──
        wrap3, body3 = self._card(pad, "签字")
        wrap3.pack(fill="x", padx=6, pady=(3, 6))

        row = tk.Frame(body3, bg=CARD)
        row.pack(anchor="w", pady=4)

        self.hours_var = tk.StringVar(value="24")
        self.btn_approve = ttk.Button(row, text="签字", style="Accent.TButton",
                                       command=self.on_approve, state="disabled")
        self.btn_approve.pack(side="left")
        tk.Label(row, text="有效期", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(18, 6))
        ent = tk.Entry(row, textvariable=self.hours_var, width=6, bg=INPUT_BG, fg=FG,
                       insertbackground=FG, relief="flat", font=("Microsoft YaHei UI", 10))
        ent.pack(side="left", ipady=4)
        tk.Label(row, text="小时", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=6)

        self.ap_hint = tk.Label(body3, text="", bg=CARD, fg=WARNC,
                                 font=("Microsoft YaHei UI", 9))
        self.ap_hint.pack(anchor="w", pady=(8, 0))

        self._report_date = None
        self._report_read = False

    # ── 载入今天的战报 ──
    def _load_report(self):
        import datetime
        import daily_report
        date_str = datetime.date.today().strftime("%Y-%m-%d")
        fname = f"战报_{date_str.replace('-', '')}.txt"
        path = os.path.join(HERE, self.cfg["logging"]["daily_dir"], fname)

        if not os.path.exists(path):
            self.report_text.config(state="normal")
            self.report_text.delete("1.0", "end")
            self.report_text.insert("1.0",
                f"今日战报尚未生成。\n\n"
                f"战报每天 20:00 自动生成，也可以在下方点「重新生成」。\n"
                f"文件路径：{path}")
            self.report_text.config(state="disabled")
            self.report_msg.config(text="战报未生成", fg=WARNC)
            self._report_read = False
            self._report_date = None
            self._update_approve_button()
            return

        try:
            with io.open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            text = f"读取失败: {e}"

        # 只有日期变了才重新载入（避免刷新时打断滚动位置）
        if self._report_date != date_str:
            self.report_text.config(state="normal")
            self.report_text.delete("1.0", "end")
            self.report_text.insert("1.0", text)
            self.report_text.config(state="disabled")
            self._report_date = date_str

            # 从 state 恢复「已读」标记
            try:
                st = M.load_state(self.state_path, self.cfg)
                if st.get("_report_read_date") == date_str:
                    self._report_read = True
            except Exception:
                pass

        self._update_approve_button()

    # ── 滚动到末尾 → 标记已读 ──
    def _check_report_read(self):
        if self._report_read or self._report_date is None:
            return
        try:
            # 看是否能看到最后一行
            last = self.report_text.index("end-1c")
            bbox = self.report_text.bbox(last)
            if bbox is not None:      # 最后一行在可视区域内
                self._mark_report_read()
            elif self.report_text.yview()[1] >= 0.999:
                self._mark_report_read()
        except Exception:
            pass

    def _mark_report_read(self):
        if self._report_read:
            return
        self._report_read = True
        try:
            st = M.load_state(self.state_path, self.cfg)
            st = M.load_state(self.state_path, self.cfg)
            st["_report_read_date"] = self._report_date
            tmp = self.state_path + ".tmp"
            with io.open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, self.state_path)
        except Exception:
            pass
        self.report_msg.config(text="✓ 已读完战报", fg=OKC)
        self._update_approve_button()

    def _update_approve_button(self):
        if self._report_read:
            self.btn_approve.config(state="normal")
            self.ap_hint.config(text="", fg=MUTED)
        else:
            self.btn_approve.config(state="disabled")
            self.ap_hint.config(
                text="⚠ 必须滚动读完上方战报才能签字",
                fg=WARNC)

    def on_regen_report(self):
        try:
            import daily_report
            st = M.load_state(self.state_path, self.cfg)
            path = daily_report.save_report(self.cfg, st)
            self._report_date = None      # 强制重新载入
            self._report_read = False
            self._load_report()
            self.report_msg.config(text=f"✓ 已重新生成：{os.path.basename(path)}", fg=OKC)
        except Exception as e:
            self.report_msg.config(text=f"生成失败: {e}", fg=ERRC)

    # ═══════════ ③ 参数 ═══════════
    def _build_config_tab(self):
        # 外层：可滚动的画布（参数项多，窗口可能放不下）
        outer = tk.Frame(self.tab_config, bg=BG)
        outer.pack(fill="both", expand=True, padx=6, pady=6)

        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.cfg_frame = tk.Frame(canvas, bg=BG)

        self.cfg_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.cfg_frame, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # 滚轮
        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)

        # 输入控件字典：{路径: (变量, 控件)}
        self.vars = {}

        self._add_group("基础", [
            ("symbol", "交易品种", "text",
             "MT5 里的品种名，一般是 XAUUSD"),
            ("timeframe", "K线周期", "combo",
             "策略运行的周期。M5 / M15 / H1 / H4 / D1"),
        ])

        self._add_group("账户与下单", [
            ("account.base_lot", "基础手数", "float",
             "策略的标准下注量。风控只会往下压，永远不会超过这个数。XAUUSD 1手=100盎司"),
            ("account.contract_size", "合约乘数", "float",
             "1 手对应的单位数。XAUUSD 固定 100，不要改"),
            ("account.initial_equity", "初始权益", "float",
             "纸面模式的起始资金。MT5 模式会用真实账户余额"),
            ("broker.mode", "下单模式", "combo_mode",
             "paper = 只记录不下单（安全）｜mt5 = 真实下单到 MT5 模拟账户"),
        ])

        self._add_group("策略参数（OsMA 指标）", [
            ("strategy.fast_ema", "快线周期", "int",
             "MACD 快线。越小越灵敏，信号越多"),
            ("strategy.slow_ema", "慢线周期", "int",
             "MACD 慢线。建议是快线的 3~5 倍"),
            ("strategy.signal_ema", "信号线周期", "int",
             "MACD 的 EMA 平滑周期。越大信号越滞后但越稳"),
            ("strategy.weight_body", "实体权重", "float",
             "加权价格里 K 线实体的占比，0~1"),
            ("strategy.weight_shadow", "影线权重", "float",
             "加权价格里上下影线的占比。两个权重会自动归一化"),
        ])

        self._add_group("波动率风控（ATRP）", [
            ("vol_risk.atr_period_1", "ATR 短周期", "int",
             "ATRP 指标里第一个 ATR 的周期"),
            ("vol_risk.atr_period_2", "ATR 长周期", "int",
             "ATRP 指标里第二个 ATR 的周期"),
            ("vol_risk.ma_period", "阈值均线周期", "int",
             "ATRP 的移动平均周期，用来做阈值基准"),
            ("vol_risk.atrp_factor", "阈值倍数 ★", "float",
             "ATRP 超过 均线×这个倍数 就不下单。硬下限 1.4（低于此值程序会强制拉到 1.4）"),
            ("vol_risk.weight_vol", "波动率权重", "float",
             "标的仓位里波动率压力占的权重。建议 0.9"),
        ])

        self._add_group("总分析师（每晚一次）", [
            ("daily_analyst.lookback_days", "历史回看天数", "int",
             "算百分位用的历史窗口。250 约等于一年"),
            ("daily_analyst.vol_window", "波动率窗口", "int",
             "已实现波动率的计算窗口（日）"),
            ("daily_analyst.atr_window", "ATR 窗口", "int",
             "ATR 百分比的计算窗口（日）"),
            ("daily_analyst.pct_gate", "流动性门槛", "float",
             "流动性百分位超过这个值，当天不开新仓。默认 98"),
        ])

        self._add_group("订单风控 · 波动率规则（权重 0.5）", [
            ("order_risk.weight_vol", "波动率权重", "float",
             "两条减仓规则各占一半，这是波动率那半的权重。默认 0.5"),
            ("order_risk.cut_ratio", "每次平仓比例", "float",
             "触发时平掉原始手数的多少。默认 0.5（平一半）"),
        ])

        self._add_group("订单风控 · 事件规则（权重 0.5）", [
            ("order_risk.weight_event", "事件权重", "float",
             "事件那半的权重，默认 0.5。两条规则地位平等"),
            ("order_risk.event_threshold", "事件严重度门槛", "float",
             "多个 LLM 平均 severity 达到这个值 → 平一半。默认 0.7"),
            ("event_layer.enabled", "启用事件判断", "bool",
             "关掉的话只看波动率，不看新闻"),
            ("event_layer.only_important", "只看重要快讯", "bool",
             "金十标记为 important=1 的才送模型判断"),
            ("event_layer.poll_seconds", "轮询间隔（秒）", "int",
             "多久查一次金十。建议 300（5分钟）"),
            ("event_layer.max_events_per_check", "单次最多判断条数", "int",
             "一次轮询最多送几条给模型，控制成本"),
        ])

        self._add_group("时间安排", [
            ("schedule.flat_before_newyork_close_minutes", "休盘前平仓（分钟）", "int",
             "纽约收盘前多少分钟平掉所有仓。默认 5"),
        ])

        self._add_group("签字与风控", [
            ("approval.valid_hours", "签字有效期（小时）", "float",
             "签字后多久内可开新仓。过期只平仓不开新仓，程序继续跑"),
        ])

        # ── 按钮栏 ──
        bar = tk.Frame(self.cfg_frame, bg=BG)
        bar.pack(fill="x", pady=(14, 8), padx=10)
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=self.on_save_config).pack(side="left")
        ttk.Button(bar, text="放弃修改", command=self._load_config_into_editor).pack(side="left", padx=8)
        self.cfg_msg = tk.Label(bar, text="", bg=BG, fg=MUTED,
                                 font=("Microsoft YaHei UI", 9))
        self.cfg_msg.pack(side="left", padx=12)

        tk.Label(self.cfg_frame,
                 text="★ 标记的项有硬约束。所有数字都是占位值，按模拟盘表现再调。",
                 bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 9)
                 ).pack(anchor="w", padx=10, pady=(0, 16))

        self._load_config_into_editor()

    # ── 加一组参数 ──
    def _add_group(self, title, items):
        wrap = tk.Frame(self.cfg_frame, bg=CARD)
        wrap.pack(fill="x", padx=10, pady=(0, 10))

        head = tk.Frame(wrap, bg=CARD)
        head.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(head, text=title, bg=CARD, fg=ACCENT,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")

        for path, label, kind, comment in items:
            row = tk.Frame(wrap, bg=CARD)
            row.pack(fill="x", padx=16, pady=(6, 0))

            # 左：标签
            lab = tk.Label(row, text=label, bg=CARD, fg=FG, width=16, anchor="w",
                           font=("Microsoft YaHei UI", 10))
            lab.pack(side="left")

            # 中：控件
            var = tk.StringVar()
            self.vars[path] = (var, kind)
            if kind == "combo":
                w = ttk.Combobox(row, textvariable=var, width=10, state="readonly",
                                 values=["M1", "M5", "M15", "M30", "H1", "H4", "D1"],
                                 font=("Microsoft YaHei UI", 10))
            elif kind == "combo_mode":
                w = ttk.Combobox(row, textvariable=var, width=10, state="readonly",
                                 values=["paper", "mt5"],
                                 font=("Microsoft YaHei UI", 10))
            elif kind == "bool":
                w = ttk.Combobox(row, textvariable=var, width=10, state="readonly",
                                 values=["true", "false"],
                                 font=("Microsoft YaHei UI", 10))
            else:
                w = tk.Entry(row, textvariable=var, width=14, bg=INPUT_BG, fg=FG,
                             insertbackground=FG, relief="flat",
                             font=("Consolas", 10))
            w.pack(side="left", ipady=3)

            # 右：注释
            tk.Label(wrap, text=comment, bg=CARD, fg=MUTED, anchor="w",
                     justify="left", wraplength=820,
                     font=("Microsoft YaHei UI", 9)).pack(fill="x", padx=16, pady=(2, 0))

    # ── 从 config 载入到控件 ──
    def _get_path(self, obj, path):
        cur = obj
        for k in path.split("."):
            if not isinstance(cur, dict) or k not in cur:
                return None
            cur = cur[k]
        return cur

    def _set_path(self, obj, path, value):
        keys = path.split(".")
        cur = obj
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = value

    def _load_config_into_editor(self):
        try:
            self.cfg = M.load_cfg(self.cfg_path)
        except Exception as e:
            self.cfg_msg.config(text=f"读取失败: {e}", fg=ERRC)
            return
        for path, (var, kind) in self.vars.items():
            v = self._get_path(self.cfg, path)
            if v is None:
                continue
            if isinstance(v, bool):
                var.set("true" if v else "false")
            elif isinstance(v, float):
                # 整数值显示成整数，避免出现 1e+06
                if v == int(v) and abs(v) < 1e15:
                    var.set(str(int(v)))
                else:
                    var.set(f"{v:g}")
            else:
                var.set(str(v))
        self.cfg_msg.config(text="已载入当前配置", fg=MUTED)

    # ── 保存 ──
    def on_save_config(self):
        cfg = json.loads(json.dumps(self.cfg))   # 深拷贝

        errors = []
        for path, (var, kind) in self.vars.items():
            raw = var.get().strip()
            try:
                if kind == "int":
                    cfg_v = int(float(raw))
                elif kind == "float":
                    cfg_v = float(raw)
                elif kind == "bool":
                    cfg_v = (raw.lower() == "true")
                else:
                    cfg_v = raw
            except ValueError:
                errors.append(f"{path}: 「{raw}」不是有效数字")
                continue
            self._set_path(cfg, path, cfg_v)

        # 硬约束校验
        factor = self._get_path(cfg, "vol_risk.atrp_factor")
        if factor is not None and factor < 1.4:
            errors.append("atrp_factor 不得低于 1.4（这是硬下限，低于会被强制拉回）")

        orv = self._get_path(cfg, "order_risk.weight_vol")
        ore = self._get_path(cfg, "order_risk.weight_event")
        if orv is not None and ore is not None and abs(orv - 0.5) > 0.001:
            errors.append(f"订单风控的两条规则权重应该都是 0.5（当前 {orv}/{ore}）")

        base_lot = self._get_path(cfg, "account.base_lot")
        if base_lot is not None and base_lot < 0.01:
            errors.append("基础手数不能小于 0.01")

        if errors:
            self.cfg_msg.config(text=" ｜ ".join(errors[:2]), fg=ERRC)
            return

        try:
            bak = self.cfg_path + ".bak"
            with io.open(self.cfg_path, "r", encoding="utf-8-sig") as f:
                old = f.read()
            with io.open(bak, "w", encoding="utf-8") as f:
                f.write(old)
            with io.open(self.cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.cfg = cfg
            self.state_path = os.path.join(HERE, cfg["logging"]["state_file"])
            self.cfg_msg.config(text="✓ 已保存（原配置备份为 .bak），重启程序生效", fg=OKC)
        except Exception as e:
            self.cfg_msg.config(text=f"保存失败: {e}", fg=ERRC)

    # ═══════════ 启停 ═══════════
    def on_start(self):
        if self.running:
            return
        self.stop_flag.clear()
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._set_status("运行中", OKC)

    def on_stop(self):
        if not self.running:
            return
        self.stop_flag.set()
        self._set_status("停止中…", WARNC)

    def _worker(self):
        try:
            logfile = os.path.join(HERE, self.cfg["logging"]["log_dir"],
                                   f"run_{datetime.date.today():%Y%m%d}.log")
            os.makedirs(os.path.dirname(logfile), exist_ok=True)
            st = M.load_state(self.state_path, self.cfg)
            from broker import make_broker
            broker = make_broker(self.cfg, HERE)

            # 把主循环的日志接到 UI 面板上
            M.LOG_SINK = lambda m: self._push_log(m)

            self._push_log("=" * 50)
            self._push_log(f"启动 | {self.cfg['symbol']} {self.cfg['timeframe']} | "
                           f"{self.cfg['broker']['mode']}")
            self._push_log(f"签字: {'有效' if M.is_approved(st, self.cfg) else '未签字/已过期'}")

            while not self.stop_flag.is_set():
                try:
                    M.run_once(self.cfg, st, broker, logfile)
                except Exception as ex:
                    self._push_log(f"[错误] {type(ex).__name__}: {ex}", "err")
                    self._push_log(traceback.format_exc()[-500:], "err")
                for _ in range(15):
                    if self.stop_flag.is_set():
                        break
                    time.sleep(1)
            M.save_state(self.state_path, st)
            self._push_log("已停止")
            M.LOG_SINK = None
        except Exception as ex:
            self._push_log(f"[致命] {type(ex).__name__}: {ex}", "err")
        finally:
            self.running = False
            self.root.after(0, lambda: (
                self.btn_start.config(state="normal"),
                self.btn_stop.config(state="disabled"),
                self._set_status("已停止", MUTED),
            ))

    def _push_log(self, msg, tag=None):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_queue.put((f"[{ts}] {msg}", tag))

    def _set_status(self, text, color):
        self.status_lbl.config(text=text, fg=color)
        self.dot.itemconfig(self.dot_id, fill=color)

    # ═══════════ 刷新 ═══════════
    def refresh_loop(self):
        # 日志
        try:
            while True:
                line, tag = self.log_queue.get_nowait()
                self.log.insert("end", line + "\n", tag or ())
                self.log.see("end")
        except queue.Empty:
            pass

        # 状态文件
        try:
            if os.path.exists(self.state_path):
                st = M.load_state(self.state_path, self.cfg)
                self._update_status_cards(st)
                self._update_approve_tab(st)
        except Exception:
            pass

        # 数据源
        try:
            md = M.get_market_data(self.cfg)
            stt = md.status()
            ok = bool(stt.get("ok"))
            short = {"csv": "CSV", "xaus": "XAUS", "mt5": "MT5"}.get(stt.get("source"), "?")
            self.k_source["val"].config(
                text=("\u2713 " if ok else "\u2717 ") + short,
                fg=OKC if ok else ERRC)
            self.src_detail = stt.get("msg", "")
        except Exception as e:
            self.k_source["val"].config(text="\u2717 异常", fg=ERRC)
            self.src_detail = str(e)

        # 指标
        try:
            ind = M.compute_indicators(self.cfg, self.cfg["timeframe"])
            if ind is not None:
                bar = ind.iloc[-1]
                thr = bar["atrp_ma"] * max(self.cfg["vol_risk"]["atrp_factor"], 1.4)
                over = bar["atrp"] > thr
                self.k_atrp["val"].config(
                    text=f"{bar['atrp']:.3f}%", fg=ERRC if over else OKC)
                long_ok = bar["osma"] > 0 and bar["signal"] > 0
                short_ok = bar["osma"] < 0 and bar["signal"] < 0
                sig = "多" if long_ok else ("空" if short_ok else "无")
                self.ind_lbl.config(text=(
                    f"数据源     {getattr(self, 'src_detail', '')}\n"
                    f"最新K线  {ind.index[-1]}\n"
                    f"收盘价    {bar['close']:.2f}\n"
                    f"ATR        {bar['atr']:.2f}\n"
                    f"ATRP       {bar['atrp']:.3f}%   "
                    f"阈值(MA×{self.cfg['vol_risk']['atrp_factor']}) {thr:.3f}%   "
                    f"{'✗ 超阈值会拦截' if over else '✓ 未超阈值'}\n"
                    f"OsMA       {bar['osma']:.4f}\n"
                    f"signal     {bar['signal']:.4f}\n"
                    f"当前信号   {sig}"))
        except Exception as e:
            self.ind_lbl.config(text=f"指标计算失败: {e}")

        # 战报：每 15 秒检查一次（有新战报就载入）
        try:
            self._report_tick = getattr(self, "_report_tick", 0) + 1
            if self._report_tick % 10 == 1:
                self._load_report()
        except Exception:
            pass

        self.root.after(1500, self.refresh_loop)

    def _update_status_cards(self, st):
        approved = M.is_approved(st, self.cfg)
        self.k_approve["val"].config(text="✓ 有效" if approved else "✗ 过期",
                                      fg=OKC if approved else ERRC)
        self.k_equity["val"].config(text=f"{st.get('equity', 0):,.0f}")

        pos = st.get("position")
        if pos:
            side = "多" if pos["side"] == 1 else "空"
            self.k_position["val"].config(text=f"{side} {pos['lots']:.2f} 手")
        else:
            self.k_position["val"].config(text="空仓", fg=MUTED)

    def _update_approve_tab(self, st):
        now = datetime.datetime.now(datetime.UTC)
        au = st.get("approved_until")
        if not au:
            self.ap_status.config(text="✗ 从未签字", fg=ERRC)
            self.ap_detail.config(text="没有签字，程序不会开新仓。")
            return
        try:
            until = datetime.datetime.fromisoformat(au)
            if until.tzinfo is None:
                until = until.replace(tzinfo=datetime.UTC)
        except Exception:
            self.ap_status.config(text="签字记录损坏", fg=ERRC)
            return

        local_until = until.astimezone()
        if now < until:
            left = (until - now).total_seconds() / 3600
            self.ap_status.config(text=f"✓ 有效 · 还剩 {left:.1f} 小时", fg=OKC)
        else:
            self.ap_status.config(text="✗ 已过期", fg=ERRC)
        self.ap_detail.config(
            text=f"到期时间  {local_until:%Y-%m-%d %H:%M:%S}（本地时间）\n"
                 f"UTC       {until:%Y-%m-%dT%H:%M:%SZ}")

    def on_approve(self):
        if not self._report_read:
            messagebox.showwarning("未读战报", "请先滚动读完今日战报再签字。")
            return
        try:
            hours = float(self.hours_var.get())
        except ValueError:
            messagebox.showerror("错误", "小时数必须是数字")
            return
        if hours <= 0:
            messagebox.showerror("错误", "小时数必须大于 0")
            return
        now = datetime.datetime.now(datetime.UTC)
        until = now + datetime.timedelta(hours=hours)
        # 先读磁盘最新状态，避免覆盖主循环刚写进去的东西
        st = M.load_state(self.state_path, self.cfg)
        st["approved_until"] = until.isoformat()
        st["approved_at"] = now.isoformat()
        # 不走 M.save_state（它会先同步磁盘字段，把我们刚设的值冲掉）
        tmp = self.state_path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, self.state_path)
        self._push_log(f"[签字] 有效期至 {until.astimezone():%Y-%m-%d %H:%M}", "ok")
        self._update_approve_tab(st)


def main():
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.2)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()


