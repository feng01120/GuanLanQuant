"""资金因子：主力净流入、量比、换手与流动性。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..util import clamp


def fund_dimension(d: pd.DataFrame, quote) -> dict:
    last = d.iloc[-1]
    score, reasons = 0.0, []
    fr5 = float(last.get("flow_ratio5") or 0)
    if abs(fr5) > 1e-9:
        s = clamp(fr5 * 100 * 9, -30, 30)
        score += s
        reasons.append(f"近5日主力净流入/成交额 {fr5 * 100:+.2f}%，贡献 {s:+.0f}")
    else:
        reasons.append("资金流数据缺失（接口未返回），该项按 0 处理")
    vr = float(last.get("vol_ratio") or 0)
    if np.isfinite(vr) and vr > 0:
        ret1 = float(last.get("ret1") or 0)
        s = clamp((vr - 1) * 12 * (1 if ret1 >= 0 else -1), -12, 12)
        score += s
        reasons.append(f"量比 {vr:.2f}，贡献 {s:+.0f}")
    turn = float(last.get("turnover") or 0)
    if turn > 0:
        if turn > 15:
            score -= 4
            reasons.append(f"换手率 {turn:.1f}%，交易过热")
        elif turn < 1:
            score -= 2
            reasons.append(f"换手率 {turn:.1f}%，关注度偏低")
        else:
            reasons.append(f"换手率 {turn:.1f}%，处于正常区间")
    amount = float(getattr(quote, "amount", 0) or 0)
    if amount > 0:
        if amount < 5e7:
            score -= 4
            reasons.append("成交额不足 5000 万，流动性折价")
        elif amount > 3e9:
            score += 3
            reasons.append("成交活跃，冲击成本较低")
    return {"key": "fund", "label": "资金面", "score": round(clamp(score, -100, 100), 1),
            "reasons": reasons}
