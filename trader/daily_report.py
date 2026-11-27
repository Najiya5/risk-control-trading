# -*- coding: utf-8 -*-
"""每日战报生成器

每晚 20:00 生成，内容：
  1. 今日交易（开平笔数、盈亏、胜率）
  2. 今日事件判断（LLM 对新闻的判断和理由）
  3. 未来三天重要数据公布（金十财经日历）
  4. 当前风控状态（ATRP 触发次数、总系数等）

输出到 reports/每日战报_YYYYMMDD.txt
签字页必须先读过这个文件才能签字。
"""

import os
import io
import json
import datetime

import pandas as pd

ROOT = r"C:\Users\26217\Documents\deepseek-harness\default-workspace"
TR = os.path.join(ROOT, "trader")


def load_trades_csv(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        return df
    except Exception:
        return pd.DataFrame()


def today_trades(trade_log, date_str):
    """筛出今天的交易（open_time 或 close_time 落在今天）"""
    df = load_trades_csv(trade_log)
    if df.empty:
        return df
    # 按 close_time 归类：一笔交易算在【平仓那天】
    # （22:xx 开、次日 01:xx 平的，算次日）
    if "close_time" not in df.columns:
        return df.iloc[0:0]
    s = df["close_time"].astype(str).str[:10]
    return df[s == date_str]


def load_event_log(path):
    """读事件日志（每行 JSON 或 CSV 格式）"""
    if not os.path.exists(path):
        return []
    out = []
    try:
        with io.open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def fetch_calendar(days_ahead=3, cfg=None, state=None):
    """
    拉未来 N 天的财经日历。

    金十优先，失败自动降级到备用源。
    所有技术问题都会写日志（见 calendar_source.py）。
    """
    try:
        import calendar_source
        events, info = calendar_source.fetch_calendar(
            days_ahead, cfg=cfg, st=state)
        return events, info
    except Exception as ex:
        return [], dict(source=None, jin10_ok=False,
                        errors=[f"{type(ex).__name__}: {ex}"],
                        note="日历模块异常")


def gold_relevant(ev):
    """
    判断这条数据是否可能影响黄金。

    现在的数据源已经按 USD + 中高影响筛过了，
    所以 USD 的一律保留；其他货币看关键词。
    """
    if ev.get("country") == "USD":
        return ev.get("star", 0) >= 2
    keys = ["FOMC", "CPI", "Fed", "Powell", "NFP", "GDP", "Rate", "ECB", "BoJ"]
    text = ev.get("name", "") + ev.get("country", "")
    return any(k in text for k in keys) or ev.get("star", 0) >= 3


def build_report(cfg, state, date_str=None):
    """生成战报文本"""
    if date_str is None:
        date_str = datetime.date.today().strftime("%Y-%m-%d")

    L = []
    add = L.append

    add("=" * 66)
    add(f"  每日战报   {date_str}")
    add("=" * 66)
    add("")

    # ═══ 1. 今日交易 ═══
    add("【一、今日交易】")
    add("-" * 66)
    trade_log = os.path.join(TR, cfg["logging"]["trade_log"])
    tr = today_trades(trade_log, date_str)

    if tr.empty:
        add("  今日无成交。")
    else:
        pnl_col = "pnl" if "pnl" in tr.columns else None
        n = len(tr)
        if pnl_col:
            total = tr[pnl_col].sum()
            wins = tr[tr[pnl_col] > 0]
            losses = tr[tr[pnl_col] < 0]
            wr = len(wins) / n * 100 if n else 0
            pf = (wins[pnl_col].sum() / -losses[pnl_col].sum()) if len(losses) and losses[pnl_col].sum() != 0 else float("inf")
            add(f"  成交笔数：{n}")
            add(f"  今日盈亏：{total:+,.2f} USD")
            add(f"  胜率：{wr:.1f}%  （{len(wins)} 盈 / {len(losses)} 亏）")
            add(f"  盈利因子：{pf:.2f}")
            add("")
            add("  明细：")
            for _, r in tr.iterrows():
                side = "多" if str(r.get("side")) == "1" else "空"
                add(f"    {str(r.get('open_time',''))[:19]} → {str(r.get('close_time',''))[:19]}  "
                    f"{side} {r.get('lots','')}手  "
                    f"{r.get('entry_price','')} → {r.get('exit_price','')}  "
                    f"{float(r.get('pnl', 0)):+.2f}  [{r.get('reason','')}]")
        else:
            add(f"  成交笔数：{n}")

    add("")

    # ═══ 2. 风控状态 ═══
    add("【二、风控状态】")
    add("-" * 66)
    equity = state.get("equity", 0)
    balance = state.get("balance", 0)
    add(f"  账户权益：{equity:,.2f} USD")
    add(f"  账户余额：{balance:,.2f} USD")
    add(f"  今日已实现盈亏：{state.get('daily_pnl', 0):+,.2f} USD")

    pos = state.get("position")
    if pos:
        side = "多" if pos.get("side") == 1 else "空"
        add(f"  当前持仓：{side} {pos.get('lots', 0):.2f} 手 @ {pos.get('entry_price', 0):.2f}")
    else:
        add("  当前持仓：空仓")

    da = state.get("_da_detail")
    if da:
        add(f"  总分析师：昨日百分位 {da.get('pct', 0):.1f}% → 系数 {da.get('coeff', 1.0):.1f}")
        add(f"              {da.get('reason', '')}")

    add("")

    # ═══ 3. 事件判断 ═══
    add("【三、今日事件判断】")
    add("-" * 66)
    ev_log = os.path.join(TR, cfg["logging"]["event_log"])
    events = [e for e in load_event_log(ev_log) if str(e.get("date", date_str))[:10] == date_str]
    if not events:
        add("  今日无事件判断记录。")
    else:
        add(f"  共 {len(events)} 条判断：")
        for e in events[:20]:
            add(f"    [{e.get('time','')}] severity={e.get('severity',0):.2f} "
                f"impact={e.get('impact',0):+.2f}  {e.get('title','')}")
            if e.get("reason"):
                add(f"        理由：{e['reason']}")

    add("")

    # ═══ 4. 未来三天数据 ═══
    add("【四、未来三天重要数据公布】")
    add("-" * 66)
    try:
        cal, cal_info = fetch_calendar(3, cfg=cfg, state=state)
        rel = [e for e in cal if gold_relevant(e)]

        src_tag = {"jin10": "金十", "backup": "备用源(showmytrades)", None: "无"}.get(
            cal_info.get("source"), cal_info.get("source"))
        if cal_info.get("source"):
            add(f"  数据源：{src_tag}")
            if cal_info.get("errors"):
                for er in cal_info["errors"]:
                    add(f"    ⚠ {er}")
        if cal_info.get("source") is None:
            add("  （所有日历数据源不可用，详见 logs/calendar_source.log）")
        elif not rel:
            add("  （未来三天无 USD 中高影响数据 —— 节假期或数据空窗属正常）")
        else:
            cur_day = None
            for e in rel:
                if e["date"] != cur_day:
                    cur_day = e["date"]
                    add(f"  ▸ {cur_day}")
                add(f"    {e['time']:<8} {'★' * max(e['star'], 1):<4} "
                    f"{e['country']:<6} {e['name']}")
    except Exception as ex:
        add(f"  （日历接口异常：{type(ex).__name__} —— 不影响交易）")

    add("")
    add("=" * 66)
    add(f"  生成时间：{datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    add("=" * 66)

    return "\n".join(L)


def save_report(cfg, state, date_str=None):
    """生成并保存战报，返回文件路径"""
    if date_str is None:
        date_str = datetime.date.today().strftime("%Y-%m-%d")

    text = build_report(cfg, state, date_str)

    reports_dir = os.path.join(TR, cfg["logging"]["daily_dir"])
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, f"战报_{date_str.replace('-', '')}.txt")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


if __name__ == "__main__":
    cfg = json.load(io.open(os.path.join(TR, "config.json"), encoding="utf-8-sig"))
    sp = os.path.join(TR, cfg["logging"]["state_file"])
    state = json.load(io.open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    p = save_report(cfg, state)
    print("战报已生成:", p)
    print()
    print(io.open(p, encoding="utf-8").read())
