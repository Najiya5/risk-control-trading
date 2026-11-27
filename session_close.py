# -*- coding: utf-8 -*-
"""休盘平仓：回测与实盘共用的时刻判断

纽约 17:00 收市。
  夏令时 EDT (UTC-4)：17:00 EDT = 21:00 UTC
  冬令时 EST (UTC-5)：17:00 EST = 22:00 UTC
"""

import datetime


def is_us_dst(d: datetime.date) -> bool:
    """美国夏令时：3 月第二个周日 ~ 11 月第一个周日"""
    y = d.year
    mar = datetime.date(y, 3, 1)
    while mar.weekday() != 6:      # 0=Mon, 6=Sun
        mar += datetime.timedelta(days=1)
    dst_start = mar + datetime.timedelta(days=7)

    nov = datetime.date(y, 11, 1)
    while nov.weekday() != 6:
        nov += datetime.timedelta(days=1)
    dst_end = nov

    return dst_start <= d < dst_end


def ny_close_utc(d: datetime.date) -> datetime.datetime:
    """当天纽约收市对应的 UTC 时刻（naive UTC）"""
    hour = 21 if is_us_dst(d) else 22
    return datetime.datetime(d.year, d.month, d.day, hour, 0)


def should_flat(ts, minutes_before: int = 10) -> bool:
    """
    给定一根 K 线的时间（naive，按 UTC 理解），
    判断是否落在「休盘前 N 分钟」窗口内。
    """
    if isinstance(ts, str):
        ts = datetime.datetime.fromisoformat(ts.replace("Z", ""))
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.astimezone(datetime.timezone.utc).replace(tzinfo=None)

    close_ = ny_close_utc(ts.date())
    start = close_ - datetime.timedelta(minutes=minutes_before)
    return start <= ts < close_


def trading_date(ts) -> datetime.date:
    """把时间归到「交易日期」（休盘前平仓，所以按休盘那天算）"""
    if isinstance(ts, str):
        ts = datetime.datetime.fromisoformat(ts.replace("Z", ""))
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return ts.date()
