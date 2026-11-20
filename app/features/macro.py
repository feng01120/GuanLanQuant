"""宏观因子：增长、通胀、流动性、汇率、利率代理。"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..util import clamp, pct_rank, safe_float


@dataclass
class MacroContext:
    points: list = field(default_factory=list)
    fx: list[dict] = field(default_factory=list)
    bond_close: list[float] = field(default_factory=list)
    gold_pct: float = 0.0
    oil_pct: float = 0.0
    amount_history: list[float] = field(default_factory=list)
    index_pct: float = 0.0
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    updated: str = ""
    source_note: str = ""

    def by_key(self, key: str) -> dict:
        for p in self.points:
            if getattr(p, "key", None) == key or (isinstance(p, dict) and p.get("key") == key):
                return p if isinstance(p, dict) else p.__dict__
        return {}

    def dimension(self) -> dict:
        return {"key": "macro", "label": "宏观面", "score": round(self.score, 1),
                "reasons": self.reasons[:7]}

    def to_dict(self) -> dict:
        return {
            "points": [p.__dict__ if hasattr(p, "__dict__") else p for p in self.points],
            "fx": self.fx[-30:], "bond_close": self.bond_close[-30:],
            "gold_pct": self.gold_pct, "oil_pct": self.oil_pct,
            "amount_history": self.amount_history[-60:], "index_pct": self.index_pct,
            "score": self.score, "reasons": self.reasons, "updated": self.updated,
            "source_note": self.source_note,
        }


def build_context(points: list, fx: list[dict], bond_df: pd.DataFrame | None,
                  gold_pct: float, oil_pct: float, amount_history: list[float],
                  index_pct: float) -> MacroContext:
    ctx = MacroContext(points=points, fx=fx,
                       bond_close=[float(x) for x in (bond_df["close"].tolist() if bond_df is not None and len(bond_df) else [])],
                       gold_pct=gold_pct, oil_pct=oil_pct,
                       amount_history=amount_history, index_pct=index_pct)
    score, reasons = 0.0, []

    def get(key):
        for p in points:
            if getattr(p, "key", "") == key:
                return p
        return None

    pmi = get("pmi")
    if pmi:
        v = float(pmi.value)
        s = clamp((v - 50) * 4.5, -18, 12)
        if pmi.change:
            s += clamp(pmi.change * 2.0, -4, 4)
        score += s
        reasons.append(f"制造业PMI {v:.1f}（{'扩张' if v >= 50 else '收缩'}），贡献 {s:+.0f}")

    cpi = get("cpi")
    if cpi:
        v = float(cpi.value)
        if v < 0:
            s = -16
            reasons.append(f"CPI 同比 {v:+.1f}%，通缩压力，贡献 -16")
        elif v < 1:
            s = -4
            reasons.append(f"CPI 同比 {v:+.1f}%，需求偏弱，贡献 -4")
        elif v <= 3:
            s = 6
            reasons.append(f"CPI 同比 {v:+.1f}%，温和通胀，贡献 +6")
        elif v <= 5:
            s = -4
            reasons.append(f"CPI 同比 {v:+.1f}%，通胀升温，贡献 -4")
        else:
            s = -12
            reasons.append(f"CPI 同比 {v:+.1f}%，通胀高压，贡献 -12")
        score += s

    ppi = get("ppi")
    if ppi:
        v = float(ppi.value)
        s = clamp(v * 1.8, -10, 10)
        score += s
        reasons.append(f"PPI 同比 {v:+.1f}%，{'再通胀' if v > 0 else '工业品通缩'}，贡献 {s:+.0f}")

    gdp = get("gdp")
    if gdp:
        v = float(gdp.value)
        s = clamp((v - 5) * 4, -10, 10)
        score += s
        reasons.append(f"GDP 同比 {v:.1f}%，贡献 {s:+.0f}")

    m2 = get("m2")
    if m2:
        v = float(m2.value)
        s = clamp((v - 5) * 2.5, -8, 8)
        score += s
        reasons.append(f"M2 同比 {v:.1f}%，流动性贡献 {s:+.0f}")

    # 汇率：USD/CNY 上行 = 人民币贬值，对权益偏负面
    if len(fx) >= 6:
        latest = fx[-1]["value"]
        base = fx[max(0, len(fx) - 21)]["value"]
        chg = (latest / base - 1) * 100 if base else 0.0
        s = clamp(-chg * 12, -12, 12)
        score += s
        reasons.append(f"USD/CNY {latest:.4f}，20日 {chg:+.2f}%（{'人民币贬值' if chg > 0 else '人民币升值'}），贡献 {s:+.0f}")

    # 国债 ETF 价格上行 ≈ 收益率下行，对估值偏正面
    if len(ctx.bond_close) >= 21:
        chg = (ctx.bond_close[-1] / ctx.bond_close[-21] - 1) * 100
        s = clamp(chg * 18, -9, 9)
        score += s
        reasons.append(f"国债ETF 20日 {chg:+.2f}%（利率代理），贡献 {s:+.0f}")

    if len(amount_history) >= 10:
        rank = pct_rank(amount_history, amount_history[-1])
        s = clamp((rank - 0.5) * 26, -10, 10)
        score += s
        reasons.append(f"两市成交额处于近{len(amount_history)}日 {rank * 100:.0f}% 分位，贡献 {s:+.0f}")

    if abs(gold_pct) > 0.01:
        s = clamp(-gold_pct * 0.8, -4, 4)
        score += s
        reasons.append(f"黄金当日 {gold_pct:+.2f}%（避险温度），贡献 {s:+.0f}")
    if abs(oil_pct) > 0.01:
        s = clamp(oil_pct * 1.2, -4, 4)
        score += s
        reasons.append(f"原油当日 {oil_pct:+.2f}%（成本与通胀），贡献 {s:+.0f}")

    ctx.score = round(clamp(score, -100, 100), 1)
    ctx.reasons = reasons or ["宏观数据不足，按中性处理"]
    ctx.updated = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    ctx.source_note = "CPI/PMI/PPI/GDP/M2 来自国家统计局（经数据中心转发）；汇率来自中国外汇交易中心；利率用国债ETF代理"
    return ctx
