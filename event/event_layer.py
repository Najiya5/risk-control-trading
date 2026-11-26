#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""事件层：金十快讯 → 多模型判断 → 仓位系数

流程：
  1. fetch_news()   拉金十快讯，过滤 important=1（或关键词命中）
  2. judge()        多模型各自判断"这次事件对黄金的影响有多大"
  3. aggregate()    去极值取平均 → 影响力百分位
  4. to_coeff()     映射成标的仓位系数

数据契约（所有模型必须按这个 schema 输出）：
  {
    "impact":   -1.0 ~ 1.0,   事件对金价的净影响（正=利多，负=利空）
    "severity":  0.0 ~ 1.0,   影响烈度（与方向无关）
    "horizon":   "intraday" | "days" | "weeks",
    "reason":    "一句话依据"
  }

注意：
  - 默认判定事件为真（真假判断后置，且不由同一批模型做）
  - 模型只给判断，数值映射由代码做
  - 各家模型独立调用，记忆不共享
"""

import os
import json
import time
import urllib.request
import urllib.error

import numpy as np

# ────────────────────────────────────────────────
# 1. 金十快讯
# ────────────────────────────────────────────────

JIN10_URL = "https://flash-api.jin10.com/get_flash_list"
JIN10_HEADERS = {
    "Referer": "https://www.jin10.com/",
    "Origin": "https://www.jin10.com",
    "x-app-id": "bVBF4FyRTn5NJF5n",
    "x-version": "1.0.0",
    "User-Agent": "Mozilla/5.0",
}

# 黄金相关关键词（用于 important=0 时补充过滤）
GOLD_KEYWORDS = [
    "黄金", "金价", "贵金属", "美元指数", "美联储", "降息", "加息",
    "通胀", "CPI", "非农", "地缘", "战争", "制裁", "避险",
    "美债", "收益率", "央行购金", "ETF",
]


def fetch_news(channel: int = -8200, timeout: int = 10) -> list:
    """拉金十快讯，返回规范化后的列表"""
    url = f"{JIN10_URL}?channel={channel}&max_time="
    req = urllib.request.Request(url, headers=JIN10_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    payload = json.loads(raw)
    if payload.get("status") != 200:
        raise RuntimeError(f"金十接口返回 {payload.get('status')}: {payload.get('message')}")

    out = []
    for item in payload.get("data", []):
        d = item.get("data", {}) or {}
        content = (d.get("content") or "").strip()
        if not content:
            continue
        out.append({
            "id": item.get("id"),
            "time": item.get("time"),
            "important": item.get("important", 0),
            "content": content,
            "title": (d.get("title") or "").strip(),
        })
    return out


def filter_events(news: list, only_important: bool = True,
                  keywords: list = None, max_items: int = 10) -> list:
    """过滤出需要判断的事件"""
    keywords = keywords or GOLD_KEYWORDS
    picked = []
    for n in news:
        hit = False
        if only_important and n["important"] == 1:
            hit = True
        elif any(k in n["content"] for k in keywords):
            hit = True
        if hit:
            picked.append(n)
    return picked[:max_items]


# ────────────────────────────────────────────────
# 2. 多模型判断
# ────────────────────────────────────────────────

JUDGE_PROMPT = """你是黄金交易的研究员。判断下面这条新闻对国际现货黄金（XAUUSD）价格的影响。

只输出 JSON，不要任何其他文字：
{{
  "impact": <数字，-1.0 到 1.0，正=利多金价，负=利空>,
  "severity": <数字，0.0 到 1.0，影响的烈度（与方向无关）>,
  "horizon": <"intraday" 或 "days" 或 "weeks">,
  "reason": <一句话依据，不超过 30 字>
}}

新闻：
{content}"""


def _post_json(url: str, headers: dict, body: dict, timeout: int = 30) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def judge_with_deepseek(content: str, api_key: str,
                        base_url: str = "https://api.deepseek.com",
                        model: str = "deepseek-chat",
                        timeout: int = 40) -> dict:
    """用 DeepSeek 判断一条新闻（OpenAI 兼容接口）"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": JUDGE_PROMPT.format(content=content)}],
        "temperature": 0,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }
    resp = _post_json(f"{base_url.rstrip('/')}/chat/completions", headers, body, timeout)
    text = resp["choices"][0]["message"]["content"]
    return parse_judgment(text)


def parse_judgment(text: str) -> dict:
    """解析模型输出；失败时返回 None 型结果（该模型记为弃权）"""
    try:
        obj = json.loads(text)
        impact = float(obj.get("impact", 0))
        severity = float(obj.get("severity", 0))
        return {
            "impact": max(-1.0, min(1.0, impact)),
            "severity": max(0.0, min(1.0, severity)),
            "horizon": obj.get("horizon", "days"),
            "reason": str(obj.get("reason", ""))[:60],
            "ok": True,
        }
    except Exception:
        return {"ok": False, "raw": text[:200]}


def judge_all(event: dict, judges: list) -> list:
    """
    judges: [{"name": "...", "fn": callable(content) -> dict}, ...]
    每个 judge 独立调用；失败/超时的记为弃权，不参与聚合。
    """
    results = []
    for j in judges:
        t0 = time.time()
        try:
            r = j["fn"](event["content"])
            r["model"] = j["name"]
            r["latency"] = time.time() - t0
            results.append(r)
        except Exception as e:
            results.append({"model": j["name"], "ok": False,
                            "error": f"{type(e).__name__}: {e}",
                            "latency": time.time() - t0})
    return results


# ────────────────────────────────────────────────
# 3. 聚合
# ────────────────────────────────────────────────

def aggregate(results: list) -> dict:
    """
    去极值取平均。
    返回 impact / severity / 分歧度 / 参与模型数。
    """
    valid = [r for r in results if r.get("ok")]
    n = len(valid)
    if n == 0:
        return {"ok": False, "reason": "所有模型都失败", "n": 0}

    impacts = np.array([r["impact"] for r in valid])
    severities = np.array([r["severity"] for r in valid])

    def trimmed_mean(x: np.ndarray) -> float:
        if len(x) >= 3:
            xs = np.sort(x)
            return float(xs[1:-1].mean())   # 去最高最低
        return float(x.mean())

    out = {
        "ok": True,
        "n": n,
        "impact": trimmed_mean(impacts),
        "severity": trimmed_mean(severities),
        "impact_std": float(impacts.std()) if n > 1 else 0.0,
        "severity_std": float(severities.std()) if n > 1 else 0.0,
    }
    # 分歧度：方向或幅度不一致
    if n > 1:
        same_sign = (np.sign(impacts) == np.sign(impacts[0])).all()
        out["dir_agree"] = bool(same_sign)
        out["dispersion"] = out["impact_std"]
    else:
        out["dir_agree"] = True
        out["dispersion"] = 0.0
    return out


def to_impact_score(agg: dict) -> float:
    """合成一个强度值：烈度为准，方向不参与（风控只关心大小）"""
    if not agg.get("ok"):
        return 0.0
    return float(agg["severity"])


def to_coeff(impact_score: float, hist: np.ndarray = None) -> float:
    """
    影响强度 → 标的仓位系数。
    hist 给定时按历史百分位映射；否则按绝对阈值。

    映射（占位，待校准）：
      severity < 0.3          → 1.0   （不管）
      0.3 - 0.6               → 0.7
      0.6 - 0.8               → 0.5
      > 0.8                   → 0.0   （归零）
    """
    s = impact_score
    if s < 0.30:
        return 1.0
    if s < 0.60:
        return 0.70
    if s < 0.80:
        return 0.50
    return 0.0


def check_dispersion(agg: dict, std_threshold: float = 0.4) -> tuple:
    """分歧检查：分歧大的直接归零，不打折"""
    if not agg.get("ok") or agg["n"] < 2:
        return False, None
    if not agg.get("dir_agree"):
        return True, "方向不一致"
    if agg["dispersion"] > std_threshold:
        return True, f"幅度分歧 {agg['dispersion']:.2f} > {std_threshold}"
    return False, None
