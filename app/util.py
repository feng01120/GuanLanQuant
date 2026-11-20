"""通用工具：日期/交易日历、格式化、日志环。"""
from __future__ import annotations

import ctypes
import logging
import math
import os
import re
import sys
import threading
from collections import deque
from datetime import date, datetime, time, timedelta
from logging.handlers import RotatingFileHandler
from typing import Iterable

from .config import APP_NAME, LOG_DIR


def hard_exit(code: int = 0) -> None:
    """强制结束进程。

    Windows 下 Qt 在退出阶段会收到 DLL_PROCESS_DETACH；如果仍有 QThread
    在跑，普通 os._exit()/ExitProcess 可能卡在 DLL 卸载。TerminateProcess
    不触发 DLL 通知，能保证进程立即结束。调用前必须已完成落盘与日志刷新。
    """
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    if os.name == "nt":
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            k32.TerminateProcess.restype = ctypes.c_int
            handle = k32.GetCurrentProcess()
            if k32.TerminateProcess(handle, int(code) & 0xFFFFFFFF):
                return
        except Exception:
            pass
    os._exit(int(code))

# ---------------------------------------------------------------------------
# 数字与文本
# ---------------------------------------------------------------------------


def safe_float(v, default=float("nan")) -> float:
    try:
        if v is None or (isinstance(v, str) and v.strip() in {"", "-", "None", "null"}):
            return default
        f = float(v)
        return f
    except (TypeError, ValueError):
        return default


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def pct(v: float, digits: int = 2, sign: bool = True) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "--"
    s = f"{v:+.{digits}f}%" if sign else f"{v:.{digits}f}%"
    return s


def money(v: float) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "--"
    av = abs(v)
    if av >= 1e12:
        return f"{v / 1e12:.2f}万亿"
    if av >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if av >= 1e4:
        return f"{v / 1e4:.2f}万"
    return f"{v:.0f}"


def price(v: float, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "--"
    return f"{v:,.{digits}f}"


def zscore(arr, window: int | None = None) -> float:
    """最后一个值相对历史窗口的 z 分数。"""
    import numpy as np

    a = np.asarray(arr, dtype=float)
    a = a[np.isfinite(a)]
    if a.size < 3:
        return 0.0
    if window and a.size > window:
        a = a[-window:]
    sd = float(np.std(a))
    if sd < 1e-12:
        return 0.0
    return float((a[-1] - np.mean(a)) / sd)


def pct_rank(arr, value: float) -> float:
    import numpy as np

    a = np.asarray(arr, dtype=float)
    a = a[np.isfinite(a)]
    if a.size < 5:
        return 0.5
    return float(np.mean(a <= value))


def tail(text: str, n: int = 4000) -> str:
    text = text or ""
    return text[-n:]


def esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# 交易日历（中国 A 股）
# ---------------------------------------------------------------------------

# 2025-2027 法定休市（近似；以交易所公告为准，界面上标注“近似”）
HOLIDAY_RANGES: list[tuple[str, str, str]] = [
    ("2025-01-01", "2025-01-01", "元旦"),
    ("2025-01-28", "2025-02-04", "春节"),
    ("2025-04-04", "2025-04-06", "清明"),
    ("2025-05-01", "2025-05-05", "劳动节"),
    ("2025-05-31", "2025-06-02", "端午"),
    ("2025-10-01", "2025-10-08", "国庆·中秋"),
    ("2026-01-01", "2026-01-03", "元旦"),
    ("2026-02-15", "2026-02-21", "春节"),
    ("2026-04-04", "2026-04-06", "清明"),
    ("2026-05-01", "2026-05-05", "劳动节"),
    ("2026-06-19", "2026-06-21", "端午"),
    ("2026-09-25", "2026-09-27", "中秋"),
    ("2026-10-01", "2026-10-07", "国庆"),
    ("2027-01-01", "2027-01-03", "元旦"),
    ("2027-02-06", "2027-02-12", "春节"),
    ("2027-04-04", "2027-04-06", "清明"),
    ("2027-05-01", "2027-05-05", "劳动节"),
    ("2027-06-09", "2027-06-11", "端午"),
    ("2027-09-15", "2027-09-17", "中秋"),
    ("2027-10-01", "2027-10-07", "国庆"),
]


def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


HOLIDAY_DATES: dict[date, str] = {}
for _s, _e, _name in HOLIDAY_RANGES:
    _d = _parse(_s)
    while _d <= _parse(_e):
        HOLIDAY_DATES[_d] = _name
        _d += timedelta(days=1)


def is_trading_day(d: date | datetime | None = None) -> bool:
    d = (d or datetime.now()).date() if isinstance(d, datetime) else (d or date.today())
    return d.weekday() < 5 and d not in HOLIDAY_DATES


def market_phase(now: datetime | None = None) -> tuple[str, bool]:
    """返回 (状态文案, 是否处于连续竞价)。"""
    now = now or datetime.now()
    if not is_trading_day(now):
        return "休市", False
    t = now.time()
    if t < time(9, 15):
        return "盘前", False
    if t < time(9, 30):
        return "集合竞价", False
    if t <= time(11, 30):
        return "交易中", True
    if t < time(13, 0):
        return "午间休市", False
    if t <= time(15, 0):
        return "交易中", True
    return "已收盘", False


def prev_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def trading_days_between(start: date, end: date) -> int:
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n


def recent_holiday(d: date, before: int = 5, after: int = 3) -> tuple[str, int] | None:
    """距离最近长假的 (名称, 天数)；负数为节前，正数为节后。"""
    for delta in range(-after, before + 1):
        x = d + timedelta(days=delta)
        if x in HOLIDAY_DATES and HOLIDAY_DATES[x] in {"春节", "国庆", "国庆·中秋", "劳动节"}:
            return HOLIDAY_DATES[x], delta
    return None


def is_pre_holiday(d: date, days: int = 3) -> bool:
    for k in range(1, days + 1):
        if (d + timedelta(days=k)) in HOLIDAY_DATES:
            return True
    return False


def add_trading_days(d: date, n: int) -> date:
    for _ in range(max(0, int(n))):
        d = next_trading_day(d)
    return d


def session_progress(now: datetime | None = None) -> float:
    """当日连续竞价已走过的比例（用于盘中成交额折算）。"""
    now = now or datetime.now()
    if not is_trading_day(now):
        return 1.0
    t = now.time()
    if t <= time(9, 30):
        return 0.02
    if t <= time(11, 30):
        # 9:30 之后按分钟线性推进；旧代码在 9:30:01 会从 0.05
        # 突然掉到 0.004，导致成交额预估放大十几倍。
        minutes = (t.hour * 60 + t.minute) - (9 * 60 + 30)
        return max(0.02, min(0.5, 0.5 * minutes / 120))
    if t < time(13, 0):
        return 0.5
    if t <= time(15, 0):
        return 0.5 + 0.5 * ((t.hour * 60 + t.minute) - 13 * 60) / 120
    return 1.0


CONSUMPTION_EVENTS = [
    ((6, 18), "618 电商大促", "消费/电商/物流"),
    ((11, 11), "双十一", "消费/电商/物流"),
    ((9, 1), "开学季", "教育/文具/数码"),
    ((3, 8), "三八节礼赠", "美妆/珠宝/零售"),
    ((5, 20), "婚庆季启动", "黄金珠宝/白酒/婚庆"),
    ((12, 31), "年货季", "食品饮料/零售/物流"),
]

SECTOR_THEMES: list[tuple[tuple[str, ...], str, str]] = [
    (("白酒", "食品饮料", "酿酒", "调味"), "宴席与礼赠文化", "社交宴请、节庆礼赠决定动销节奏，关注春节/中秋备货与批价"),
    (("旅游", "酒店", "景区", "航空", "免税"), "假日经济", "假期长度与出行半径直接决定客流；关注节前预售与票价"),
    (("影视", "传媒", "游戏", "视频", "出版"), "内容消费与情绪", "爆款内容与政策审查共振；情绪高时估值弹性大"),
    (("黄金", "珠宝", "贵金属"), "婚庆与避险", "婚庆刚需叠加避险配置；金价与实际利率、汇率同向敏感"),
    (("医药", "生物", "医疗", "养老"), "老龄化与健康", "人口结构决定长期需求；集采与医保谈判决定短期利润"),
    (("教育", "培训"), "教育政策周期", "政策边界是估值第一变量；开学季与考试季带来季节性"),
    (("家电", "家居", "装修", "地产"), "婚房与居住链", "婚房/换新需求与地产周期绑定；以旧换新补贴是短期催化"),
    (("汽车", "整车", "零部件"), "出行方式变迁", "新能源渗透率与价格战并行；关注月度交付与出口"),
    (("农业", "种业", "养殖", "化肥"), "节气与收成", "节气、天气与猪周期共同作用；CPI 食品项是映射"),
    (("军工", "国防", "航天"), "安全叙事", "订单与政策节奏主导，事件驱动强、基本面验证慢"),
    (("银行", "保险", "证券", "金融"), "信用与信心", "利差、社融与风险偏好三因素；政策表态影响大"),
    (("煤炭", "电力", "石油", "有色", "钢铁", "化工"), "资源与周期", "供需与库存周期；PPI 与全球定价品联动"),
    (("半导体", "芯片", "电子", "通信", "计算机", "软件"), "技术代际与国产替代", "技术迭代与产业政策双驱动；估值对流动性敏感"),
    (("机器人", "机械", "自动化"), "自动化与人口替代", "劳动力结构变化推动自动化；订单验证是关键"),
]


def sector_theme(industry: str) -> tuple[str, str]:
    name = industry or ""
    for keys, theme, note in SECTOR_THEMES:
        if any(k in name for k in keys):
            return theme, note
    return "综合产业", "缺少明确人文主题映射，按市场共振处理"


def calendar_events(d: date, horizon: int = 21) -> list[dict]:
    """未来一段时间的人文/制度日历（近似）。"""
    events: list[dict] = []
    end = d + timedelta(days=horizon)
    # 长假
    for s, e, name in HOLIDAY_RANGES:
        sd, ed = _parse(s), _parse(e)
        if d - timedelta(days=5) <= sd <= end:
            events.append({
                "date": s, "days": (sd - d).days, "kind": "假期",
                "title": f"{name}休市 {s} ~ {e}", "impact": "节前流动性收敛，节后波动放大",
            })
    # 消费节点
    for (m, day), title, sectors in CONSUMPTION_EVENTS:
        for y in (d.year, d.year + 1):
            x = date(y, m, day)
            if d <= x <= end:
                events.append({
                    "date": x.isoformat(), "days": (x - d).days, "kind": "人文",
                    "title": title, "impact": f"关注：{sectors}",
                })
    # 两会
    for y in (d.year, d.year + 1):
        x = date(y, 3, 3)
        if d <= x <= end:
            events.append({
                "date": x.isoformat(), "days": (x - d).days, "kind": "政策",
                "title": "全国两会窗口（3月上旬）", "impact": "政策预期集中释放，主题轮动加快",
            })
    # 财报季
    for m, label in ((4, "年报+一季报"), (8, "中报"), (10, "三季报")):
        for y in (d.year, d.year + 1):
            x = date(y, m, 1)
            if d <= x <= end:
                events.append({
                    "date": x.isoformat(), "days": (x - d).days, "kind": "财报",
                    "title": f"{label}披露季", "impact": "业绩验证期，个股分化加大",
                })
    # 股指期货交割：每月第三个周五
    for y in (d.year, d.year + 1):
        for m in range(1, 13):
            first = date(y, m, 1)
            fridays = [first + timedelta(days=i) for i in range(31)
                       if (first + timedelta(days=i)).month == m
                       and (first + timedelta(days=i)).weekday() == 4]
            if len(fridays) >= 3:
                x = fridays[2]
                if d <= x <= end:
                    events.append({
                        "date": x.isoformat(), "days": (x - d).days, "kind": "交割",
                        "title": "股指期货交割日", "impact": "尾盘波动与基差扰动",
                    })
    # 月末/季末
    for y in (d.year, d.year + 1):
        for m in range(1, 13):
            nx = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
            x = nx - timedelta(days=1)
            if d <= x <= end:
                events.append({
                    "date": x.isoformat(), "days": (x - d).days, "kind": "制度",
                    "title": "月末" + ("/季末" if m in (3, 6, 9, 12) else ""),
                    "impact": "机构考核与资金面扰动",
                })
    events.sort(key=lambda e: (e["days"], e["date"]))
    return [e for e in events if -1 <= e["days"] <= horizon][:18]


def humanities_score(d: date | None = None) -> tuple[float, list[str]]:
    """人文日历的轻权重打分（-100~100）。明确标注为背景因子。"""
    d = d or date.today()
    score, notes = 0.0, []
    hol = recent_holiday(d)
    if hol:
        name, delta = hol
        if -3 <= delta < 0:
            score += 6
            notes.append(f"{name}节前{-delta}天：成交趋于清淡，题材更偏防御")
        elif 0 <= delta <= 2:
            score -= 4
            notes.append(f"{name}节后{delta}天：波动放大，方向待确认")
    if d.month in (3, 4):
        score += 3
        notes.append("政策与业绩窗口叠加，主题活跃度提升")
    if d.month in (4, 8, 10):
        score -= 3
        notes.append("财报披露期，业绩不及预期者承压")
    # 月末机构考核
    if d.day >= 26:
        score += 3
        notes.append("临近月末，机构调仓与做净值行为增多")
    # 季末资金面
    if d.month in (3, 6, 9, 12) and d.day >= 26:
        score -= 4
        notes.append("季末资金面偏紧，估值扩张受限")
    # 交割周
    first = d.replace(day=1)
    fridays = [first + timedelta(days=i) for i in range(31)
               if (first + timedelta(days=i)).month == d.month
               and (first + timedelta(days=i)).weekday() == 4]
    if len(fridays) >= 3 and 0 <= (fridays[2] - d).days <= 3:
        score -= 2
        notes.append("临近交割日，尾盘基差扰动")
    if not notes:
        notes.append("无显著人文/制度事件，按中性处理")
    return clamp(score, -100, 100), notes


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------


class RingLogHandler(logging.Handler):
    def __init__(self, capacity: int = 400):
        super().__init__()
        self.buffer: deque[str] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = f"{datetime.fromtimestamp(record.created).strftime('%H:%M:%S')}  {record.getMessage()}"
        except Exception:
            msg = str(record.msg)
        with self._lock:
            self.buffer.append(msg)

    def lines(self) -> list[str]:
        with self._lock:
            return list(self.buffer)


LOG_RING = RingLogHandler()


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("guanlan")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-5s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(LOG_DIR / "guanlan.log", maxBytes=4_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    LOG_RING.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.addHandler(LOG_RING)
    logger.propagate = False
    return logger


log = setup_logging()


def app_meta() -> dict:
    return {"name": APP_NAME, "built": datetime.now().strftime("%Y-%m-%d %H:%M")}


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").replace("&nbsp;", " ").strip()


def pct_color(v: float) -> str:
    if v > 0.001:
        return "#F0544F"
    if v < -0.001:
        return "#22B07D"
    return "#8CA0BE"


def short_symbol(symbol: str) -> str:
    s = str(symbol).upper().replace("SH", "").replace("SZ", "").strip()
    return s.zfill(6) if s.isdigit() else s
