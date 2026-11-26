#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""签字工具

用法：
  python approve.py            # 签字（从现在起 24 小时有效）
  python approve.py --status   # 查看当前签字状态
  python approve.py --hours 12 # 自定义有效小时数
"""

import os
import sys
import json
import argparse
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def load_state(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(path, st):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="只看状态，不签字")
    ap.add_argument("--hours", type=float, default=None)
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    state_path = os.path.join(HERE, cfg["logging"]["state_file"])
    st = load_state(state_path)

    now = datetime.datetime.now(datetime.UTC)
    au = st.get("approved_until")
    valid = False
    if au:
        try:
            until = datetime.datetime.fromisoformat(au)
            if until.tzinfo is None:
                until = until.replace(tzinfo=datetime.UTC)
            valid = now < until
            left = (until - now).total_seconds() / 3600
        except Exception:
            left = None
    else:
        left = None

    print(f"当前时间: {now.astimezone().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"签字到期: {au or '（从未签字）'}")
    if valid:
        print(f"状态: ✓ 有效，还剩 {left:.1f} 小时")
    else:
        print("状态: ✗ 无效（已过期或从未签字）")

    if args.status:
        return 0

    hours = args.hours if args.hours is not None else cfg["approval"]["valid_hours"]
    until = now + datetime.timedelta(hours=hours)
    st["approved_until"] = until.isoformat()
    st["approved_at"] = now.isoformat()
    save_state(state_path, st)
    print()
    print(f"✓ 已签字，有效期至 {until.astimezone().strftime('%Y-%m-%d %H:%M:%S')}（{hours:g} 小时）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
