"""估值因子：价格分位、PE/PB、市值。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..util import clamp, pct_rank


def valuation_dimension(d: pd.DataFrame, quote) -> dict:
    close = float(d["close"].iloc[-1])
    hist = d["close"].tail(750).to_numpy(float)
    rank = pct_rank(hist, close)
    score = clamp((0.5 - rank) * 38, -19, 19)
    reasons = [f"股价处于近3年 {rank * 100:.0f}% 分位（{'高位' if rank > 0.7 else '低位' if rank < 0.3 else '中位'}）"]

    pe = float(getattr(quote, "pe", 0) or 0)
    pb = float(getattr(quote, "pb", 0) or 0)
    if pe > 0:
        if pe < 12:
            s, txt = 9, "PE 低位"
        elif pe < 20:
            s, txt = 5, "PE 偏低"
        elif pe < 35:
            s, txt = 0, "PE 中性"
        elif pe < 60:
            s, txt = -7, "PE 偏高"
        else:
            s, txt = -13, "PE 高估"
        score += s
        reasons.append(f"{txt}（PE {pe:.1f}），贡献 {s:+.0f}")
    else:
        score -= 8
        reasons.append("PE 为负或缺失（亏损/数据缺失），贡献 -8")
    if pb > 0:
        if pb < 1.5:
            s = 6
        elif pb < 3:
            s = 2
        elif pb < 6:
            s = -3
        else:
            s = -7
        score += s
        reasons.append(f"PB {pb:.2f}，贡献 {s:+.0f}")
    cap = float(getattr(quote, "market_cap", 0) or 0)
    if cap > 0:
        if cap < 5e9:
            score -= 4
            reasons.append("市值偏小，流动性与波动风险较高")
        elif cap > 5e11:
            score += 2
            reasons.append("大市值，定价相对充分")
    return {"key": "valuation", "label": "估值面", "score": round(clamp(score, -100, 100), 1),
            "reasons": reasons}
