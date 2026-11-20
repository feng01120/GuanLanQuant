"""情绪因子：新闻语义、市场宽度、涨跌停、成交活跃度。"""
from __future__ import annotations

import math
import re
from datetime import datetime

import numpy as np

from ..util import clamp, pct_rank

POSITIVE = {
    "利好": 2.0, "大涨": 2.0, "涨停": 2.0, "突破": 1.5, "新高": 1.5, "增持": 1.6,
    "回购": 1.5, "降准": 2.2, "降息": 2.2, "减税": 1.6, "宽松": 1.5, "复苏": 1.6,
    "超预期": 2.0, "盈利": 1.0, "增长": 1.0, "签约": 1.0, "中标": 1.2, "获批": 1.4,
    "分红": 1.0, "提价": 1.2, "景气": 1.6, "改善": 1.0, "支持": 1.0, "鼓励": 1.0,
    "补贴": 1.2, "创新高": 1.8, "净流入": 1.2, "上涨": 1.2, "走强": 1.2, "反弹": 1.0,
    "扩产": 1.0, "订单": 1.0, "利润": 0.8, "提振": 1.2, "看好": 1.3, "加仓": 1.3,
}
NEGATIVE = {
    "利空": 2.0, "大跌": 2.0, "跌停": 2.0, "减持": 1.6, "亏损": 1.6, "下滑": 1.5,
    "处罚": 1.6, "调查": 2.0, "退市": 2.2, "违约": 2.0, "爆雷": 2.2, "下调": 1.5,
    "不及预期": 2.0, "收紧": 1.5, "加息": 2.2, "通胀": 1.0, "风险": 1.0, "警示": 1.5,
    "停牌": 1.0, "解禁": 1.0, "质押": 1.0, "诉讼": 1.2, "召回": 1.0, "裁员": 1.2,
    "净流出": 1.2, "下跌": 1.2, "走弱": 1.2, "回落": 1.0, "亏损扩大": 2.0, "暴跌": 2.2,
    "低迷": 1.3, "承压": 1.2, "减持计划": 1.6, "立案": 2.2, "冻结": 1.5,
}
NEGATORS = ("不", "未", "无", "难", "否", "非")


def score_text(text: str) -> tuple[float, list[str]]:
    if not text:
        return 0.0, []
    hits = []
    raw = 0.0
    for word, weight in POSITIVE.items():
        for m in re.finditer(re.escape(word), text):
            before = text[max(0, m.start() - 3):m.start()]
            sign = -1.0 if any(n in before for n in NEGATORS) else 1.0
            raw += weight * sign
            hits.append(("+" if sign > 0 else "-") + word)
    for word, weight in NEGATIVE.items():
        for m in re.finditer(re.escape(word), text):
            before = text[max(0, m.start() - 3):m.start()]
            sign = -1.0 if any(n in before for n in NEGATORS) else 1.0
            raw -= weight * sign
            hits.append(("-" if sign > 0 else "+") + word)
    score = math.tanh(raw / 3.5)
    hits = list(dict.fromkeys(hits))
    return score, hits[:6]


def tag_text(text: str) -> list[str]:
    mapping = {
        "货币政策": ("央行", "降准", "降息", "MLF", "LPR", "流动性", "逆回购"),
        "监管政策": ("证监会", "银保监", "交易所", "监管", "立案", "新规"),
        "财政政策": ("财政", "专项债", "减税", "补贴", "国债"),
        "海外扰动": ("美联储", "关税", "特朗普", "地缘", "冲突", "制裁", "美股"),
        "地产链": ("房地产", "楼市", "地产", "保交楼", "房贷"),
        "科技产业": ("半导体", "芯片", "AI", "算力", "机器人", "国产替代"),
        "消费": ("消费", "白酒", "零售", "旅游", "以旧换新"),
        "能源资源": ("原油", "黄金", "铜", "煤炭", "电力", "有色"),
    }
    tags = []
    for tag, keys in mapping.items():
        if any(k in text for k in keys):
            tags.append(tag)
    return tags


def score_news(items) -> tuple[float, list[dict], list[str]]:
    if not items:
        return 0.0, [], []
    scored = []
    for it in items:
        base = f"{it.title} {it.summary}"
        s, hits = score_text(base)
        scored.append({"title": it.title, "time": it.time, "url": it.url,
                       "score": round(s * 100, 1), "hits": hits, "tags": tag_text(base)})
    weights = np.linspace(1.3, 0.6, len(scored))
    agg = float(np.average([x["score"] / 100 for x in scored], weights=weights))
    hits = list(dict.fromkeys(h for x in scored for h in x["hits"]))
    return agg * 100, scored, hits[:8]


def market_sentiment(breadth: float, limit_up: int, limit_down: int, amount: float,
                     amount_history: list[float], index_pct: float) -> dict:
    breadth_score = clamp((breadth - 0.5) * 160, -55, 55)
    updown = limit_up + limit_down
    limit_score = clamp((limit_up - limit_down) / max(1, updown) * 35, -35, 35)
    amt_rank = pct_rank(amount_history, amount) if len(amount_history) >= 5 else 0.5
    amount_score = clamp((amt_rank - 0.5) * 40, -20, 20)
    index_score = clamp(index_pct * 12, -18, 18)
    total = clamp(breadth_score + limit_score + amount_score + index_score, -100, 100)
    label = ("亢奋" if total > 55 else "偏暖" if total > 15 else
             "偏冷" if total < -15 else "冰点" if total < -55 else "中性")
    return {
        "score": round(total, 1), "label": label, "breadth": breadth,
        "breadth_score": round(breadth_score, 1), "limit_score": round(limit_score, 1),
        "amount_score": round(amount_score, 1), "index_score": round(index_score, 1),
        "amount_rank": round(amt_rank, 2), "limit_up": limit_up, "limit_down": limit_down,
    }


def sentiment_dimension(news_items, breadth: float, limit_up: int, limit_down: int,
                        amount: float, amount_history: list[float], index_pct: float) -> dict:
    news_score, scored, hits = score_news(news_items)
    ms = market_sentiment(breadth, limit_up, limit_down, amount, amount_history, index_pct)
    score = clamp(news_score * 0.35 + ms["score"] * 0.65, -100, 100)
    reasons = [
        f"新闻语义 {news_score:+.0f}（{len(scored)} 条，关键词：{'、'.join(hits[:4]) or '无'}）",
        f"涨跌家数比 {breadth * 100:.0f}%（{ms['breadth_score']:+.0f}）",
        f"涨停 {limit_up} / 跌停 {limit_down}（{ms['limit_score']:+.0f}）",
        f"成交额历史分位 {ms['amount_rank'] * 100:.0f}%（{ms['amount_score']:+.0f}）",
        f"指数当日 {index_pct:+.2f}%",
    ]
    return {"key": "sentiment", "label": "情绪面", "score": round(score, 1),
            "reasons": reasons, "label_text": ms["label"], "news": scored[:12]}
