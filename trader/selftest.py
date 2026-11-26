#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""自检：不启动主循环，只跑一次决策逻辑，看输出对不对

用法：python selftest.py
"""

import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "osma"))
sys.path.insert(0, os.path.join(ROOT, "risk"))

import main as M  # noqa: E402


def main():
    print("=" * 66)
    print("  自检（不启动主循环）")
    print("=" * 66)

    cfg = M.load_cfg(os.path.join(HERE, "config.json"))
    print(f"\n配置: {cfg['symbol']} {cfg['timeframe']}  模式={cfg['broker']['mode']}")
    print(f"      基础手数={cfg['account']['base_lot']}  合约乘数={cfg['account']['contract_size']}")
    print(f"      波动率权重={cfg['vol_risk']['weight_vol']}  事件权重={cfg['event_layer']['weight_event']}")
    print(f"      ATRP factor={cfg['vol_risk']['atrp_factor']}（硬下限 1.4）")
    print(f"      签字有效期={cfg['approval']['valid_hours']} 小时")

    # 1. 纽约休盘时刻
    print("\n[1] 纽约休盘时刻（UTC）")
    import datetime
    for d in [datetime.date(2026, 11, 24), datetime.date(2026, 6, 15)]:
        c = M.newyork_close_utc(d)
        print(f"    {d}: {c:%Y-%m-%d %H:%M} UTC  "
              f"（北京时间 {(c + datetime.timedelta(hours=8)):%H:%M}）")

    # 2. 指标计算
    print("\n[2] 指标计算")
    ind = M.compute_indicators(cfg, cfg["timeframe"])
    if ind is None:
        print("    ✗ 数据不足")
        return 1
    bar = ind.iloc[-1]
    print(f"    最新 K 线: {ind.index[-1]}")
    print(f"    close={bar['close']:.2f}  ATR={bar['atr']:.2f}")
    print(f"    ATRP={bar['atrp']:.3f}%  阈值(MA×{cfg['vol_risk']['atrp_factor']})={bar['atrp_ma']*max(cfg['vol_risk']['atrp_factor'],1.4):.3f}%")
    over = bar["atrp"] > bar["atrp_ma"] * max(cfg["vol_risk"]["atrp_factor"], 1.4)
    print(f"    → ATRP {'超过阈值（会拦截）' if over else '未超阈值（正常）'}")
    print(f"    OsMA={bar['osma']:.4f}  signal={bar['signal']:.4f}")
    long_ok = bar["osma"] > 0 and bar["signal"] > 0
    short_ok = bar["osma"] < 0 and bar["signal"] < 0
    print(f"    → 信号: {'多' if long_ok else ('空' if short_ok else '无')}")

    # 3. 历史拦截统计
    print("\n[3] 历史上 ATRP 拦截频率（最近 500 根）")
    n = len(ind)
    over_n = (ind["atrp"] > ind["atrp_ma"] * max(cfg["vol_risk"]["atrp_factor"], 1.4)).sum()
    print(f"    最近 {n} 根里，ATRP 越线 {over_n} 根 ({over_n/n*100:.1f}%)")

    # 4. 状态文件
    print("\n[4] 状态文件")
    sp = os.path.join(HERE, cfg["logging"]["state_file"])
    if os.path.exists(sp):
        st = M.load_state(sp, cfg)
        print(f"    ✓ 已存在")
        print(f"      签字: {st.get('approved_until') or '未签字'}")
        print(f"      通过检查: {'是' if M.is_approved(st, cfg) else '否'}")
        print(f"      权益: {st.get('equity', 0):.2f}")
        print(f"      持仓: {st.get('position') or '空仓'}")
    else:
        print(f"    （还没有 state.json，首次运行 main.py 会创建）")

    # 5. 事件层
    print("\n[5] 事件层")
    try:
        import event_layer as EL
        news = EL.fetch_news()
        events = EL.filter_events(news, only_important=True, max_items=3)
        print(f"    ✓ 金十接口正常，{len(news)} 条快讯，命中 {len(events)} 条事件")
        models = [m for m in cfg["event_layer"]["models"] if m.get("enabled") and m.get("api_key")]
        print(f"    可用模型: {[m['name'] for m in models] or '（未配置 API key，事件层会降级）'}")
    except Exception as e:
        print(f"    ✗ 事件层异常: {type(e).__name__}: {e}")

    print("\n" + "=" * 66)
    print("  自检完成")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
