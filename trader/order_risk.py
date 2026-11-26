# -*- coding: utf-8 -*-
"""持仓风控：对已有仓位执行减半

两条规则各占 0.5 权重：
  A) 波动率：ATRP > MA × factor  → 平掉当前持仓的一半
  B) 事件：  LLM 平均 severity ≥ threshold → 平掉当前持仓的一半

每次触发平掉「当前持仓」的一半（连乘）。
  1 手 → 波动率触发 → 0.5 → 事件触发 → 0.25 → 波动率再触发 → 0.125 ...

两条规则各自只能触发一次（避免同一原因重复砍）。
两条同时触发 → 直接归零。

减仓只影响当前持仓，下次开仓重新满仓。
"""


def check_order_risk(ind_row, event_severity, position,
                     factor=1.4, event_threshold=0.7, cut_ratio=0.5):
    """
    判断当前持仓要不要减。

    参数：
      ind_row        当前 K 线（含 atrp / atrp_ma）
      event_severity 当前事件平均严重度（0~1），无事件传 None 或 0
      position       持仓 dict：lots / vol_cut_done / event_cut_done
      factor         ATRP 阈值倍数（硬下限 1.4）
      event_threshold 事件严重度门槛
      cut_ratio      每次平掉的比例（默认 0.5）

    返回：
      dict(should_reduce, target_lots, reasons, vol_trigger, event_trigger)
    """
    lots = float(position.get("lots", 0.0))
    if lots <= 0:
        return dict(should_reduce=False, target_lots=lots, reasons=[],
                    vol_trigger=False, event_trigger=False)

    vol_done = bool(position.get("vol_cut_done", False))
    evt_done = bool(position.get("event_cut_done", False))

    reasons = []

    # A) 波动率
    vol_trigger = False
    try:
        atrp_v = float(ind_row["atrp"])
        thr = float(ind_row["atrp_ma"]) * factor
        if atrp_v > thr and not vol_done:
            vol_trigger = True
            reasons.append(f"ATRP {atrp_v:.4f}% > MA×{factor} ({thr:.4f}%)")
    except Exception:
        pass

    # B) 事件
    evt_trigger = False
    if (event_severity is not None
            and float(event_severity) >= event_threshold
            and not evt_done):
        evt_trigger = True
        reasons.append(f"事件严重度 {float(event_severity):.2f} ≥ {event_threshold}")

    if not vol_trigger and not evt_trigger:
        return dict(should_reduce=False, target_lots=lots, reasons=[],
                    vol_trigger=False, event_trigger=False)

    # 两条同时首次触发 → 归零
    if vol_trigger and evt_trigger:
        return dict(should_reduce=True, target_lots=0.0,
                    reasons=reasons + ["两条规则同时触发 → 归零"],
                    vol_trigger=True, event_trigger=True)

    # 单条触发 → 平掉当前持仓的一半
    target = lots * (1.0 - cut_ratio)
    target = round(target / 0.01) * 0.01
    if target < 0.01:
        target = 0.0

    return dict(should_reduce=target < lots - 1e-9,
                target_lots=target,
                reasons=reasons,
                vol_trigger=vol_trigger,
                event_trigger=evt_trigger)
