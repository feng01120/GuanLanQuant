"""六维因子融合。"""
from __future__ import annotations

import numpy as np

from ..util import clamp

DEFAULT_WEIGHTS = {
    "technical": 0.30,
    "fund": 0.15,
    "valuation": 0.10,
    "sentiment": 0.17,
    "macro": 0.16,
    "humanities": 0.12,
}


def fuse(dimensions: dict[str, dict], weights: dict[str, float] | None = None) -> dict:
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)
    total = 0.0
    radar = []
    contributions = {}
    for key, dim in dimensions.items():
        wt = w.get(key, 0.0)
        s = float(dim.get("score", 0))
        total += s * wt
        contributions[key] = round(s * wt, 2)
        radar.append({"key": key, "label": dim.get("label", key), "score": round(s, 1),
                      "weight": wt, "contribution": round(s * wt, 2)})
    total = clamp(total / max(1e-6, sum(w.values())), -100, 100)
    signs = [np.sign(d.get("score", 0)) for d in dimensions.values() if abs(d.get("score", 0)) > 3]
    agreement = abs(sum(signs)) / max(1, len(signs)) if signs else 0.0
    confidence = clamp(42 + abs(total) * 0.55 + agreement * 22, 8, 96)

    if total >= 45:
        verdict, signal = "强势偏多", "BULL"
    elif total >= 18:
        verdict, signal = "温和偏多", "LEAN_BULL"
    elif total <= -45:
        verdict, signal = "强势偏空", "BEAR"
    elif total <= -18:
        verdict, signal = "温和偏空", "LEAN_BEAR"
    else:
        verdict, signal = "中性震荡", "NEUTRAL"

    return {"total": round(total, 1), "verdict": verdict, "signal": signal,
            "confidence": round(confidence, 1), "agreement": round(agreement, 2),
            "radar": radar, "contributions": contributions, "weights": w}
