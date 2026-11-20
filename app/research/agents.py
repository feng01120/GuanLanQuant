"""多智能体研判：分析师 → 多空研究员 → 交易员 → 风控官。

借鉴 TradingAgents 的分工结构，但使用可复现的规则推理，不依赖外部 LLM token。
"""
from __future__ import annotations

import math
from datetime import datetime

from ..util import clamp, money, price


def _stance(score: float) -> str:
    if score >= 20:
        return "偏多"
    if score <= -20:
        return "偏空"
    return "中性"


def _view(role: str, dim: dict, bullets: list[str] | None = None) -> dict:
    return {"role": role, "stance": _stance(float(dim.get("score", 0))),
            "score": round(float(dim.get("score", 0)), 1),
            "bullets": (bullets if bullets is not None else dim.get("reasons", []))[:6]}


def build_research(r: dict) -> dict:
    """r: MarketService.analyze() 的输出字典。"""
    snap = r.get("snapshot", {})
    dims = r.get("dimensions", {})
    fused = r.get("fused", {})
    short = r.get("short", {})
    long = r.get("long", {})
    quote = r.get("quote")
    name = r.get("name", "")
    industry = r.get("industry", "")
    news = r.get("news", [])
    anns = r.get("announcements", [])
    events = r.get("events", [])

    close = float(getattr(quote, "price", 0) or snap.get("close", 0)) if quote else float(snap.get("close", 0))
    atr = float(snap.get("atr", close * 0.02))
    support = float(snap.get("support", close * 0.95))
    resistance = float(snap.get("resistance", close * 1.05))
    pe = float(getattr(quote, "pe", 0) or 0)
    pb = float(getattr(quote, "pb", 0) or 0)
    turnover = float(getattr(quote, "turnover", 0) or 0)

    views = []
    views.append(_view("技术分析师", dims.get("technical", {}),
                       [
                           f"趋势评分 {snap.get('trend_score', 0):+.0f}；MA20 偏离 {snap.get('dist_ma20', 0) * 100:+.1f}%，MA60 偏离 {snap.get('dist_ma60', 0) * 100:+.1f}%",
                           f"RSI {snap.get('rsi', 50):.1f}，MACD 柱 {snap.get('macd_hist', 0):+.3f}",
                           f"支撑 {price(support)} / 压力 {price(resistance)}，ATR {price(atr)}（{snap.get('atr_pct', 0) * 100:.1f}%）",
                       ] + dims.get("technical", {}).get("reasons", [])[:3]))
    views.append(_view("资金分析师", dims.get("fund", {}),
                       [f"换手率 {turnover:.2f}%，量比 {snap.get('vol_ratio', 0):.2f}",
                        f"5日资金流/成交额 {snap.get('flow_ratio5', 0) * 100:+.2f}%"] +
                       dims.get("fund", {}).get("reasons", [])[:3]))
    views.append(_view("估值分析师", dims.get("valuation", {}),
                       [f"PE {pe:.1f} / PB {pb:.2f}" if pe > 0 else "PE 缺失或为负（亏损）",
                        f"市值 {money(float(getattr(quote, 'market_cap', 0) or 0))}"] +
                       dims.get("valuation", {}).get("reasons", [])[:3]))
    views.append(_view("情绪分析师", dims.get("sentiment", {}),
                       [f"市场情绪 {dims.get('sentiment', {}).get('label_text', '中性')}，指数当日 {r.get('index_pct', 0):+.2f}%",
                        f"涨停 {r.get('limit_up', 0)} / 跌停 {r.get('limit_down', 0)}，涨跌家数比 {r.get('breadth', 0.5) * 100:.0f}%"] +
                       dims.get("sentiment", {}).get("reasons", [])[:3]))
    views.append(_view("宏观分析师", dims.get("macro", {}),
                       dims.get("macro", {}).get("reasons", [])[:5]))
    views.append(_view("人文观察员", dims.get("humanities", {}),
                       [f"产业主题：{dims.get('humanities', {}).get('theme', '综合')}"] +
                       dims.get("humanities", {}).get("reasons", [])[:4]))

    contrib = fused.get("contributions", {})
    positives = [(k, v) for k, v in contrib.items() if v > 0]
    negatives = [(k, v) for k, v in contrib.items() if v < 0]
    positives.sort(key=lambda x: -x[1])
    negatives.sort(key=lambda x: x[1])

    def dim_text(k, val):
        d = dims.get(k, {})
        reasons = d.get("reasons", [])
        return f"{d.get('label', k)}（{val:+.1f}）：" + "；".join(reasons[:2])

    long20 = (long.get("horizons", {}) or {}).get(20, {})
    short1 = short.get(1, {}) or short.get("1", {})
    short2 = short.get(2, {}) or short.get("2", {})
    bull_points = [dim_text(k, v) for k, v in positives[:3]]
    if short1:
        bull_points.append(
            f"T+1 模型方向概率 {short1.get('prob_up', 0.5) * 100:.0f}%，期望 {short1.get('exp_ret', 0):+.2f}%（置信度 {short1.get('confidence', 0):.0f}）")
    if long20:
        bull_points.append(
            f"20日蒙特卡洛：上涨概率 {long20.get('prob_up', 0.5) * 100:.0f}%，中性情形 {long20.get('median_ret', 0):+.2f}%")
    bear_points = []
    for k, v in negatives[:3]:
        bear_points.append(dim_text(k, v))
    if long20:
        bear_points.append(
            f"20日 90% 区间下沿 {long20.get('price_low', 0):.2f}，VaR95 {long20.get('var95', 0):+.2f}%")
    bear_points.append(f"压力位 {price(resistance)} 未突破前，追高性价比有限")
    if short2:
        bear_points.append(f"T+2 方向概率 {short2.get('prob_up', 0.5) * 100:.0f}%，存在隔夜与消息面跳空风险")

    # 交易员决策
    bias = 0.55 * fused.get("total", 0) / 100
    bias += 0.25 * ((short1.get("prob_up", 0.5) - 0.5) * 2)
    bias += 0.20 * ((long20.get("prob_up", 0.5) - 0.5) * 2)
    vol_flag = snap.get("atr_pct", 0) > 0.05
    stale = r.get("stale", False)
    event_near = any(0 <= e.get("days", 99) <= 3 for e in events)
    veto = stale or (vol_flag and abs(bias) < 0.35)

    if veto:
        action = "观望"
        position = 0.0
    elif bias >= 0.45:
        action, position = "偏多 · 分批建仓", clamp(abs(bias) * 0.45, 0.03, r.get("max_position", 0.2))
    elif bias >= 0.2:
        action, position = "轻仓偏多", clamp(abs(bias) * 0.35, 0.02, 0.12)
    elif bias <= -0.45:
        action, position = "偏空 · 回避", 0.0
    elif bias <= -0.2:
        action, position = "减仓/观望", 0.0
    else:
        action, position = "中性观察", 0.0

    entry_low = max(0.01, close - 0.5 * atr)
    entry_high = close + 0.3 * atr
    stop = max(0.01, close - 2.2 * atr)
    target = max(resistance, close + 3.0 * atr)
    rr = (target - close) / max(1e-6, close - stop)

    decision = {
        "action": action, "bias": round(bias, 3), "position_pct": round(position * 100, 1),
        "entry_low": round(entry_low, 2), "entry_high": round(entry_high, 2),
        "stop": round(stop, 2), "target": round(target, 2), "risk_reward": round(rr, 2),
        "horizon": "T+1 ~ T+20", "veto": veto,
    }

    # 风控官
    risks, flags = [], []
    if stale:
        flags.append("数据陈旧：未获取到最新行情，结论暂停使用")
    if vol_flag:
        flags.append(f"波动偏高：ATR {snap.get('atr_pct', 0) * 100:.1f}%，仓位需下调")
    if event_near:
        ev = next((e for e in events if 0 <= e.get("days", 99) <= 3), None)
        if ev:
            flags.append(f"事件临近：{ev.get('title')}（{ev.get('days')}天后）")
    if 0 < pe > 60:
        flags.append(f"估值偏高：PE {pe:.1f}")
    if pe <= 0:
        flags.append("盈利为负或 PE 缺失，估值支撑弱")
    if turnover > 18:
        flags.append(f"换手率 {turnover:.1f}%，筹码高度松动")
    if short1 and long20 and (short1.get("prob_up", 0.5) - 0.5) * (long20.get("prob_up", 0.5) - 0.5) < 0:
        flags.append("长短周期信号背离，方向一致性不足")
    if short1 and short1.get("confidence", 0) < 45:
        flags.append("短周期模型置信度偏低（样本外命中率接近随机）")
    for a in anns[:5]:
        t = a.title if hasattr(a, "title") else str(a)
        if any(k in t for k in ("减持", "亏损", "立案", "诉讼", "质押", "退市", "处罚", "冻结")):
            flags.append(f"公告风险词：{t[:28]}")
    for n in news[:10]:
        title = n.get("title", "") if isinstance(n, dict) else str(n)
        if any(k in title for k in ("暴跌", "调查", "处罚", "退市", "违约", "冲突", "关税")):
            flags.append(f"舆情风险：{title[:28]}")
    if not flags:
        flags.append("未触发硬性风控条款；仍需遵守仓位与止损纪律")

    risk_level = "高" if len(flags) >= 4 or stale else "中" if len(flags) >= 2 else "低"

    summary = (
        f"{name}（{r.get('symbol', '')}）六维综合 {fused.get('total', 0):+.1f}，判定「{fused.get('verdict', '中性')}」；"
        f"T+1 上涨概率 {short1.get('prob_up', 0.5) * 100:.0f}%、T+2 {short2.get('prob_up', 0.5) * 100:.0f}%；"
        f"20日上涨概率 {long20.get('prob_up', 0.5) * 100:.0f}%。交易员建议：{action}。"
        f"主要风险：{flags[0]}。"
    )
    return {"views": views, "bull": bull_points, "bear": bear_points, "decision": decision,
            "risks": flags, "risk_level": risk_level, "summary": summary,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
