# -*- coding: utf-8 -*-
"""诊断：模拟一轮完整的决策，不连 MT5、不下单

用本地 M5 CSV 当数据，跑一遍 run_once 的核心逻辑，
看指标算得对不对、决策分支会不会崩。
"""

import sys
import os
import io
import json
import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "osma"))
sys.path.insert(0, os.path.join(ROOT, "risk"))


def main():
    import pandas as pd
    import numpy as np
    from vol_event_layer import atrp, vol_pressure
    from indicator import osma

    print("=" * 66)
    print("  决策逻辑诊断（不连 MT5 / 不下单）")
    print("=" * 66)

    # 读配置
    with io.open(os.path.join(HERE, "config.json"), encoding="utf-8-sig") as f:
        cfg = json.load(f)
    print(f"\n周期={cfg['timeframe']}  数据源={cfg['market_data']['source']}  "
          f"模式={cfg['broker']['mode']}")

    # 用本地 M5 CSV 模拟（MT4 导出的）
    csvp = os.path.join(ROOT, "XAUUSD_M5_Tickmill-DemoUK.csv")
    df = pd.read_csv(csvp, parse_dates=["time"]).set_index("time").sort_index()
    df = df.tail(1000)
    print(f"\n[1] 数据：{len(df)} 根  {df.index[0]} -> {df.index[-1]}")

    # 指标
    print("\n[2] 指标计算")
    ind = atrp(df, cfg["vol_risk"]["atr_period_1"], cfg["vol_risk"]["atr_period_2"])
    s = cfg["strategy"]
    ind = ind.join(osma(df, s["fast_ema"], s["slow_ema"], s["signal_ema"],
                        s["weight_body"], s["weight_shadow"]),
                   how="inner", rsuffix="_o")
    ind = ind.dropna(subset=["atrp", "atrp_ma", "osma", "signal"])
    if len(ind) == 0:
        print("    [X] 指标全为空")
        return 1

    bar = ind.iloc[-1]
    print(f"    最新: {ind.index[-1]}")
    print(f"    close={bar['close']:.2f}  ATR={bar['atr']:.2f}")
    print(f"    ATRP={bar['atrp']:.4f}%  阈值={bar['atrp_ma']*factor:.4f}%")
    print(f"    OsMA={bar['osma']:.4f}  signal={bar['signal']:.4f}")

    # 决策
    print("\n[3] 决策模拟")
    long_ok = bool(bar["osma"] > 0 and bar["signal"] > 0)
    short_ok = bool(bar["osma"] < 0 and bar["signal"] < 0)
    print(f"    信号: {'多' if long_ok else ('空' if short_ok else '无')}")

    factor = max(cfg["vol_risk"]["atrp_factor"], 1.4)
    atrp_over = bar["atrp"] > bar["atrp_ma"] * factor
    print(f"    ATRP 拦截: {'是' if atrp_over else '否'}")

    # 仓位压力计算（这是 run_once 里最容易出错的代码）
    print("\n[4] 仓位压力计算")
    try:
        one = pd.DataFrame([bar.to_dict()], index=[ind.index[-1]])
        vp = float(vol_pressure(one, factor=factor).iloc[0])
        print(f"    波动压力 vol_pressure = {vp:.4f}")
    except Exception as e:
        print(f"    [X] vol_pressure 出错: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

    ep = 0.0
    pressure = cfg["vol_risk"]["weight_vol"] * vp + \
        cfg["event_layer"]["weight_event"] * ep
    coeff = max(0.0, 1.0 - pressure)
    lots = np.floor(cfg["account"]["base_lot"] * coeff / 0.01) * 0.01
    lots = min(lots, cfg["account"]["base_lot"])
    print(f"    事件压力 = {ep:.2f}")
    print(f"    合成压力 = {pressure:.4f}")
    print(f"    系数     = {coeff:.4f}")
    print(f"    手数     = {lots:.2f}")

    # 检查 min/max 手数约束
    print("\n[5] 手数约束（MT5 要求 0.01~100，步长 0.01）")
    ok = 0.01 <= lots <= 100.0 and abs(lots * 100 - round(lots * 100)) < 1e-9
    print(f"    {'[OK]' if ok else '[X]'} 手数 {lots}")

    # 回放最近 200 根，统计信号切换次数
    print("\n[6] 最近 200 根的信号切换频率")
    tail = ind.tail(200)
    sig_series = np.where((tail.osma > 0) & (tail.signal > 0), 1,
                          np.where((tail.osma < 0) & (tail.signal < 0), -1, 0))
    changes = int((np.diff(sig_series) != 0).sum())
    print(f"    切换 {changes} 次 / {len(tail)} 根 K 线")
    print(f"    → 按 M5 算，约等于每 {len(tail)/max(changes,1):.1f} 根换一次信号")

    print("\n" + "=" * 66)
    print("  诊断完成")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
