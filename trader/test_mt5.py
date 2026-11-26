# -*- coding: utf-8 -*-
"""测试 MT5 连接（在普通 PowerShell 里跑，不走沙箱）

用法：
  C:\\Users\\26217\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe trader\\test_mt5.py

输出：
  1. 有没有连上客户端
  2. 账户信息（余额、净值、杠杆）
  3. 能不能读 XAUUSD 行情
  4. 能不能读 K 线
  5. 当前持仓
"""

import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[X] 没有安装 MetaTrader5 包")
    print("    安装：python -m pip install MetaTrader5")
    sys.exit(1)

print("=" * 60)
print("MetaTrader5 包版本:", mt5.__version__)
print("=" * 60)

# ── 1. 初始化 ──
print("\n[1] 连接 MT5 客户端")
ok = mt5.initialize()
if not ok:
    err = mt5.last_error()
    print(f"    [X] 连接失败: {err}")
    print()
    if err[0] == -10003:
        print("    原因：客户端没开，或者 MT5 没登录")
        print("    处理：打开 MT5 并登录账户后重试")
    elif err[0] == -10004:
        print("    原因：MT5 是 32 位版本，或者用管理员权限运行了")
    else:
        print("    处理：确认 MT5 客户端在运行")
    sys.exit(1)
print("    [OK] 已连接")

term = mt5.terminal_info()
if term:
    print(f"    客户端路径: {term.path}")
    print(f"    公司: {term.company}")
    print(f"    已连接服务器: {term.connected}")

# ── 2. 账户 ──
print("\n[2] 账户信息")
a = mt5.account_info()
if a is None:
    print("    [X] 读不到账户，可能没登录")
    mt5.shutdown()
    sys.exit(1)
print(f"    账号:     {a.login}")
print(f"    服务器:   {a.server}")
print(f"    名称:     {a.name}")
print(f"    币种:     {a.currency}")
print(f"    杠杆:     1:{a.leverage}")
print(f"    余额:     {a.balance:.2f}")
print(f"    净值:     {a.equity:.2f}")
print(f"    可用保证金: {a.margin_free:.2f}")
print(f"    账户类型: {'模拟' if a.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else '实盘/其他'}")

# ── 3. 品种与行情 ──
print("\n[3] XAUUSD 行情")
SYMBOL = "XAUUSD"
if not mt5.symbol_select(SYMBOL, True):
    print(f"    [!] {SYMBOL} 不可选，尝试其他名字")
    for name in ["XAUUSD.a", "XAUUSDm", "GOLD", "XAUUSD.r"]:
        if mt5.symbol_select(name, True):
            SYMBOL = name
            print(f"    改用: {SYMBOL}")
            break
    else:
        print("    [X] 找不到黄金品种，请在 MT5 市场报价里手动添加")
        mt5.shutdown()
        sys.exit(1)

si = mt5.symbol_info(SYMBOL)
print(f"    品种:     {si.name}")
print(f"    小数位:   {si.digits}")
print(f"    合约大小: {si.trade_contract_size}")
print(f"    最小手数: {si.volume_min}   步长: {si.volume_step}")
print(f"    点差:     {si.spread}")

tick = mt5.symbol_info_tick(SYMBOL)
if tick:
    print(f"    买价:     {tick.bid:.2f}")
    print(f"    卖价:     {tick.ask:.2f}")
    print(f"    点差:     {(tick.ask - tick.bid):.2f}")

# ── 4. K 线 ──
print("\n[4] H1 K 线")
rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 5)
if rates is None or len(rates) == 0:
    print(f"    [X] 读不到 K 线: {mt5.last_error()}")
else:
    import datetime
    print(f"    最近 {len(rates)} 根:")
    for r in rates[-5:]:
        t = datetime.datetime.fromtimestamp(r[0], datetime.timezone.utc)
        print(f"      {t:%Y-%m-%d %H:%M} UTC  "
              f"O={r[1]:.2f} H={r[2]:.2f} L={r[3]:.2f} C={r[4]:.2f}")

# ── 5. 持仓 ──
print("\n[5] 当前持仓")
pos = mt5.positions_get(symbol=SYMBOL)
if not pos:
    print("    （空仓）")
else:
    for p in pos:
        side = "多" if p.type == mt5.POSITION_TYPE_BUY else "空"
        print(f"    #{p.ticket} {side} {p.volume} 手  "
              f"开仓 {p.price_open:.2f}  现价 {p.price_current:.2f}  盈亏 {p.profit:.2f}")

mt5.shutdown()
print()
print("=" * 60)
print("[OK] 全部测试通过，MT5 可以正常使用")
print("=" * 60)
