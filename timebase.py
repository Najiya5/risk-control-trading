# -*- coding: utf-8 -*-
"""时间基准归一化

两套数据时间基准不同：
  Yahoo Finance  → UTC
  MT4 券商导出   → 服务器时间 (EET = UTC+2, 夏令时 EEST = UTC+3)

回测里统一转成 UTC 再做休盘判断。

⚠ Tickmill 的服务器时区我没从券商文档核实过，
   是按"MT4 常见做法 + 与 UTC 数据的价格对齐"推断的。
"""

import pandas as pd


def to_utc(index: pd.DatetimeIndex, source="mt4") -> pd.DatetimeIndex:
    """
    把时间索引转成 UTC（返回 naive 的 UTC 时间，方便和 session_close 配合）

    source:
      "utc"  —— Yahoo 等，原样不动
      "mt4"  —— 服务器时间，减 2 小时（EET）；夏令时减 3 小时（EEST）
    """
    idx = pd.DatetimeIndex(index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
        return idx

    if source == "utc":
        return idx

    # MT4：按夏令时判断偏移
    # 用 pandas 的时区库简化为：3 月最后周日 ~ 10 月最后周日 = EEST(UTC+3)，其余 EET(UTC+2)
    out = []
    for t in idx:
        y = t.year
        # 欧洲夏令时：3 月最后一个周日 01:00 UTC ~ 10 月最后一个周日 01:00 UTC
        mar_last = pd.Timestamp(y, 3, 31) - pd.Timedelta(days=(pd.Timestamp(y, 3, 31).weekday() + 1) % 7)
        oct_last = pd.Timestamp(y, 10, 31) - pd.Timedelta(days=(pd.Timestamp(y, 10, 31).weekday() + 1) % 7)
        is_eest = mar_last <= pd.Timestamp(t) < oct_last
        offset = 3 if is_eest else 2
        out.append(pd.Timestamp(t) - pd.Timedelta(hours=offset))
    return pd.DatetimeIndex(out)


def infer_source(path: str) -> str:
    """按文件路径推断时间基准"""
    p = str(path).lower()
    if "yahoo" in p or "/data/" in p.replace("\\", "/"):
        return "utc"
    return "mt4"
