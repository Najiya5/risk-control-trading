#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""行情数据源适配层

支持三类来源：
  csv   —— 本地 MT4 导出的 CSV（回测/离线用）
  xaus  —— xaus.com 实时现货（5 分钟采样，本地聚合成 K 线）
  mt5   —— 读取 MT5 客户端的历史 K 线（备用，暂未实现）

统一输出：DataFrame，列为 open/high/low/close/volume，索引为 UTC 时间

设计要点：
  - xaus 只给 5 分钟采样点，本地攒够一根 K 线需要的点数再输出
  - 历史（CSV）和实时（xaus）拼接在一条时间线上，接缝处不重叠
  - 数据源失败时抛异常，由调用方决定降级策略
"""

import os
import json
import time
import urllib.request
import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

XAUS_SPOT = "https://xaus.com/api/v1/spot"
XAUS_INTRADAY = "https://xaus.com/api/v1/intraday"


# ────────────────────────────────────────────────
# xaus 客户端
# ────────────────────────────────────────────────

class XausClient:
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._tick_buf = []          # [(ts, price), ...] 攒采样点
        self._last_ts = 0

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def spot(self) -> dict:
        """即时价，返回 {price, as_of, status, age_seconds}"""
        d = self._get(XAUS_SPOT + "?compact=1")
        ds = d.get("data_state", {})
        xau = d.get("xau", {})
        return {
            "price": float(xau.get("price") or d.get("spot_usd_oz")),
            "as_of": ds.get("as_of"),
            "status": ds.get("status", "unknown"),
            "age_seconds": ds.get("age_seconds"),
        }

    def intraday(self, hours: int = 24) -> pd.DataFrame:
        """日内采样点（5 分钟一个），返回 DataFrame[ts, price]"""
        d = self._get(f"{XAUS_INTRADAY}?symbol=xau&hours={hours}")
        pts = d.get("points", [])
        if not pts:
            return pd.DataFrame(columns=["ts", "price"])
        df = pd.DataFrame(pts)
        df["dt"] = pd.to_datetime(df["t"], unit="s", utc=True)
        df = df.rename(columns={"p": "price"})
        return df[["dt", "price"]].sort_values("dt").reset_index(drop=True)

    def poll(self) -> dict:
        """轮询一次即时价，并攒进缓冲区"""
        s = self.spot()
        if s["price"] > 0:
            ts = int(time.time())
            if ts != self._last_ts:
                self._tick_buf.append((ts, s["price"]))
                self._last_ts = ts
        return s

    def bars_from_buffer(self, minutes: int = 60) -> pd.DataFrame:
        """
        把攒到的采样点聚合成 K 线。
        注意：只有采集到的点才参与，不补零、不插值。
        """
        if not self._tick_buf:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        raw = pd.DataFrame(self._tick_buf, columns=["ts", "price"])
        raw["dt"] = pd.to_datetime(raw["ts"], unit="s", utc=True)
        raw = raw.set_index("dt").sort_index()
        rule = f"{minutes}min"
        g = raw["price"].resample(rule).agg(["first", "max", "min", "last", "count"]).dropna()
        g.columns = ["open", "high", "low", "close", "volume"]
        return g

    def seed_from_intraday(self, hours: int = 48):
        """启动时用日内采样把缓冲区补满（避免刚启动没数据）"""
        try:
            df = self.intraday(hours)
            if len(df) == 0:
                return 0
            self._tick_buf = [(int(r.dt.timestamp()), float(r.price)) for r in df.itertuples()]
            self._tick_buf.sort()
            self._last_ts = self._tick_buf[-1][0] if self._tick_buf else 0
            return len(self._tick_buf)
        except Exception:
            return 0


# ────────────────────────────────────────────────
# 本地 CSV（历史）
# ────────────────────────────────────────────────

def load_csv(tf: str, n: int = 500, srv: str = "Tickmill-DemoUK") -> pd.DataFrame:
    p = os.path.join(ROOT, f"XAUUSD_{tf}_{srv}.csv")
    df = pd.read_csv(p, parse_dates=["time"]).set_index("time").sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.tail(n).copy()


# ────────────────────────────────────────────────
# MT5（本地客户端，真实 OHLC）
# ────────────────────────────────────────────────

_mt5_client = None


def get_mt5(cfg: dict = None):
    """懒加载 MT5 客户端"""
    global _mt5_client
    if _mt5_client is not None:
        return _mt5_client
    try:
        from mt5_broker import MT5Client
    except Exception as e:
        raise RuntimeError(f"MT5 模块导入失败: {e}")
    mcfg = (cfg or {}).get("broker", {}).get("mt5", {})
    _mt5_client = MT5Client.shared(
        login=mcfg.get("login"),
        password=mcfg.get("password"),
        server=mcfg.get("server"),
        path=mcfg.get("path") or None,
    )
    return _mt5_client


def load_mt5(tf: str, n: int = 500, cfg: dict = None) -> pd.DataFrame:
    """从 MT5 客户端读 K 线（真实 OHLCV）"""
    c = get_mt5(cfg)
    symbol = (cfg or {}).get("broker", {}).get("mt5", {}).get("symbol", "XAUUSD")
    return c.bars(symbol, tf, n)


# ────────────────────────────────────────────────
# 统一入口
# ────────────────────────────────────────────────

class MarketData:
    """
    source: "csv" | "xaus" | "mt5"
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        md = cfg.get("market_data", {})
        self.source = md.get("source", "csv")
        self.cachefile = os.path.join(ROOT, "XAUUSD_H1_LIVE.csv")
        self.h1_frames = []          # 实时攒出来的 H1
        self.xaus = None
        self.seeded = False

    def prepare(self) -> bool:
        """启动时准备；返回是否成功"""
        if self.source == "xaus":
            self.xaus = XausClient()
            n = self.xaus.seed_from_intraday(48)
            self.seeded = n > 0
            return self.seeded
        if self.source == "csv":
            return True
        if self.source == "mt5":
            try:
                get_mt5(self.cfg)
                return True
            except Exception:
                return False
        return False

    def load_bars(self, tf: str, n: int = 500) -> pd.DataFrame:
        """返回历史 + 实时拼起来的 K 线"""
        if self.source == "mt5":
            return load_mt5(tf, n, self.cfg)

        hist = load_csv(tf, n=n * 2 if self.source == "xaus" else n)

        if self.source != "xaus" or self.xaus is None:
            return hist.tail(n)

        # 轮询一次，把点攒进来
        try:
            self.xaus.poll()
        except Exception:
            pass

        live = self.xaus.bars_from_buffer(60)
        if len(live) == 0:
            return hist.tail(n)

        live = live.reset_index().rename(columns={"dt": "time"}).set_index("time")

        # 拼接：只取实时部分中晚于历史最后一根的时间
        last_hist = hist.index[-1]
        live = live[live.index > last_hist]
        if len(live) == 0:
            return hist.tail(n)

        merged = pd.concat([hist, live])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        return merged.tail(n)

    def status(self) -> dict:
        """给 UI 显示的数据源状态"""
        if self.source == "csv":
            return {"source": "csv", "ok": True, "msg": "本地 CSV（离线回放）"}
        if self.source == "xaus":
            if self.xaus is None:
                return {"source": "xaus", "ok": False, "msg": "未初始化"}
            try:
                s = self.xaus.spot()
                return {
                    "source": "xaus",
                    "ok": s["status"] == "fresh",
                    "price": s["price"],
                    "age": s["age_seconds"],
                    "status": s["status"],
                    "ticks": len(self.xaus._tick_buf),
                    "msg": f"{s['status']} · {s['age_seconds']}s 前 · 缓冲 {len(self.xaus._tick_buf)} 点",
                }
            except Exception as e:
                return {"source": "xaus", "ok": False, "msg": f"拉取失败: {e}"}
        if self.source == "mt5":
            try:
                c = get_mt5(self.cfg)
                symbol = self.cfg.get("broker", {}).get("mt5", {}).get("symbol", "XAUUSD")
                tk = c.tick(symbol)
                acct = c.account()
                return {
                    "source": "mt5", "ok": True,
                    "price": tk["mid"],
                    "msg": f"MT5 已连接 · {tk['bid']:.2f}/{tk['ask']:.2f} · "
                           f"余额 {acct['balance']:,.0f} {acct['currency']}",
                }
            except Exception as e:
                return {"source": "mt5", "ok": False, "msg": f"MT5 连接失败: {e}"}
        return {"source": self.source, "ok": False, "msg": "未知数据源"}
