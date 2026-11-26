#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""纸面模拟 broker：只记录，不真实下单

接口设计成和真实 broker 一致，将来换成 MT5 / 券商 API 时只改这个文件。

持仓结构：
  {"side": 1|-1|0, "lots": float, "entry_price": float, "entry_time": str, "stop": float}
"""

import os
import csv
import json
import datetime


class PaperBroker:
    def __init__(self, cfg, workdir):
        self.cfg = cfg
        self.workdir = workdir
        self.contract = cfg["account"]["contract_size"]
        self.trade_log = os.path.join(workdir, cfg["logging"]["trade_log"])
        os.makedirs(os.path.dirname(self.trade_log), exist_ok=True)
        if not os.path.exists(self.trade_log):
            with open(self.trade_log, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(
                    ["open_time", "close_time", "side", "lots", "entry_price",
                     "exit_price", "pnl", "reason"])

    # ── 持仓 ──
    def open(self, side, lots, price, stop, now, reason="signal"):
        return {
            "side": side, "lots": lots, "entry_price": price,
            "entry_time": now.isoformat(), "stop": stop, "reason": reason,
        }

    def close(self, pos, price, now, reason="signal"):
        if not pos or pos["side"] == 0:
            return None, 0.0
        pnl = (price - pos["entry_price"]) * pos["lots"] * self.contract if pos["side"] == 1 \
            else (pos["entry_price"] - price) * pos["lots"] * self.contract
        self._log(pos, price, now, pnl, reason)
        return None, pnl

    def _log(self, pos, exit_price, now, pnl, reason):
        with open(self.trade_log, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([
                pos["entry_time"], now.isoformat(), pos["side"], pos["lots"],
                f"{pos['entry_price']:.2f}", f"{exit_price:.2f}",
                f"{pnl:.2f}", reason,
            ])

    def partial_close(self, pos, lots, price, now, reason="partial"):
        """纸面模式部分平仓"""
        if not pos or lots <= 0:
            return pos, 0.0
        cur = pos.get("lots", 0.0)
        lots = min(round(lots / 0.01) * 0.01, cur)
        if lots <= 0:
            return pos, 0.0
        unit = self.contract
        pnl = (price - pos["entry_price"]) * lots * unit if pos["side"] == 1 \
            else (pos["entry_price"] - price) * lots * unit
        remain = round((cur - lots) / 0.01) * 0.01
        # 写日志
        try:
            with open(self.trade_log, "a", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow([
                    pos.get("entry_time", ""), now.isoformat(), pos.get("side"),
                    lots, f"{pos.get('entry_price', 0):.2f}", f"{price:.2f}",
                    f"{pnl:.2f}", reason])
        except Exception:
            pass
        if remain < 0.01:
            return None, pnl
        pos = dict(pos)
        pos["lots"] = remain
        return pos, pnl

    def cancel_all_pending(self):
        """纸面模式下没有挂单，返回 0"""
        return 0

    def flat_all(self, price, now, reason="daily_flat"):
        """平所有仓 + 撤所有挂单（休盘前调用）"""
        n = self.cancel_all_pending()
        return n


# ═══════════════════════════════════════════════════
# MT5 真实下单
# ═══════════════════════════════════════════════════

class MT5Broker:
    """连 MT5 模拟账户真实下单"""

    def __init__(self, cfg, workdir):
        from mt5_broker import MT5Client, MT5_AVAILABLE, MT5Error
        if not MT5_AVAILABLE:
            raise RuntimeError("没有安装 MetaTrader5 包")
        self.cfg = cfg
        self.workdir = workdir
        mcfg = cfg.get("broker", {}).get("mt5", {})
        self.symbol = mcfg.get("symbol", "XAUUSD")
        self.magic = mcfg.get("magic", 20261124)

        # 和 market_data 共用同一个连接，避免重复 initialize
        self.client = MT5Client.shared(
            login=mcfg.get("login"),
            password=mcfg.get("password"),
            server=mcfg.get("server"),
            path=mcfg.get("path") or None,
        )

        # 交易日志（和纸面模式共用同一个 csv）
        self.trade_log = os.path.join(workdir, cfg["logging"]["trade_log"])
        os.makedirs(os.path.dirname(self.trade_log), exist_ok=True)
        if not os.path.exists(self.trade_log):
            with open(self.trade_log, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(
                    ["open_time", "close_time", "side", "lots", "entry_price",
                     "exit_price", "pnl", "reason"])

    # ── 账户 ──
    def equity(self) -> float:
        return float(self.client.account()["equity"])

    def balance(self) -> float:
        return float(self.client.account()["balance"])

    # ── 持仓 ──
    def positions(self) -> list:
        return self.client.positions(self.symbol)

    def open(self, side, lots, price, stop, now, reason="signal"):
        """
        side: 1 = 多, -1 = 空
        真实下单，返回持仓信息（从 MT5 读回来）
        """
        res = self.client.market_order(
            self.symbol,
            "buy" if side == 1 else "sell",
            lots,
            sl=stop,
            comment=f"riskctl:{reason}"[:31],
            magic=self.magic,
        )
        # 读回实际持仓
        for p in self.client.positions(self.symbol):
            return {
                "side": side,
                "lots": p["volume"],
                "entry_price": p["price_open"],
                # ★ 用本地 now，不用 MT5 的 p["time"]：
                #   那个是服务器时间戳（EET = UTC+2），标成 UTC 会差 1-2 小时
                "entry_time": now.isoformat(),
                "stop": p["sl"],
                "ticket": p["ticket"],
                "reason": reason,
                "_pnl_settled": 0.0,   # 已结算的部分平仓盈亏
            }
        # 万一读不到，用返回值兜底
        return {
            "side": side, "lots": res.get("volume", lots),
            "entry_price": res.get("price", price),
            "entry_time": now.isoformat(), "stop": stop,
            "ticket": res.get("ticket"), "reason": reason,
        }

    def close(self, pos, price, now, reason="signal"):
        """平仓，返回 (None, pnl)"""
        if not pos:
            return None, 0.0
        ticket = pos.get("ticket")
        if not ticket:
            # 没有 ticket 就按品种全平
            self.client.close_all(self.symbol, comment=f"close:{reason}")
            return None, 0.0

        try:
            self.client.close_position(ticket, comment=f"close:{reason}"[:31])
        except Exception as e:
            # 已经不存在（可能被止损平掉）——仍然去读这笔的真实盈亏
            if "不存在" not in str(e):
                raise

        # 从成交记录读真实盈亏（balance 平仓后不会立即更新，不能靠差值）
        # ★ position_pnl 返回的是这笔持仓【累计】盈亏，
        #   如果之前做过部分平仓，要减去已结算的那部分
        cumulative = self.client.position_pnl(ticket)
        pnl = cumulative - float(pos.get("_pnl_settled", 0.0))

        # 写日志
        try:
            with open(self.trade_log, "a", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow([
                    pos.get("entry_time", ""), now.isoformat(),
                    pos.get("side"), pos.get("lots"),
                    f"{pos.get('entry_price', 0):.2f}",
                    f"{price:.2f}", f"{pnl:.2f}", reason,
                ])
        except Exception:
            pass
        return None, pnl

    def partial_close(self, pos, lots, price, now, reason="partial"):
        """
        部分平仓。lots 是要平掉的手数（不是剩余）。
        返回 (更新后的持仓 dict, 实现盈亏)
        """
        if not pos or lots <= 0:
            return pos, 0.0

        ticket = pos.get("ticket")
        cur_lots = pos.get("lots", 0.0)
        lots = min(round(lots / 0.01) * 0.01, cur_lots)
        if lots <= 0:
            return pos, 0.0

        # 全平走 close()
        if abs(lots - cur_lots) < 1e-9:
            new_pos, pnl = self.close(pos, price, now, reason)
            return new_pos, pnl

        # 部分平
        try:
            self.client.partial_close_position(ticket, lots,
                                               comment=f"pcut:{reason}"[:31])
        except Exception as e:
            if "不存在" in str(e):
                return None, 0.0
            raise

        cumulative = self.client.position_pnl(ticket)
        settled_before = float(pos.get("_pnl_settled", 0.0))
        pnl = cumulative - settled_before       # 本次平仓的增量盈亏
        remain = round((cur_lots - lots) / 0.01) * 0.01
        if remain < 0.01:
            return None, pnl

        pos = dict(pos)
        pos["lots"] = remain
        pos["_pnl_settled"] = cumulative        # 记下累计值，下次减掉
        return pos, pnl

    def cancel_all_pending(self):
        return self.client.cancel_pending(self.symbol)

    def flat_all(self, price, now, reason="daily_flat"):
        """平所有仓 + 撤所有挂单"""
        n = self.client.cancel_pending(self.symbol)
        self.client.close_all(self.symbol, comment=f"flat:{reason}"[:31])
        return n

    def account_info(self) -> dict:
        return self.client.account()


# ═══════════════════════════════════════════════════
# 工厂
# ═══════════════════════════════════════════════════

def make_broker(cfg, workdir):
    """按 config.broker.mode 选纸面还是 MT5"""
    mode = cfg.get("broker", {}).get("mode", "paper")
    if mode == "mt5":
        return MT5Broker(cfg, workdir)
    return PaperBroker(cfg, workdir)
