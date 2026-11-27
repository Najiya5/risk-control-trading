# -*- coding: utf-8 -*-
"""7 个期货品种的规格参数

⚠ 这些参数是我按常识估的，不是从券商官网查的。
   回测前请确认，尤其是点差——它直接决定结果。
"""

SPECS = {
    # 短期 文件名: 合约规格
    "GOLD": dict(
        name="黄金", yahoo="GC=F", symbol="XAUUSD",
        contract=100.0,       # 1 手 = 100 盎司
        tick=0.1,             # 最小变动
        spread_usd=0.10,      # 点差（美元/盎司）— CME GC 约 0.1
        real_symbol="GC",     # CME 代码
    ),
    "SILVER": dict(
        name="白银", yahoo="SI=F", symbol="XAGUSD",
        contract=5000.0,      # 1 手 = 5000 盎司
        tick=0.005,
        spread_usd=0.005,     # 点差（美元/盎司）
        real_symbol="SI",
    ),
    "WTI": dict(
        name="原油WTI", yahoo="CL=F", symbol="XTIUSD",
        contract=1000.0,      # 1 手 = 1000 桶
        tick=0.01,
        spread_usd=0.01,      # 美元/桶
        real_symbol="CL",
    ),
    "BRENT": dict(
        name="布伦特", yahoo="BZ=F", symbol="BRENT",
        contract=1000.0,
        tick=0.01,
        spread_usd=0.02,
        real_symbol="BZ",
    ),
    "NATGAS": dict(
        name="天然气", yahoo="NG=F", symbol="NAT.GAS",
        contract=10000.0,     # 1 手 = 10000 MMBtu
        tick=0.001,
        spread_usd=0.003,     # 美元/MMBtu
        real_symbol="NG",
    ),
    "COPPER": dict(
        name="铜", yahoo="HG=F", symbol="COPPER",
        contract=25000.0,     # 1 手 = 25000 磅
        tick=0.0005,
        spread_usd=0.001,     # 美元/磅
        real_symbol="HG",
    ),
    "PLATINUM": dict(
        name="铂金", yahoo="PL=F", symbol="",
        contract=50.0,        # 1 手 = 50 盎司
        tick=0.1,
        spread_usd=0.5,
        real_symbol="PL",
    ),
}


def round_trip_cost_usd(key):
    """一手往返成本（美元）"""
    s = SPECS[key]
    return s["spread_usd"] * s["contract"]
