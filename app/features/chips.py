"""筹码分布估算：日 K 成交量按价格分箱 + 时间衰减。

公开日线没有逐笔成交与真实持仓成本，本模块只做“估算”：
- 以典型价 (H+L+2C)/4 作为当日成交价格；
- 以成交量作为权重；
- 以半衰期对久远成交衰减，近似换手；
- 以现价切分获利盘/套牢盘。

输出统一标注为估算，不冒充交易所逐笔筹码。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def chip_distribution(df: pd.DataFrame, price: float, bins: int = 40,
                      lookback: int = 420, half_life: int = 120) -> dict:
    if df is None or len(df) < 20 or not price or price <= 0:
        return {}
    d = df.tail(max(60, min(lookback, len(df)))).copy()
    for col in ("high", "low", "close", "volume"):
        if col not in d.columns:
            return {}
    d = d.dropna(subset=["high", "low", "close", "volume"])
    if d.empty:
        return {}
    vol = d["volume"].to_numpy(float)
    typical = (d["high"].to_numpy(float) + d["low"].to_numpy(float) + 2 * d["close"].to_numpy(float)) / 4
    age = np.arange(len(d))[::-1]
    weights = vol * np.power(0.5, age / max(1.0, float(half_life)))
    if not np.isfinite(weights).all() or weights.sum() <= 0:
        return {}

    lo = float(np.nanmin(typical))
    hi = float(np.nanmax(typical))
    if hi - lo < 1e-9:
        hi = lo * 1.02 + 1e-6
        lo = lo * 0.98
    # 给现价留出边界，避免现价刚好落在最后一个 bin 外
    lo = min(lo, float(price))
    hi = max(hi, float(price))
    hist, edges = np.histogram(typical, bins=bins, range=(lo, hi), weights=weights)
    centers = (edges[:-1] + edges[1:]) / 2
    total = float(hist.sum())
    if total <= 0:
        return {}
    cum = np.cumsum(hist) / total

    def quantile(q: float) -> float:
        idx = int(np.searchsorted(cum, q, side="left"))
        return float(centers[min(max(idx, 0), len(centers) - 1)])

    p5, p95 = quantile(0.05), quantile(0.95)
    avg = float((centers * hist).sum() / total)
    profit_ratio = float(hist[centers <= float(price)].sum() / total)
    concentration = (p95 - p5) / (p95 + p5) * 100 if (p95 + p5) > 0 else 0.0
    return {
        "centers": [float(x) for x in centers],
        "weights": [float(x / total) for x in hist],
        "price": float(price),
        "profit_ratio": profit_ratio,
        "avg_cost": avg,
        "p5": p5,
        "p95": p95,
        "concentration": concentration,
        "low": lo,
        "high": hi,
        "lookback": int(len(d)),
        "method": f"成交量分箱 {bins} 档 · 半衰期 {half_life} 日 · 近 {len(d)} 根日 K",
    }
