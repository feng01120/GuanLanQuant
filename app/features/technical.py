"""技术因子：均线、动量、波动、量能、支撑压力。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..util import clamp


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def enrich(df: pd.DataFrame, flow: pd.DataFrame | None = None) -> pd.DataFrame:
    """在日线表上追加技术指标列（不修改入参）。"""
    if df is None or len(df) < 30:
        raise ValueError("K 线数据不足（至少 30 根）")
    d = df.copy().reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume", "amount", "pct", "turnover"):
        d[c] = _num(d, c)
    d = d.dropna(subset=["close"]).reset_index(drop=True)
    close, high, low, vol = d["close"], d["high"], d["low"], d["volume"]

    for n in (5, 10, 20, 30, 60, 120):
        d[f"ma{n}"] = close.rolling(n, min_periods=max(2, n // 2)).mean()

    for n in (5, 10, 12, 20, 26, 60):
        d[f"ema{n}"] = close.ewm(span=n, adjust=False).mean()

    # RSI（Wilder）
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    d["rsi"] = 100 - 100 / (1 + rs)
    d["rsi"] = d["rsi"].fillna(50)

    # MACD
    d["macd"] = d["ema12"] - d["ema26"]
    d["macd_signal"] = d["macd"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = (d["macd"] - d["macd_signal"]) * 2

    # 布林带
    mid = close.rolling(20, min_periods=10).mean()
    sd = close.rolling(20, min_periods=10).std(ddof=0)
    d["boll_mid"] = mid
    d["boll_up"] = mid + 2 * sd
    d["boll_low"] = mid - 2 * sd
    d["boll_width"] = (d["boll_up"] - d["boll_low"]) / mid.replace(0, np.nan)

    # ATR
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    # KDJ
    low9 = low.rolling(9, min_periods=4).min()
    high9 = high.rolling(9, min_periods=4).max()
    rsv = (close - low9) / (high9 - low9).replace(0, np.nan) * 100
    d["k"] = rsv.ewm(alpha=1 / 3, adjust=False).mean().fillna(50)
    d["d"] = d["k"].ewm(alpha=1 / 3, adjust=False).mean().fillna(50)
    d["j"] = 3 * d["k"] - 2 * d["d"]

    # 量能
    d["vol_ma5"] = vol.rolling(5, min_periods=3).mean()
    d["vol_ma20"] = vol.rolling(20, min_periods=10).mean()
    d["vol_ratio"] = vol / d["vol_ma5"].replace(0, np.nan)
    d["amount_ma5"] = d["amount"].rolling(5, min_periods=3).mean()

    # 收益率与位置
    d["ret1"] = close.pct_change()
    for n in (3, 5, 10, 20, 60, 120):
        d[f"ret{n}"] = close.pct_change(n)
    d["pos_52w"] = (close - close.rolling(250, min_periods=60).min()) / (
        close.rolling(250, min_periods=60).max() - close.rolling(250, min_periods=60).min()
    ).replace(0, np.nan)
    d["high_52w"] = close.rolling(250, min_periods=60).max()
    d["low_52w"] = close.rolling(250, min_periods=60).min()
    d["dist_ma20"] = close / d["ma20"] - 1
    d["dist_ma60"] = close / d["ma60"] - 1
    d["ma20_slope5"] = d["ma20"].pct_change(5)
    d["ma60_slope10"] = d["ma60"].pct_change(10)
    d["range_pos"] = (close - low) / (high - low).replace(0, np.nan) - 0.5
    d["gap"] = d["open"] / prev_close - 1
    d["atr_pct"] = d["atr"] / close

    # OBV
    direction = np.sign(close.diff()).fillna(0)
    d["obv"] = (direction * vol).cumsum()
    d["obv_slope"] = d["obv"].pct_change(10)

    # 资金流（可选）
    if flow is not None and len(flow) > 0 and "date" in flow.columns:
        f = flow.copy()
        f["date"] = f["date"].astype(str).str[:10]
        f["main"] = pd.to_numeric(f["main"], errors="coerce").fillna(0)
        d["date"] = d["date"].astype(str).str[:10]
        d = d.merge(f[["date", "main"]], on="date", how="left")
        d["main"] = d["main"].fillna(0)
        d["flow_5"] = d["main"].rolling(5, min_periods=1).sum()
        d["flow_ratio5"] = d["flow_5"] / d["amount"].rolling(5, min_periods=1).sum().replace(0, np.nan)
        d["flow_ratio"] = d["main"] / d["amount"].replace(0, np.nan)
    else:
        d["main"] = 0.0
        d["flow_5"] = 0.0
        d["flow_ratio5"] = 0.0
        d["flow_ratio"] = 0.0

    d = d.replace([np.inf, -np.inf], np.nan)
    return d


def _pivots(d: pd.DataFrame, lookback: int = 120, span: int = 3) -> list[float]:
    recent = d.tail(lookback).reset_index(drop=True)
    highs, lows = [], []
    for i in range(span, len(recent) - span):
        h = recent["high"].iloc[i]
        l = recent["low"].iloc[i]
        if h >= recent["high"].iloc[i - span:i + span + 1].max() - 1e-9:
            highs.append(float(h))
        if l <= recent["low"].iloc[i - span:i + span + 1].min() + 1e-9:
            lows.append(float(l))
    return highs + lows


def support_resistance(d: pd.DataFrame) -> tuple[float, float]:
    close = float(d["close"].iloc[-1])
    levels = _pivots(d)
    below = [x for x in levels if x < close * 0.995]
    above = [x for x in levels if x > close * 1.005]
    if not below:
        below = [float(d["low"].tail(60).min())]
    if not above:
        above = [float(d["high"].tail(60).max())]
    support = max(below)
    resistance = min(above)
    if support >= close:
        support = close * 0.97
    if resistance <= close:
        resistance = close * 1.03
    return support, resistance


def trend_score(d: pd.DataFrame) -> tuple[float, list[str]]:
    last = d.iloc[-1]
    parts, notes = [], []

    def add(v, w, text):
        if np.isfinite(v):
            parts.append(float(v) * w)
            notes.append(text)

    ma5, ma20, ma60 = last.get("ma5"), last.get("ma20"), last.get("ma60")
    if all(np.isfinite([ma5, ma20, ma60])):
        if ma5 > ma20 > ma60:
            add(18, 1, "均线多头排列（5>20>60）")
        elif ma5 < ma20 < ma60:
            add(-18, 1, "均线空头排列（5<20<60）")
        else:
            add(0, 1, "均线交织，趋势待选择")
    slope20 = last.get("ma20_slope5")
    slope60 = last.get("ma60_slope10")
    if np.isfinite(slope20):
        add(clamp(float(slope20) * 400, -15, 15), 1,
            f"20日均线5日斜率 {float(slope20) * 100:+.2f}%")
    if np.isfinite(slope60):
        add(clamp(float(slope60) * 250, -12, 12), 1,
            f"60日均线10日斜率 {float(slope60) * 100:+.2f}%")
    for n, w in ((20, 10), (60, 12)):
        v = last.get(f"ret{n}")
        if np.isfinite(v):
            add(clamp(float(v) * 250, -15, 15) * (w / 12), 1,
                f"{n}日动量 {float(v) * 100:+.1f}%")
    hist = last.get("macd_hist")
    if np.isfinite(hist):
        add(clamp(float(hist) / max(1e-6, last["close"]) * 5000, -12, 12), 1,
            "MACD 柱在零轴" + ("上方" if hist > 0 else "下方"))
    pos = last.get("pos_52w")
    if np.isfinite(pos):
        add((float(pos) - 0.55) * 45, 1, f"处于52周区间 {float(pos) * 100:.0f}% 分位")
    rsi = last.get("rsi")
    if np.isfinite(rsi):
        if rsi > 78:
            add(-6, 1, f"RSI {rsi:.1f}，短线过热")
        elif rsi < 22:
            add(5, 1, f"RSI {rsi:.1f}，短线超卖")
        else:
            add((float(rsi) - 50) * 0.15, 1, f"RSI {rsi:.1f}")
    score = clamp(sum(parts), -100, 100)
    return score, notes


def technical_dimension(d: pd.DataFrame) -> dict:
    score, notes = trend_score(d)
    last = d.iloc[-1]
    vol_ratio = last.get("vol_ratio")
    if np.isfinite(vol_ratio):
        if last.get("ret1", 0) > 0 and vol_ratio > 1.2:
            score = clamp(score + 5, -100, 100)
            notes.append(f"放量上涨（量比 {vol_ratio:.2f}）")
        elif last.get("ret1", 0) < 0 and vol_ratio > 1.4:
            score = clamp(score - 6, -100, 100)
            notes.append(f"放量下跌（量比 {vol_ratio:.2f}），抛压偏重")
    atr_pct = last.get("atr_pct")
    if np.isfinite(atr_pct) and atr_pct > 0.045:
        score = clamp(score - 5, -100, 100)
        notes.append(f"ATR 波动率 {atr_pct * 100:.1f}%，波动风险偏高")
    return {"key": "technical", "label": "技术面", "score": round(score, 1),
            "reasons": notes[:7]}


def snapshot(d: pd.DataFrame) -> dict:
    last = d.iloc[-1]
    support, resistance = support_resistance(d)
    keys = ["close", "ma5", "ma10", "ma20", "ma60", "rsi", "macd", "macd_signal", "macd_hist",
            "k", "d", "j", "boll_up", "boll_mid", "boll_low", "atr", "atr_pct", "vol_ratio",
            "ret1", "ret5", "ret20", "ret60", "pos_52w", "dist_ma20", "dist_ma60",
            "high_52w", "low_52w", "flow_ratio5"]
    out = {}
    for k in keys:
        v = last.get(k)
        out[k] = float(v) if v is not None and np.isfinite(v) else 0.0
    out["support"] = float(support)
    out["resistance"] = float(resistance)
    out["trend_score"] = trend_score(d)[0]
    out["date"] = str(last.get("date") or "")
    return out


def volume_profile(d: pd.DataFrame, bins: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """近 120 日成交量价格分布，用于筹码密集区。"""
    recent = d.tail(120)
    lo, hi = float(recent["low"].min()), float(recent["high"].max())
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return np.array([]), np.array([])
    edges = np.linspace(lo, hi, bins + 1)
    idx = np.clip(np.digitize(recent["close"].to_numpy(float), edges) - 1, 0, bins - 1)
    weights = recent["volume"].to_numpy(float)
    acc = np.zeros(bins)
    for i, w in zip(idx, weights):
        acc[i] += w
    centers = (edges[:-1] + edges[1:]) / 2
    return centers, acc / max(1e-9, acc.sum())
