"""长周期（5/10/20 交易日）趋势与蒙特卡洛区间。"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from ..util import add_trading_days, clamp, pct_rank


def _trend_series(d: pd.DataFrame) -> np.ndarray:
    close = d["close"].to_numpy(float)
    ma5, ma20, ma60 = (d["ma5"].to_numpy(float), d["ma20"].to_numpy(float),
                       d["ma60"].to_numpy(float))
    slope20 = np.nan_to_num(d["ma20_slope5"].to_numpy(float))
    slope60 = np.nan_to_num(d["ma60_slope10"].to_numpy(float))
    ret20 = np.nan_to_num(d["ret20"].to_numpy(float))
    ret60 = np.nan_to_num(d["ret60"].to_numpy(float))
    hist = np.nan_to_num(d["macd_hist"].to_numpy(float))
    pos = d["pos_52w"].to_numpy(float)
    rsi = np.nan_to_num(d["rsi"].to_numpy(float), nan=50.0)

    align = np.where((ma5 > ma20) & (ma20 > ma60), 18,
                     np.where((ma5 < ma20) & (ma20 < ma60), -18, 0))
    s = (align
         + np.clip(slope20 * 400, -15, 15)
         + np.clip(slope60 * 250, -12, 12)
         + np.clip(ret20 * 250, -15, 15)
         + np.clip(ret60 * 250, -12, 12)
         + np.clip(hist / np.maximum(close, 1e-6) * 5000, -12, 12)
         + np.where(np.isfinite(pos), (pos - 0.55) * 45, 0)
         + np.clip((rsi - 50) * 0.12, -5, 5))
    return np.clip(np.nan_to_num(s), -100, 100)


def _valuation_series(d: pd.DataFrame) -> np.ndarray:
    close = d["close"].to_numpy(float)
    out = np.zeros(len(close))
    for i in range(len(close)):
        w = close[max(0, i - 750):i + 1]
        if len(w) >= 60:
            out[i] = (0.5 - float(np.mean(w <= close[i]))) * 38
    return out


class LongTermEngine:
    def __init__(self, settings=None, paths: int | None = None):
        self.settings = settings
        self.paths = int(paths or (settings.get("monte_carlo_paths", 2600) if settings else 2600))
        self._cache: dict[tuple, dict] = {}

    # ------------------------------------------------------------------
    def validate(self, d: pd.DataFrame, horizon: int = 20) -> dict:
        key = (str(d["date"].iloc[-1]), len(d), horizon)
        if key in self._cache:
            return self._cache[key]
        trend = _trend_series(d)
        close = d["close"].to_numpy(float)
        n = len(close)
        rets, scores = [], []
        start = max(180, n - 420)
        for i in range(start, n - horizon):
            ret = math.log(close[i + horizon] / close[i])
            rets.append(ret)
            scores.append(trend[i])
        rets = np.asarray(rets)
        scores = np.asarray(scores)
        hit = float(np.mean((scores > 0) == (rets > 0))) if len(rets) else 0.5
        ra = pd.Series(scores).rank().to_numpy()
        rb = pd.Series(rets).rank().to_numpy()
        ic = float(np.corrcoef(ra, rb)[0, 1]) if len(rets) > 10 and np.std(ra) > 0 else 0.0
        out = {"horizon": horizon, "hit": round(hit, 4), "ic": round(ic, 4),
               "n": int(len(rets)), "note": "仅用趋势因子做历史验证，不含实时情绪/宏观"}
        self._cache[key] = out
        return out

    # ------------------------------------------------------------------
    def forecast(self, d: pd.DataFrame, dimensions: dict[str, dict], quote,
                 last_close: float | None = None) -> dict:
        close_all = d["close"].to_numpy(float)
        last_close = float(last_close if last_close is not None else close_all[-1])
        r = np.diff(np.log(np.maximum(close_all, 1e-9)))
        # EWMA 波动率
        lam = 0.94
        vol = np.zeros(len(r))
        v = float(np.std(r[-60:])) if len(r) >= 60 else float(np.std(r)) if len(r) > 2 else 0.02
        for i, x in enumerate(r):
            v = math.sqrt(lam * v * v + (1 - lam) * x * x)
            vol[i] = v
        daily_vol = max(0.008, float(vol[-1]))
        z = r / np.where(vol > 1e-8, vol, 1e-8)
        z = np.clip(z[-400:], -5, 5)
        z = z[np.isfinite(z)]
        if len(z) < 30:
            z = np.random.default_rng(7).normal(0, 1, 200)

        tech = dimensions.get("technical", {}).get("score", 0)
        val = dimensions.get("valuation", {}).get("score", 0)
        mac = dimensions.get("macro", {}).get("score", 0)
        sen = dimensions.get("sentiment", {}).get("score", 0)
        hum = dimensions.get("humanities", {}).get("score", 0)
        total = 0.55 * tech + 0.15 * val + 0.18 * mac + 0.07 * sen + 0.05 * hum
        drift = math.tanh(total / 55) * 0.0035

        rng = np.random.default_rng(20261120)
        days = 25
        shocks = rng.choice(z, size=(self.paths, days), replace=True) * daily_vol
        path = np.cumsum(np.full((self.paths, days), drift) + shocks, axis=1)
        price = last_close * np.exp(path)

        fan_days = list(range(days + 1))
        fan_price = np.column_stack([np.full(self.paths, last_close), price])
        q = {f"q{p}": np.quantile(fan_price, p / 100, axis=0).tolist() for p in (5, 25, 50, 75, 95)}

        horizons = {}
        last_date = date.fromisoformat(str(d["date"].iloc[-1])[:10])
        for h in (5, 10, 20):
            cum = path[:, h - 1]
            horizons[h] = {
                "horizon": h,
                "prob_up": round(float(np.mean(cum > 0)), 4),
                "exp_ret": round(float(np.mean(cum)) * 100, 3),
                "median_ret": round(float(np.median(cum)) * 100, 3),
                "low": round(float(np.quantile(cum, 0.1)) * 100, 3),
                "high": round(float(np.quantile(cum, 0.9)) * 100, 3),
                "price_low": round(float(last_close * math.exp(np.quantile(cum, 0.1))), 2),
                "price_high": round(float(last_close * math.exp(np.quantile(cum, 0.9))), 2),
                "target_date": add_trading_days(last_date, h).isoformat(),
                "var95": round(float(np.quantile(cum, 0.05)) * 100, 3),
            }
        # 最大回撤分布
        run_max = np.maximum.accumulate(price, axis=1)
        dd = price / run_max - 1
        max_dd = float(np.median(np.min(dd, axis=1)))

        v20 = self.validate(d, 20)
        validations = {h: (v20 if h == 20 else self.validate(d, h)) for h in (5, 10, 20)}
        conf = clamp(50 + (v20["hit"] - 0.5) * 220, 8, 88)

        return {
            "total_score": round(total, 1), "drift_daily": round(drift * 100, 4),
            "vol_daily": round(daily_vol * 100, 3), "vol_annual": round(daily_vol * math.sqrt(252) * 100, 1),
            "horizons": horizons, "fan": {"days": fan_days, **{k: [round(x, 3) for x in vv] for k, vv in q.items()}},
            "last_close": round(last_close, 2), "max_dd": round(max_dd * 100, 2),
            "paths": self.paths, "confidence": round(conf, 1),
            "validation": v20, "validations": validations,
            "components": {"technical": tech, "valuation": val, "macro": mac,
                           "sentiment": sen, "humanities": hum},
        }
