# -*- coding: utf-8 -*-
"""持仓风控单元测试"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "risk"))

import pandas as pd
from order_risk import check_order_risk

print("=" * 62)
print("  持仓风控单元测试")
print("=" * 62)


def mk(atrp, ma, lots=1.0, orig=1.0, vcd=False, ecd=False):
    row = pd.Series({"atrp": atrp, "atrp_ma": ma})
    return row, dict(lots=lots, original_lots=orig,
                     vol_cut_done=vcd, event_cut_done=ecd)


ok = 0

# 1
row, pos = mk(0.10, 0.15)
r = check_order_risk(row, 0.3, pos)
print(f"\n[1] 都不触发")
print(f"    ATRP 0.10 vs 阈值 0.15×1.4=0.210 ；事件 0.3 < 0.7")
print(f"    -> 减仓={r['should_reduce']}  目标手数={r['target_lots']}")
assert not r["should_reduce"]
ok += 1

# 2
row, pos = mk(0.30, 0.15)
r = check_order_risk(row, 0.3, pos)
print(f"\n[2] 波动率触发")
print(f"    ATRP 0.30 > 0.210")
print(f"    -> 减仓={r['should_reduce']}  目标手数={r['target_lots']}")
print(f"    原因: {r['reasons']}")
assert r["should_reduce"] and abs(r["target_lots"] - 0.5) < 1e-9
ok += 1

# 3
row, pos = mk(0.10, 0.15)
r = check_order_risk(row, 0.8, pos)
print(f"\n[3] 事件触发")
print(f"    事件 0.8 >= 0.7")
print(f"    -> 减仓={r['should_reduce']}  目标手数={r['target_lots']}")
assert r["should_reduce"] and abs(r["target_lots"] - 0.5) < 1e-9
ok += 1

# 4
row, pos = mk(0.30, 0.15)
r = check_order_risk(row, 0.9, pos)
print(f"\n[4] 两条同时触发 → 归零")
print(f"    -> 减仓={r['should_reduce']}  目标手数={r['target_lots']}")
print(f"    原因: {r['reasons']}")
assert abs(r["target_lots"]) < 1e-9
ok += 1

# 5
row, pos = mk(0.30, 0.15, lots=0.5, vcd=True)
r = check_order_risk(row, 0.3, pos)
print(f"\n[5] 波动率已减过，不重复")
print(f"    vol_cut_done=True，持仓 0.5")
print(f"    -> 减仓={r['should_reduce']}")
assert not r["should_reduce"]
ok += 1

# 6
row1, pos = mk(0.30, 0.15)
r1 = check_order_risk(row1, 0.3, pos)
pos["lots"] = r1["target_lots"]
pos["vol_cut_done"] = True
print(f"\n[6] 先波动率减半（剩 {pos['lots']}），再事件减半")
row2, _ = mk(0.10, 0.15)
r2 = check_order_risk(row2, 0.9, pos)
print(f"    -> 目标手数={r2['target_lots']}（应在 0.5 基础上再减半）")
assert abs(r2["target_lots"] - 0.25) < 1e-9
ok += 1

# 7 无事件
row, pos = mk(0.10, 0.15)
r = check_order_risk(row, None, pos)
print(f"\n[7] 事件为 None（事件层关闭）")
print(f"    -> 减仓={r['should_reduce']}")
assert not r["should_reduce"]
ok += 1

print("\n" + "=" * 62)
print(f"  ✓ {ok}/7 全部通过")
print("=" * 62)
