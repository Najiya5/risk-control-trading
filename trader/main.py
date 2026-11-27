#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""风控主程序

运行节奏：
  - 每 60 秒轮询一次
  - 数据：从本地 CSV 读取最新行情（后续可换成实时源）
  - 决策：OsMA 信号 + ATRP 波动率拦截 + 总分析师百分比拦截 + 事件系数
  - 下单：纸面模拟（broker.py）
  - 纽约休盘前 10 分钟：平仓 + 撤单
  - 签字有效期 24 小时：过期只平仓不开新仓，程序不中断

所有状态写到 state.json，日志写到 logs/。可随时 kill，下次启动自动接上。
"""

import io
import os
import sys
import json
import time
import datetime
import traceback

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 复用已有的指标实现
sys.path.insert(0, os.path.join(ROOT, "osma"))
sys.path.insert(0, os.path.join(ROOT, "risk"))
sys.path.insert(0, os.path.join(ROOT, "event"))

from indicator import osma                      # noqa: E402
from vol_event_layer import atrp, vol_pressure  # noqa: E402
from broker import PaperBroker                  # noqa: E402
from order_risk import check_order_risk            # noqa: E402
from daily_analyst import get_prev_day_coeff        # noqa: E402

try:
    import event_layer as EL
except Exception:
    EL = None


# ────────────────────────────────────────────────
# 工具
# ────────────────────────────────────────────────

def load_cfg(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def now():
    return datetime.datetime.now(datetime.UTC)


# 全局日志回调（UI 挂上去就能收到主循环的日志）
LOG_SINK = None


def log(msg, logfile):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    # 推给 UI（如果挂了回调）
    if LOG_SINK is not None:
        try:
            LOG_SINK(msg)
        except Exception:
            pass


def load_state(path, cfg):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "position": None,
        "equity": cfg["account"]["initial_equity"],
        "daily_pnl": 0.0,
        "today": "",
        "daily_coeff": 1.0,
        "last_bar": None,
        "approved_until": None,
        "last_event_check": None,
        "event_pressure": 0.0,
        "flat_done_for": None,
    }


# 只由 UI 写入、主循环不能覆盖的字段
UI_OWNED_FIELDS = ("approved_until", "approved_at", "_report_read_date")


def _sync_ui_fields(path, st):
    """
    保存前先从磁盘同步「UI 独占」字段。

    主循环的 st 是启动时读的快照，UI 签字/标记已读写的是磁盘。
    不同步的话，下一轮 save_state 会把 UI 的改动冲掉。
    """
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8-sig") as f:
            disk = json.load(f)
        for k in UI_OWNED_FIELDS:
            if k in disk:
                st[k] = disk[k]
            elif k in st:
                # 磁盘上没有（用户清空了签字），跟着清掉
                del st[k]
    except Exception:
        pass


def save_state(path, st):
    _sync_ui_fields(path, st)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)


# ────────────────────────────────────────────────
# 行情
# ────────────────────────────────────────────────

_MD = None   # 全局行情数据源


def get_market_data(cfg=None):
    """懒初始化行情源"""
    global _MD
    if _MD is None:
        import market_data
        if cfg is None:
            cfg = load_cfg(os.path.join(HERE, "config.json"))
        _MD = market_data.MarketData(cfg)
        _MD.prepare()
    return _MD


def load_bars(tf, n=500, cfg=None):
    """从配置的数据源读取 K 线（csv / xaus / mt5）"""
    md = get_market_data(cfg)
    return md.load_bars(tf, n=n)


# ────────────────────────────────────────────────
# 纽约休盘时刻
# ────────────────────────────────────────────────

def newyork_close_utc(day_utc: datetime.date) -> datetime.datetime:
    """
    纽约 17:00 收盘对应的 UTC 时刻。
    EDT(夏令时) = UTC-4 → 21:00 UTC
    EST(冬令时) = UTC-5 → 22:00 UTC
    """
    # 美国夏令时：3月第二个周日 ~ 11月第一个周日
    y = day_utc.year
    # 3月第二个周日
    mar = datetime.date(y, 3, 1)
    while mar.weekday() != 6:
        mar += datetime.timedelta(days=1)
    dst_start = mar + datetime.timedelta(days=7)
    # 11月第一个周日
    nov = datetime.date(y, 11, 1)
    while nov.weekday() != 6:
        nov += datetime.timedelta(days=1)
    dst_end = nov

    is_dst = dst_start <= day_utc < dst_end
    hour = 21 if is_dst else 22
    return datetime.datetime(day_utc.year, day_utc.month, day_utc.day, hour, 0,
                             tzinfo=datetime.UTC)


# ────────────────────────────────────────────────
# 签字
# ────────────────────────────────────────────────

def is_approved(st, cfg):
    au = st.get("approved_until")
    if not au:
        return False
    try:
        until = datetime.datetime.fromisoformat(au)
        if until.tzinfo is None:
            until = until.replace(tzinfo=datetime.UTC)
        return now() < until
    except Exception:
        return False


# ────────────────────────────────────────────────
# 事件层
# ────────────────────────────────────────────────

def check_events(cfg, st, logfile):
    """返回事件压力（0-1）。失败时返回 0（降级，不阻断）。"""
    if not cfg["event_layer"]["enabled"] or EL is None:
        return 0.0

    last = st.get("last_event_check")
    if last:
        try:
            lt = datetime.datetime.fromisoformat(last)
            if lt.tzinfo is None:
                lt = lt.replace(tzinfo=datetime.UTC)
            if (now() - lt).total_seconds() < cfg["event_layer"]["poll_seconds"]:
                return st.get("event_pressure", 0.0)
        except Exception:
            pass

    st["last_event_check"] = now().isoformat()
    st["_evt_fails"] = 0

    try:
        news = EL.fetch_news()
        events = EL.filter_events(news, only_important=cfg["event_layer"]["only_important"],
                                  max_items=cfg["event_layer"]["max_events_per_check"])
        if not events:
            log("事件检查：无新事件", logfile)
            return 0.0

        judges = []
        for m in cfg["event_layer"]["models"]:
            if not m.get("enabled") or not m.get("api_key"):
                continue
            judges.append({
                "name": m["name"],
                "fn": (lambda c, _m=m: EL.judge_with_deepseek(
                    c, _m["api_key"], base_url=_m["base_url"], model=_m["model"])),
            })
        if not judges:
            log(f"事件检查：{len(events)} 条，但没有可用模型（降级）", logfile)
            return 0.0

        pressures = []
        for e in events:
            res = EL.judge_all(e, judges)
            agg = EL.aggregate(res)
            if not agg.get("ok"):
                continue
            blocked, why = EL.check_dispersion(agg)
            p = 1.0 if blocked else agg["severity"]
            pressures.append(p)
            log(f"事件[{e['time']}] severity={agg['severity']:.2f} "
                f"n={agg['n']} blocked={blocked} {why or ''}", logfile)
            _write_event_log(cfg, e, agg, blocked, why, p)

        if not pressures:
            return 0.0
        # 取最大值（事件压力不平均，最坏的说了算）
        return float(max(pressures))

    except Exception as ex:
        # 失败退避：连续失败时降低重试频率，避免把 socket 打满
        fails = st.get("_evt_fails", 0) + 1
        st["_evt_fails"] = fails
        if fails <= 3:
            log(f"事件检查失败（降级为 0）：{type(ex).__name__}: {ex}", logfile)
        elif fails == 4:
            log(f"事件检查连续失败 {fails} 次，进入退避模式（每 30 分钟重试一次）", logfile)
        # 把下次检查时间推后
        st["last_event_check"] = (
            now() + datetime.timedelta(minutes=25 * min(fails - 1, 5))).isoformat()
        return 0.0


# ────────────────────────────────────────────────
# 事件判断落盘
# ────────────────────────────────────────────────

def _write_event_log(cfg, event, agg, blocked, why, pressure):
    """每判断完一条事件，追加一行到 logs/events.csv（JSON 行格式）"""
    try:
        path = os.path.join(HERE, cfg["logging"]["event_log"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = {
            "time": str(event.get("time", "")),
            "date": datetime.date.today().isoformat(),
            "title": str(event.get("title") or event.get("content") or "")[:120],
            "severity": round(float(agg.get("severity", 0)), 3),
            "impact": round(float(agg.get("impact", 0)), 3),
            "horizon": agg.get("horizon", ""),
            "n_judges": int(agg.get("n", 0)),
            "blocked": bool(blocked),
            "why": str(why or ""),
            "pressure": round(float(pressure), 3),
            "reason": str(agg.get("reason", ""))[:200],
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with io.open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as ex:
        print(f"[events.csv 写入失败] {type(ex).__name__}: {ex}", flush=True)


# ────────────────────────────────────────────────
# 总分析师：每天算一次，缓存在 state
# ────────────────────────────────────────────────

def get_daily_coeff(cfg, st, logfile):
    """返回昨天的总系数（1.0 / 0.5 / 0.0）"""
    today = str(datetime.date.today())
    if st.get("_da_date") == today:
        return st.get("_da_coeff", 1.0)

    try:
        d1 = load_bars("D1", n=400, cfg=cfg)
        r = get_prev_day_coeff(d1, cfg)
        coeff = float(r["coeff"])
        st["_da_date"] = today
        st["_da_coeff"] = coeff
        st["_da_detail"] = {k: (v if not isinstance(v, float) else round(v, 2))
                            for k, v in r.items()}
        log(f"[总分析师] 昨日百分位 {r.get('pct', 0):.1f}% → 系数 {coeff:.1f}"
            f"（{r.get('reason', '')}）", logfile)
        return coeff
    except Exception as ex:
        log(f"[总分析师] 计算失败（按 1.0 处理）: {type(ex).__name__}: {ex}", logfile)
        st["_da_date"] = today
        st["_da_coeff"] = 1.0
        return 1.0


# ────────────────────────────────────────────────
# 每日战报：20:00 自动生成
# ────────────────────────────────────────────────

def _daily_report_tick(cfg, st, logfile):
    """每天 20:00 生成一次战报"""
    rpt_hour = cfg.get("schedule", {}).get("daily_report_hour", 20)
    t = datetime.datetime.now()
    today = t.strftime("%Y-%m-%d")

    if t.hour < rpt_hour:
        return
    if st.get("_report_date") == today:
        return

    try:
        import daily_report
        path = daily_report.save_report(cfg, st, today)
        st["_report_date"] = today
        log(f"[战报] 已生成 {os.path.basename(path)}", logfile)
    except Exception as ex:
        log(f"[战报] 生成失败: {type(ex).__name__}: {ex}", logfile)


# ────────────────────────────────────────────────
# 主逻辑
# ────────────────────────────────────────────────

def compute_indicators(cfg, tf):
    df = load_bars(tf, cfg=cfg)
    ind = atrp(df, cfg["vol_risk"]["atr_period_1"], cfg["vol_risk"]["atr_period_2"])
    s = cfg["strategy"]
    ind = ind.join(osma(df, s["fast_ema"], s["slow_ema"], s["signal_ema"],
                        s["weight_body"], s["weight_shadow"]), how="inner",
                   rsuffix="_o")
    ind = ind.dropna(subset=["atrp", "atrp_ma", "osma", "signal"])
    if len(ind) == 0:
        return None
    return ind


def run_once(cfg, st, broker, logfile):
    tf = cfg["timeframe"]
    ind = compute_indicators(cfg, tf)
    if ind is None:
        if st.get("_last_skip") != str(datetime.date.today()):
            log("指标数据不足，跳过（这只在数据源异常时出现）", logfile)
            st["_last_skip"] = str(datetime.date.today())
        return

    bar = ind.iloc[-1]
    bar_time = ind.index[-1]
    price = float(bar["close"])
    t = now()

    # ── 每天 20:00 生成当日战报（只生成一次） ──
    _daily_report_tick(cfg, st, logfile)

    # ── 日内平仓：纽约休盘前 N 分钟 ──
    close_utc = newyork_close_utc(t.date())
    flat_at = close_utc - datetime.timedelta(
        minutes=cfg["schedule"]["flat_before_newyork_close_minutes"])
    if flat_at <= t < close_utc and st.get("flat_done_for") != str(t.date()):
        if st.get("position"):
            st["position"], pnl = broker.close(st["position"], price, t, "daily_flat")
            st["equity"] += pnl
            log(f"[休盘平仓] 平掉持仓，pnl={pnl:.2f}", logfile)
        broker.cancel_all_pending()
        st["flat_done_for"] = str(t.date())
        log(f"[休盘平仓] 已平仓并撤单（休盘 {close_utc:%H:%M} UTC）", logfile)
        save_state(os.path.join(HERE, cfg["logging"]["state_file"]), st)
        return

    # ── 新交易日：重置日内状态 ──
    today = str(t.date())
    if st.get("today") != today:
        st["today"] = today
        st["daily_pnl"] = 0.0

    # ── 签字检查 ──
    approved = is_approved(st, cfg)

    # ── 信号 ──
    long_ok = bool(bar["osma"] > 0 and bar["signal"] > 0)
    short_ok = bool(bar["osma"] < 0 and bar["signal"] < 0)
    new_bar = st.get("last_bar") != str(bar_time)

    # ── 持仓风控：波动率 / 事件 各自减半 ──
    if st.get("position"):
        try:
            evt_sev = check_events(cfg, st, logfile)      # 0~1，无事件为 0
            st["event_pressure"] = evt_sev
        except Exception as ex:
            log(f"事件检查异常（按 0 处理）: {ex}", logfile)
            evt_sev = 0.0

        risk = check_order_risk(
            bar, evt_sev, st["position"],
            factor=max(cfg["vol_risk"]["atrp_factor"], 1.4),
            event_threshold=cfg.get("order_risk", {}).get("event_threshold", 0.7),
        )

        if risk["should_reduce"]:
            cur_lots = st["position"]["lots"]
            target = risk["target_lots"]
            cut = round((cur_lots - target) / 0.01) * 0.01
            if cut > 0:
                new_pos, pnl = broker.partial_close(
                    st["position"], cut, price, t, reason="risk_cut")
                st["equity"] += pnl
                st["daily_pnl"] += pnl
                st["position"] = new_pos

                # 标记已触发，避免重复
                if st["position"]:
                    if risk["vol_trigger"]:
                        st["position"]["vol_cut_done"] = True
                    if risk["event_trigger"]:
                        st["position"]["event_cut_done"] = True

                log(f"[持仓风控] {'; '.join(risk['reasons'])} → "
                    f"平掉 {cut:.2f} 手，剩余 {target:.2f} 手，pnl={pnl:.2f}", logfile)
                save_state(os.path.join(HERE, cfg["logging"]["state_file"]), st)

    # ── 平仓：信号消失 ──
    if st.get("position"):
        side = st["position"]["side"]
        if (side == 1 and not long_ok) or (side == -1 and not short_ok):
            st["position"], pnl = broker.close(st["position"], price, t, "signal_exit")
            st["equity"] += pnl
            st["daily_pnl"] += pnl
            log(f"[平仓] 信号消失 pnl={pnl:.2f} 权益={st['equity']:.2f}", logfile)

    # ── 开仓 ──
    daily_coeff = get_daily_coeff(cfg, st, logfile) if (long_ok or short_ok) else 1.0

    if not st.get("position") and (long_ok or short_ok) and new_bar:
        reasons = []

        # 1) 签字
        if not approved:
            reasons.append("未签字/已过期")

        # 2) ATRP 波动率拦截
        factor = max(cfg["vol_risk"]["atrp_factor"], 1.4)
        atrp_v = float(bar["atrp"])
        thr = float(bar["atrp_ma"]) * factor
        if atrp_v > thr:
            reasons.append(f"ATRP {atrp_v:.3f}% > MA×{factor} ({thr:.3f}%)")

        # 3) 总分析师：98% 以上暂停开仓
        if daily_coeff <= 0.0:
            reasons.append(f"总分析师百分位≥98% → 暂停开仓")

        if reasons:
            log(f"[拦截] {'; '.join(reasons)}", logfile)
        else:
            # 仓位计算
            vp = float(vol_pressure(pd.DataFrame([bar.to_dict()],
                                                 index=[bar_time]),
                                    factor=factor).iloc[0])
            ep = st.get("event_pressure", 0.0)
            pressure = cfg["vol_risk"]["weight_vol"] * vp + \
                cfg["event_layer"]["weight_event"] * ep
            coeff = max(0.0, 1.0 - pressure)
            # 总系数 1.0 / 0.5 / 0.0，和压力系数相乘，只减不加
            final_coeff = coeff * daily_coeff
            lots = np.floor(cfg["account"]["base_lot"] * final_coeff / 0.01) * 0.01
            lots = min(lots, cfg["account"]["base_lot"])

            if lots >= 0.01:
                side = 1 if long_ok else -1
                stop_dist = float(bar["atr"]) * 1.5
                stop = price - stop_dist if side == 1 else price + stop_dist
                st["position"] = broker.open(side, lots, price, stop, t)
                if st["position"]:
                    st["position"]["original_lots"] = lots
                    st["position"]["vol_cut_done"] = False
                    st["position"]["event_cut_done"] = False
                log(f"[开仓] {'多' if side==1 else '空'} {lots:.2f} 手 @ {price:.2f} "
                    f"(波动压力{vp:.2f} 事件压力{ep:.2f} "
                    f"压力系数{coeff:.2f} 总系数{daily_coeff:.1f})", logfile)
            else:
                log(f"[拦截] 算出的仓位 {lots:.2f} 不足最小手数", logfile)

    st["last_bar"] = str(bar_time)

    # ── 权益同步：mt5 模式从账户读真实值 ──
    if cfg["broker"]["mode"] == "mt5":
        try:
            st["equity"] = broker.equity()
            st["balance"] = broker.balance()
        except Exception:
            pass

    # ── 待审计的当日摘要 ──
    os.makedirs(os.path.join(HERE, cfg["logging"]["daily_dir"]), exist_ok=True)
    save_state(os.path.join(HERE, cfg["logging"]["state_file"]), st)


def main():
    cfg_path = os.path.join(HERE, "config.json")
    cfg = load_cfg(cfg_path)
    os.makedirs(os.path.join(HERE, cfg["logging"]["log_dir"]), exist_ok=True)
    logfile = os.path.join(HERE, cfg["logging"]["log_dir"],
                           f"run_{datetime.date.today():%Y%m%d}.log")
    state_path = os.path.join(HERE, cfg["logging"]["state_file"])

    st = load_state(state_path, cfg)
    from broker import make_broker
    broker = make_broker(cfg, HERE)

    log("=" * 60, logfile)
    log(f"启动  |  品种 {cfg['symbol']}  周期 {cfg['timeframe']}  "
        f"模式 {cfg['broker']['mode']}", logfile)
    log(f"签字状态: {'有效' if is_approved(st, cfg) else '未签字/已过期'}", logfile)
    log("=" * 60, logfile)

    interval = 15
    try:
        while True:
            try:
                run_once(cfg, st, broker, logfile)
            except Exception as ex:
                log(f"[错误] {type(ex).__name__}: {ex}", logfile)
                log(traceback.format_exc(), logfile)
            time.sleep(interval)
    except KeyboardInterrupt:
        log("收到停止信号，退出", logfile)
        save_state(state_path, st)


if __name__ == "__main__":
    main()



