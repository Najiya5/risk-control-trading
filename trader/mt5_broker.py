#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MT5 接口层

依赖：MetaTrader5（官方 Python 包）

前提：
  - MT5 客户端必须开着并已登录
  - 账号需要是 MT5 账户（MT4 不通用）

能力：
  - 初始化 / 登录
  - 读 K 线（H1 等）
  - 读账户信息、持仓
  - 下单 / 平仓 / 撤单

如果没装 MetaTrader5 包，导入时不会报错，调用时抛明确异常。
"""

import datetime


MT5_AVAILABLE = False
mt5 = None
try:
    import MetaTrader5 as mt5      # noqa: N813
    MT5_AVAILABLE = True
except ImportError:
    pass


class MT5Error(RuntimeError):
    pass


# 周期映射
TIMEFRAMES = {}
if MT5_AVAILABLE:
    TIMEFRAMES = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }


class MT5Client:
    def __init__(self, login=None, password=None, server=None, path=None):
        if not MT5_AVAILABLE:
            raise MT5Error(
                "没有安装 MetaTrader5 包。安装方法：\n"
                "  pip install MetaTrader5\n"
                "注意：这个包只能在 Windows 上装。")
        self.login = int(login) if login else None
        self.password = password
        self.server = server
        self.path = path
        self._ready = False

    # ── 全局单例：整个进程只 initialize 一次 ──
    _instance = None

    @classmethod
    def shared(cls, login=None, password=None, server=None, path=None):
        """拿全局唯一的客户端；已连过就直接返回"""
        if cls._instance is None:
            cls._instance = cls(login, password, server, path)
            cls._instance.connect()
        return cls._instance

    # ── 连接 ──
    def connect(self) -> bool:
        if self._ready:
            return True
        kwargs = {}
        if self.path:
            kwargs["path"] = self.path
        if self.login:
            kwargs["login"] = self.login
            kwargs["password"] = self.password
            kwargs["server"] = self.server
        if not mt5.initialize(**kwargs):
            raise MT5Error(f"MT5 初始化失败: {mt5.last_error()}")
        info = mt5.account_info()
        if info is None:
            raise MT5Error("已连接但读不到账户信息，确认 MT5 是否已登录")
        self._ready = True
        return True

    def shutdown(self):
        if MT5_AVAILABLE:
            mt5.shutdown()
        self._ready = False

    def _check(self):
        if not self._ready:
            raise MT5Error("未连接，请先 connect()")

    # ── 账户 ──
    def account(self) -> dict:
        self._check()
        a = mt5.account_info()
        if a is None:
            raise MT5Error(f"读账户信息失败: {mt5.last_error()}")
        return {
            "login": a.login,
            "server": a.server,
            "name": a.name,
            "currency": a.currency,
            "balance": a.balance,
            "equity": a.equity,
            "margin": a.margin,
            "free_margin": a.margin_free,
            "leverage": a.leverage,
            "profit": a.profit,
        }

    # ── 行情 ──
    def bars(self, symbol: str, timeframe: str = "H1", count: int = 500):
        """返回 DataFrame(time, open, high, low, close, volume)，时间已转 UTC"""
        self._check()
        tf = TIMEFRAMES.get(timeframe.upper())
        if tf is None:
            raise MT5Error(f"不支持的周期: {timeframe}")

        if not mt5.symbol_select(symbol, True):
            raise MT5Error(f"品种 {symbol} 不可选，检查 MT5 里是否启用")

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            raise MT5Error(f"读取 {symbol} {timeframe} 数据失败: {mt5.last_error()}")

        import pandas as pd
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time").rename(columns={"tick_volume": "volume"})
        return df[["open", "high", "low", "close", "volume"]]

    def tick(self, symbol: str) -> dict:
        self._check()
        t = mt5.symbol_info_tick(symbol)
        if t is None:
            raise MT5Error(f"读 {symbol} 报价失败: {mt5.last_error()}")
        return {"bid": t.bid, "ask": t.ask,
                "mid": (t.bid + t.ask) / 2,
                "time": datetime.datetime.fromtimestamp(t.time, datetime.UTC).isoformat()}

    def symbol_info(self, symbol: str) -> dict:
        self._check()
        s = mt5.symbol_info(symbol)
        if s is None:
            raise MT5Error(f"品种 {symbol} 不存在")
        return {
            "symbol": s.name,
            "digits": s.digits,
            "point": s.point,
            "contract_size": s.trade_contract_size,
            "min_lot": s.volume_min,
            "max_lot": s.volume_max,
            "lot_step": s.volume_step,
            "spread": s.spread,
        }

    # ── 持仓 ──
    def positions(self, symbol: str = None) -> list:
        self._check()
        pos = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if pos is None:
            return []
        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "time": datetime.datetime.fromtimestamp(p.time, datetime.UTC).isoformat(),
            }
            for p in pos
        ]

    # ── 下单 ──
    def market_order(self, symbol: str, side: str, lots: float,
                     sl: float = 0.0, tp: float = 0.0,
                     comment: str = "risk-ctl", magic: int = 20261124) -> dict:
        """
        side: "buy" | "sell"
        返回 {ok, ticket, price, comment}
        """
        self._check()
        info = mt5.symbol_info(symbol)
        if info is None:
            raise MT5Error(f"品种 {symbol} 不存在")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5Error("读不到报价")

        order_type = mt5.ORDER_TYPE_BUY if side.lower() == "buy" else mt5.ORDER_TYPE_SELL
        price = tick.ask if side.lower() == "buy" else tick.bid

        # 手数取整到允许的最小步长
        step = info.volume_step or 0.01
        lots = round(round(lots / step) * step, 8)
        lots = max(info.volume_min, min(lots, info.volume_max))

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lots,
            "type": order_type,
            "price": price,
            "deviation": 30,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if sl > 0:
            request["sl"] = round(sl, info.digits)
        if tp > 0:
            request["tp"] = round(tp, info.digits)

        result = mt5.order_send(request)
        if result is None:
            raise MT5Error(f"下单返回空: {mt5.last_error()}")
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise MT5Error(f"下单被拒 retcode={result.retcode} {result.comment}")
        return {"ok": True, "ticket": result.order, "price": result.price,
                "volume": lots, "comment": result.comment}

    def close_position(self, ticket: int, comment: str = "risk-ctl close") -> dict:
        """平掉指定持仓"""
        self._check()
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            raise MT5Error(f"持仓 {ticket} 不存在")
        p = pos[0]

        tick = mt5.symbol_info_tick(p.symbol)
        info = mt5.symbol_info(p.symbol)
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "position": ticket,
            "price": tick.bid if is_buy else tick.ask,
            "deviation": 30,
            "magic": p.magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            raise MT5Error(f"平仓返回空: {mt5.last_error()}")
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise MT5Error(f"平仓被拒 retcode={result.retcode} {result.comment}")
        return {"ok": True, "ticket": result.order, "price": result.price}

    def partial_close_position(self, ticket: int, lots: float,
                               comment: str = "risk-ctl partial") -> dict:
        """部分平仓：从指定持仓里平掉 lots 手"""
        self._check()
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            raise MT5Error(f"持仓 {ticket} 不存在")
        p = pos[0]

        info = mt5.symbol_info(p.symbol)
        lots = round(lots / info.volume_step) * info.volume_step
        lots = max(min(lots, p.volume), info.volume_min)
        if lots >= p.volume:
            return self.close_position(ticket, comment)

        tick = mt5.symbol_info_tick(p.symbol)
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": lots,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "position": ticket,
            "price": tick.bid if is_buy else tick.ask,
            "deviation": 30,
            "magic": p.magic,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            raise MT5Error(f"部分平仓返回空: {mt5.last_error()}")
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise MT5Error(f"部分平仓被拒 retcode={result.retcode} {result.comment}")
        return {"ok": True, "ticket": result.order, "price": result.price,
                "volume": lots, "comment": result.comment}

    def position_pnl(self, ticket: int, wait: float = 2.0) -> float:
        """
        读某笔持仓的已实现盈亏。
        从成交记录（deals）里找 position_id == ticket 的所有 deal，累加 profit。

        平仓后成交记录可能延迟，最多等 wait 秒。
        """
        import time
        deadline = time.time() + wait
        while time.time() < deadline:
            deals = mt5.history_deals_get(position=ticket)
            if deals and len(deals) > 0:
                total = sum(d.profit + d.swap + d.commission for d in deals)
                # 至少要有一个 OUT deal 才算真的平掉了
                has_out = any(d.entry == mt5.DEAL_ENTRY_OUT for d in deals)
                if has_out:
                    return float(total)
            time.sleep(0.3)

        # 超时了，退而求其次：用历史订单里找
        hist = mt5.history_orders_get(ticket=ticket)
        if hist:
            return 0.0
        return 0.0

    def close_all(self, symbol: str = None, comment: str = "risk-ctl flat") -> list:
        """平掉所有持仓（可按品种过滤）"""
        out = []
        for p in self.positions(symbol):
            try:
                out.append(self.close_position(p["ticket"], comment))
            except Exception as e:
                out.append({"ok": False, "ticket": p["ticket"], "error": str(e)})
        return out

    def cancel_pending(self, symbol: str = None) -> int:
        """撤销所有挂单"""
        self._check()
        orders = mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
        if not orders:
            return 0
        n = 0
        for o in orders:
            req = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket}
            if mt5.order_send(req) is not None and mt5.order_send(req).retcode == mt5.TRADE_RETCODE_DONE:
                n += 1
        return n
