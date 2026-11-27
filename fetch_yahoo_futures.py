# -*- coding: utf-8 -*-
"""从 Yahoo Finance 抓取期货连续合约历史数据

支持的周期：
  1m   —— 最多 7 天
  5m   —— 最多 60 天
  15m  —— 最多 60 天
  1h   —— 最多 730 天（2 年）
  1d   —— 长期

输出到 data/yahoo/<代码>_<周期>.csv
"""

import os
import json
import time
import urllib.request
import urllib.error
import io

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "yahoo")
os.makedirs(OUT, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 期货连续合约
SYMBOLS = {
    "SI=F": ("SILVER", "白银"),
    "GC=F": ("GOLD", "黄金"),
    "CL=F": ("WTI", "原油WTI"),
    "NG=F": ("NATGAS", "天然气"),
    "HG=F": ("COPPER", "铜"),
    "BZ=F": ("BRENT", "布伦特"),
    "PL=F": ("PLATINUM", "铂金"),
}

# 周期 → (Yahoo interval, range)
TFS = [
    ("1h",  "1h",  "730d"),
    ("5m",  "5m",  "60d"),
    ("15m", "15m", "60d"),
    ("1d",  "1d",  "10y"),
]


def fetch(sym, interval, rng, tries=3):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?interval={interval}&range={rng}&includePrePost=false")
    h = {"User-Agent": UA, "Accept": "application/json"}

    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data
        except Exception as e:
            if attempt == tries - 1:
                return {"_error": f"{type(e).__name__}: {str(e)[:120]}"}
            time.sleep(2)


def to_csv(data, path):
    """Yahoo chart 结构 → OHLCV CSV"""
    try:
        res = data["chart"]["result"][0]
    except Exception as e:
        return 0, f"结构异常: {e}"

    ts = res.get("timestamp") or []
    q = (res.get("indicators", {}).get("quote") or [{}])[0]
    o = q.get("open") or []
    h = q.get("high") or []
    l = q.get("low") or []
    c = q.get("close") or []
    v = q.get("volume") or []

    if not ts:
        return 0, "无数据"

    n = min(len(ts), len(o), len(h), len(l), len(c))
    rows = []
    for i in range(n):
        if None in (o[i], h[i], l[i], c[i]):
            continue
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts[i]))
        vol = v[i] if i < len(v) and v[i] is not None else 0
        rows.append((t, o[i], h[i], l[i], c[i], vol))

    if not rows:
        return 0, "全部为空"

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write("time,open,high,low,close,volume\n")
        for r in rows:
            f.write(f"{r[0]},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]}\n")

    return len(rows), None


def main():
    print("=" * 84)
    print("  Yahoo Finance 期货数据抓取")
    print("=" * 84)
    print(f"  输出目录: {OUT}\n")

    print(f"{'品种':<10}{'代码':<7}{'周期':<6}{'根数':>8}{'起':>13}{'止':>13}  状态")
    print("-" * 84)

    total = 0
    for sym, (short, cn) in SYMBOLS.items():
        for tf_name, interval, rng in TFS:
            data = fetch(sym, interval, rng)
            if "_error" in data:
                print(f"{cn:<10}{sym:<7}{tf_name:<6}{'':>8}{'':>13}{'':>13}  ✗ {data['_error'][:30]}")
                continue

            path = os.path.join(OUT, f"{short}_{tf_name}.csv")
            n, err = to_csv(data, path)
            if n == 0:
                print(f"{cn:<10}{sym:<7}{tf_name:<6}{'':>8}{'':>13}{'':>13}  ✗ {err}")
                continue

            # 读首尾时间
            with io.open(path, encoding="utf-8") as f:
                lines = f.read().strip().split("\n")
            t0 = lines[1].split(",")[0][:10]
            t1 = lines[-1].split(",")[0][:10]
            print(f"{cn:<10}{sym:<7}{tf_name:<6}{n:>8}{t0:>13}{t1:>13}  ✓")
            total += 1
            time.sleep(0.6)

    print()
    print(f"共 {total} 个文件")


if __name__ == "__main__":
    main()
