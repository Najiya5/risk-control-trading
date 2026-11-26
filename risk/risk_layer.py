#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""风控层 v1 —— 总分析师 + 仓位管理

设计依据：risk-framework-v3.md

结构：
  ① 总分析师：每天收盘后（纽约收盘）算一次流动性百分位 → 总系数
  ② 风控层：总预算 × 总系数 → 按止损距离算单笔仓位 → 归零线一票否决

数据限制（重要）：
  伦敦金日线只能拿到价格类指标。文档里的四个分位中，
  VIX / 利率这两个拿不到，本版用两个纯价格代理替代：
    - 已实现波动率分位   (20日)
    - ATR 百分比分位     (14日)
  这两个都只反映"波动"，不反映"资金成本"。
  等接入 VIX / 利率后，再按文档的四项加权替换。

映射（参数均为占位，待测试校准）：
  百分位   0–20   → 系数 0.30 → 1.00
  百分位  20–80   → 系数 1.00
  百分位  80–100  → 系数 1.00 → 0.40
  —— 中间区间完全不压（这是设计核心，别随意改成线性）
"""

import os
import numpy as np
import pandas as pd


# ────────────────────────────────────────────────
# 指标计算
# ────────────────────────────────────────────────

def realized_vol(close: pd.Series, window: int = 20) -> pd.Series:
    """已实现波动率：对数收益率的滚动标准差（年化可选，这里不年化）"""
    r = np.log(close / close.shift(1))
    return r.rolling(window, min_periods=window).std()


def atr_pct(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """ATR 百分比 = ATR / 收盘价 × 100"""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(window, min_periods=window).mean()
    return atr / close * 100.0


def pct_rank_rolling(series: pd.Series, lookback: int = 250) -> pd.Series:
    """
    滚动历史百分位（0-100）。
    注意：只用过去 N 个值，不含未来——这是 point-in-time 的前提。
    lookback 不够时返回 NaN。
    """
    def _rank(arr):
        if np.isnan(arr[-1]):
            return np.nan
        valid = arr[~np.isnan(arr)]
        if len(valid) < 20:
            return np.nan
        return (valid < arr[-1]).sum() / len(valid) * 100.0

    return series.rolling(lookback, min_periods=20).apply(_rank, raw=True)


# ────────────────────────────────────────────────
# 总分析师
# ────────────────────────────────────────────────

class ChiefAnalyst:
    """
    每晚一次，输出一个 0–100 的流动性百分位，映射成总系数。
    """

    def __init__(self, lookback: int = 250,
                 w_vol: float = 0.5, w_atr: float = 0.5):
        self.lookback = lookback
        self.w_vol = w_vol
        self.w_atr = w_atr

    def compute(self, daily: pd.DataFrame) -> pd.DataFrame:
        """
        daily: 含 open/high/low/close 的日线 DataFrame
        返回：附加了 vol_pct / atr_pct_rk / liquidity_pct / total_coeff 的 DataFrame
        """
        df = daily.copy()
        df["rv"] = realized_vol(df["close"], 20)
        df["atrp"] = atr_pct(df["high"], df["low"], df["close"], 14)

        # 各自转百分位
        df["rv_rk"] = pct_rank_rolling(df["rv"], self.lookback)
        df["atrp_rk"] = pct_rank_rolling(df["atrp"], self.lookback)

        # 合成百分位：越高 = 越紧
        df["liquidity_pct"] = self.w_vol * df["rv_rk"] + self.w_atr * df["atrp_rk"]

        # 映射成系数
        df["total_coeff"] = df["liquidity_pct"].apply(self._map_to_coeff)

        # 当晚定，次日用（shift(1)）
        df["total_coeff_next"] = df["total_coeff"].shift(1)
        return df

    @staticmethod
    def _map_to_coeff(pct: float) -> float:
        """中段平坦映射：只在两端出手"""
        if np.isnan(pct):
            return np.nan
        if pct <= 20:
            # 0 → 0.30, 20 → 1.00
            return 0.30 + (pct / 20.0) * 0.70
        if pct <= 80:
            return 1.00
        # 80 → 1.00, 100 → 0.40
        return 1.00 - ((pct - 80.0) / 20.0) * 0.60


# ────────────────────────────────────────────────
# 风控层
# ────────────────────────────────────────────────

class RiskManager:
    """
    仓位计算 + 归零线。
    所有约束都表达为「缩减」，唯一例外是归零线（一票否决）。
    """

    def __init__(self, equity: float = 10000.0, base_lot: float = 1.0,
                 risk_per_trade: float = 0.01,      # 单笔风险比例 1%
                 max_total_exposure: float = 1.0,   # 总暴露上限（相对基准）
                 min_win_rate: float = 0.30,        # 胜率归零线
                 max_daily_loss: float = 0.03,      # 单日亏损归零线
                 stop_atr_buffer: float = 1.2,      # 止损距离缓冲
                 contract_size: float = 100.0):     # 伦敦金 1 手 = 100 盎司
        self.equity = equity
        self.base_lot = base_lot   # 策略基准手数：风控只减不加，永远不超过它
        self.risk_per_trade = risk_per_trade
        self.max_total_exposure = max_total_exposure
        self.min_win_rate = min_win_rate
        self.max_daily_loss = max_daily_loss
        self.stop_atr_buffer = stop_atr_buffer
        self.contract_size = contract_size

        # 运行状态
        self.daily_pnl = 0.0
        self.zeroed_today = False
        self.zero_reason = None
        self.log = []

    # ── 归零线 ──
    def check_zero_lines(self, win_rate: float = None) -> tuple:
        """
        返回 (是否归零, 原因)
        优先级最高，不乘任何系数。
        """
        if self.zeroed_today:
            return True, self.zero_reason

        # 胜率归零
        if win_rate is not None and win_rate < self.min_win_rate:
            self.zeroed_today = True
            self.zero_reason = f"胜率 {win_rate:.1%} < {self.min_win_rate:.0%}"
            return True, self.zero_reason

        # 单日亏损归零
        if self.daily_pnl <= -self.equity * self.max_daily_loss:
            self.zeroed_today = True
            self.zero_reason = f"单日亏损 {self.daily_pnl:.2f} 超限"
            return True, self.zero_reason

        return False, None

    # ── 仓位计算 ──
    def calc_position(self, entry: float, stop: float,
                      total_coeff: float = 1.0,
                      atr: float = None,
                      win_rate: float = None) -> dict:
        """
        返回 dict：lots / reason / detail
        """
        # 1. 归零线
        zeroed, reason = self.check_zero_lines(win_rate)
        if zeroed:
            return dict(lots=0.0, reason=reason, detail={"zero_line": True})

        if np.isnan(total_coeff) or total_coeff <= 0:
            return dict(lots=0.0, reason="总系数无效", detail={"total_coeff": total_coeff})

        # 2. 止损距离（含缓冲）
        dist = abs(entry - stop)
        if atr is not None and not np.isnan(atr):
            dist = max(dist, atr * self.stop_atr_buffer)
        if dist <= 0:
            return dict(lots=0.0, reason="止损距离为 0", detail={"dist": dist})

        # 3. 风险预算 × 总系数
        base_budget = self.equity * self.risk_per_trade
        budget = base_budget * total_coeff * self.max_total_exposure

        # 4. 仓位 = 预算 ÷ (止损距离 × 合约乘数)
        lots = budget / (dist * self.contract_size)

        # 4.5 只减不加：不超过策略基准手数（这是文档里的硬规则，别删）
        raw_lots = lots
        lots = min(lots, self.base_lot)

        # 5. 最小手数（0.01）
        lots = np.floor(lots / 0.01) * 0.01
        if lots < 0.01:
            return dict(lots=0.0, reason="算出的仓位不足 0.01 手", detail={
                "dist": dist, "budget": budget, "raw_lots": budget / (dist * self.contract_size)
            })

        detail = dict(
            dist=dist,
            base_budget=base_budget,
            budget=budget,
            total_coeff=total_coeff,
            risk_amount=lots * dist * self.contract_size,
        )
        return dict(lots=lots, reason="ok", detail=detail)

    # ── 日切 ──
    def on_new_day(self):
        self.daily_pnl = 0.0
        self.zeroed_today = False
        self.zero_reason = None

    def record_pnl(self, pnl: float):
        self.daily_pnl += pnl

