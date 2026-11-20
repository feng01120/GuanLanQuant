"""人文因子：日历效应、消费节点、产业文化映射。"""
from __future__ import annotations

from datetime import date

from ..util import calendar_events, clamp, humanities_score, sector_theme


def dimension(industry: str, d: date | None = None) -> dict:
    d = d or date.today()
    score, notes = humanities_score(d)
    theme, theme_note = sector_theme(industry)
    events = calendar_events(d, 30)
    upcoming = [e for e in events if 0 <= e["days"] <= 10]
    if upcoming:
        near = upcoming[0]
        score += 2 if near["kind"] in ("人文", "政策") else 0
        notes.append(f"临近「{near['title']}」（{near['days']}天后）：{near['impact']}")
    reasons = [f"产业人文主题：{theme}｜{theme_note}"] + notes
    return {"key": "humanities", "label": "人文面", "score": round(clamp(score, -100, 100), 1),
            "reasons": reasons, "theme": theme, "events": events[:6]}
