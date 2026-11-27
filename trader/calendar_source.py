# -*- coding: utf-8 -*-
"""财经日历数据源

主源：金十 cdn-rili（带缓存，命中率高）
备源：showmytrades 公开 API（免费，无需 key）

降级策略：
  - 每次先试金十
  - 金十失败 → 用备用源，同时记日志
  - 金十挂掉后，冷却期内不再尝试（每天只探一次）
  - 所有失败都写进日志，不静默
"""

import os
import io
import json
import datetime
import urllib.request
import urllib.error

# 金十失败后的冷却时间（秒）。用户要求：每天检查一次是否修复
JIN10_RETRY_COOLDOWN = 24 * 3600


def _log(cfg, level, msg):
    """技术问题写进运行日志 + 单独一份数据源日志"""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] [日历] {msg}"

    # 运行日志
    try:
        logdir = os.path.join(HERE, cfg.get("logging", {}).get("log_dir", "logs"))
        os.makedirs(logdir, exist_ok=True)
        with io.open(os.path.join(logdir, f"run_{datetime.date.today():%Y%m%d}.log"),
                     "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

    # 数据源专用日志（便于排查）
    try:
        fpath = os.path.join(os.path.dirname(HERE), "logs", "calendar_source.log")
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with io.open(fpath, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

    print(line, flush=True)


HERE = os.path.dirname(os.path.abspath(__file__))

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ══════════════════════════════════════════════════
# 主源：金十
# ══════════════════════════════════════════════════

def fetch_jin10(days_ahead=3):
    """
    金十财经日历。
    返回 (events, error)：成功时 error 为 None。
    """
    events = []
    today = datetime.date.today()
    err = None

    for delta in range(0, days_ahead + 1):
        d = today + datetime.timedelta(days=delta)
        url = (f"https://cdn-rili.jin10.com/web_data/{d.year}/daily/"
               f"{d.month:02d}/{d.day:02d}/economics.json")
        H = {
            "User-Agent": UA,
            "Referer": "https://rili.jin10.com/",
            "Accept": "application/json, text/plain, */*",
        }
        try:
            req = urllib.request.Request(url, headers=H)
            with urllib.request.urlopen(req, timeout=12) as r:
                raw = r.read()
            if len(raw) < 5:
                continue
            data = json.loads(raw.decode("utf-8", errors="replace"))
            if not isinstance(data, list):
                continue
            for it in data:
                name = (it.get("name") or "").strip()
                if not name:
                    continue
                star = it.get("star", 0)
                try:
                    star = int(star)
                except Exception:
                    star = 0
                events.append(dict(
                    date=str(d),
                    time=str(it.get("time", "")),
                    name=name[:60],
                    star=star,
                    country=str(it.get("country", "")),
                    actual=str(it.get("actual", "") or ""),
                    forecast=str(it.get("forecast", "") or ""),
                    previous=str(it.get("previous", "") or ""),
                    source="jin10",
                ))
        except Exception as ex:
            err = f"{type(ex).__name__}: {str(ex)[:120]}"
            break

    return events, err


# ══════════════════════════════════════════════════
# 备源：showmytrades
# ══════════════════════════════════════════════════

def fetch_backup(days_ahead=3):
    """备用源。返回 (events, error)"""
    url = ("https://showmytrades.com/api/public/calendar/v1"
           f"?currency=USD&impact=high,medium&days={days_ahead}&format=json")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as ex:
        return [], f"{type(ex).__name__}: {str(ex)[:120]}"

    events = []
    for e in data.get("events", []) or []:
        t = str(e.get("time", ""))
        if not t:
            continue
        events.append(dict(
            date=t[:10],
            time=t[11:16],
            name=str(e.get("title", ""))[:60],
            star={"high": 3, "medium": 2, "low": 1}.get(str(e.get("impact", "")), 0),
            country=str(e.get("currency", "")),
            actual=str(e.get("actual", "") or ""),
            forecast=str(e.get("forecast", "") or ""),
            previous=str(e.get("previous", "") or ""),
            source="backup",
        ))
    return events, None


# ══════════════════════════════════════════════════
# 统一入口
# ══════════════════════════════════════════════════

def fetch_calendar(days_ahead=3, cfg=None, st=None):
    """
    拉财经日历。金十优先，失败降级。

    返回 (events, info)
      info = {source, jin10_ok, errors, note}
    """
    cfg = cfg or {}
    now = datetime.datetime.now()

    # 金十冷却判断
    skip_jin10 = False
    if st is not None:
        last_fail = st.get("_cal_jin10_failed_at")
        if last_fail:
            try:
                t = datetime.datetime.fromisoformat(last_fail)
                if (now - t).total_seconds() < JIN10_RETRY_COOLDOWN:
                    skip_jin10 = True
            except Exception:
                pass

    errors = []

    # ── 主源 ──
    if not skip_jin10:
        _log(cfg, "INFO", "尝试金十日历")
        ev, err = fetch_jin10(days_ahead)
        if err is None:
            _log(cfg, "INFO", f"金十成功，{len(ev)} 条")
            # 恢复成功 → 清掉失败标记
            if st is not None:
                st.pop("_cal_jin10_failed_at", None)
                st["_cal_last_source"] = "jin10"
            return ev, dict(source="jin10", jin10_ok=True, errors=[], note="")
        # 失败
        _log(cfg, "ERROR", f"金十失败：{err}")
        errors.append(f"jin10: {err}")
        if st is not None:
            st["_cal_jin10_failed_at"] = now.isoformat()
    else:
        _log(cfg, "WARN", "金十仍在冷却期（24h 内失败过），跳过")
        errors.append("jin10: 冷却中")

    # ── 备源 ──
    _log(cfg, "INFO", "降级到备用源 showmytrades")
    ev, err = fetch_backup(days_ahead)
    if err is not None:
        _log(cfg, "ERROR", f"备用源也失败：{err}")
        errors.append(f"backup: {err}")
        return [], dict(source=None, jin10_ok=False, errors=errors,
                        note="所有数据源都失败")

    _log(cfg, "INFO", f"备用源成功，{len(ev)} 条")
    if st is not None:
        st["_cal_last_source"] = "backup"
    return ev, dict(source="backup", jin10_ok=False, errors=errors,
                    note="金十不可用，已降级")


def reset_jin10_cooldown(st):
    """手动清除金十冷却（想立刻重试时用）"""
    if st is not None:
        st.pop("_cal_jin10_failed_at", None)
