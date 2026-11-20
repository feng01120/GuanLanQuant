"""短周期（T+1 / T+2）预测：Ridge + Logistic + 历史类比，滚动样本外校准。"""
from __future__ import annotations

import math
import time
from datetime import date

import numpy as np
import pandas as pd

from ..util import add_trading_days, clamp, is_pre_holiday, log

FEATURE_NAMES = [
    "ret1", "ret3", "ret5", "ret10", "ret20",
    "ma5_dev", "ma20_dev", "ma60_dev", "ma5_20", "ma20_60",
    "rsi", "macd", "boll", "atr", "volratio", "range", "gap",
    "flow", "mkt", "month", "preholiday",
]


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


class AnalogMatcher:
    """历史形态类比：过去 L 日的收益率/量能形态，找最相似的历史片段。"""

    def __init__(self, close: np.ndarray, volume: np.ndarray, length: int = 12):
        self.close = close
        self.L = length
        n = len(close)
        r = np.diff(np.log(np.maximum(close, 1e-9)), prepend=np.log(max(close[0], 1e-9)))
        self.r = r
        vol_sd = pd.Series(volume).rolling(20, min_periods=10).std().to_numpy(float)
        vmean = pd.Series(volume).rolling(20, min_periods=10).mean().to_numpy(float)
        self.vz = (volume - vmean) / np.where(vol_sd < 1e-9, 1.0, vol_sd)
        # 用近 20 日波动缩放收益率，避免不同波动环境的形态失真
        rvol = pd.Series(r).rolling(20, min_periods=10).std().to_numpy(float)
        rvol = np.where(np.isfinite(rvol) & (rvol > 1e-5), rvol, 1e-4)
        self.z = np.clip(r / rvol, -6, 6)
        self.cum = np.log(np.maximum(close, 1e-9))
        self.windows = []
        for i in range(self.L - 1, n):
            self.windows.append(np.concatenate([self.z[i - self.L + 1:i + 1], [self.vz[i]]]))
        self.windows = np.asarray(self.windows, dtype=float) if self.windows else np.zeros((0, length + 1))
        self.offset = self.L - 1  # window index i -> array row i - offset

    def forecast(self, i: int, h: int, k: int = 28) -> tuple[float, float, int]:
        if i < self.L + 20 or i - h < self.L:
            return 0.0, 0.5, 0
        q = np.concatenate([self.z[i - self.L + 1:i + 1], [self.vz[i]]])
        js = np.arange(self.L - 1, i - h + 1)
        if len(js) < 10:
            return 0.0, 0.5, 0
        rows = js - self.offset
        W = self.windows[rows]
        d2 = np.sum((W - q) ** 2, axis=1)
        finite = np.isfinite(d2)
        if finite.sum() < 10:
            return 0.0, 0.5, 0
        js, d2 = js[finite], d2[finite]
        order = np.argsort(d2)[:min(k, len(d2))]
        dmin = max(1e-9, float(np.median(d2[order])))
        w = np.exp(-d2[order] / (2 * dmin))
        w = w / w.sum()
        fut = self.cum[js[order] + h] - self.cum[js[order]]
        exp_ret = float(np.sum(w * fut))
        prob = float(np.sum(w * (fut > 0)))
        return exp_ret, prob, int(len(order))


def _ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float = 2.5) -> np.ndarray:
    n, k = X.shape
    X1 = np.column_stack([np.ones(n), X])
    A = X1.T @ X1
    A[1:, 1:] += alpha
    b = X1.T @ y
    try:
        return np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(A, b, rcond=None)[0]


def _logit_fit(X: np.ndarray, y: np.ndarray, lam: float = 1.2) -> np.ndarray:
    n, k = X.shape
    X1 = np.column_stack([np.ones(n), X])
    w = np.zeros(k + 1)
    for _ in range(7):
        p = _sigmoid(X1 @ w)
        W = np.clip(p * (1 - p), 1e-6, None)
        grad = X1.T @ (y - p) - lam * np.r_[0.0, w[1:]]
        H = (X1 * W[:, None]).T @ X1
        H[1:, 1:] += lam * np.eye(k)
        try:
            step = np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(H, grad, rcond=None)[0]
        w += np.clip(step, -4, 4)
        if np.max(np.abs(step)) < 1e-8:
            break
    return w


def _logit_predict(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    return _sigmoid(np.column_stack([np.ones(len(X)), X]) @ w)


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    mask = np.isfinite(a) & np.isfinite(b)
    a, b = a[mask], b[mask]
    if len(a) < 10:
        return 0.0
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if np.std(ra) < 1e-9 or np.std(rb) < 1e-9:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def _platt(prob: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """一维 Platt 校准，返回 (a,b)：p_cal = sigmoid(a*logit(p)+b)。"""
    p = np.clip(prob, 0.02, 0.98)
    z = np.log(p / (1 - p))
    a, b = 1.0, 0.0
    X = np.column_stack([z, np.ones(len(z))])
    for _ in range(25):
        q = _sigmoid(X @ np.array([a, b]))
        W = np.clip(q * (1 - q), 1e-6, None)
        grad = X.T @ (y - q) - np.array([0.0, 0.0])
        H = (X * W[:, None]).T @ X
        try:
            step = np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            break
        a += step[0] * 0.5
        b += step[1] * 0.5
        if np.linalg.norm(step) < 1e-7:
            break
    a = clamp(a, 0.25, 1.8)
    b = clamp(b, -1.0, 1.0)
    return float(a), float(b)


class ShortTermEngine:
    def __init__(self, settings=None, min_train: int | None = None):
        self.settings = settings
        self.min_train = int(min_train or (settings.get("min_train", 180) if settings else 180))
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self.last_weights: dict[int, dict] = {}

    # ------------------------------------------------------------------
    def build_features(self, d: pd.DataFrame, market_ret_map: dict[str, float] | None = None) -> pd.DataFrame:
        close = d["close"].to_numpy(float)
        x = pd.DataFrame(index=d.index)
        x["ret1"] = d.get("ret1", pd.Series(0, index=d.index)).to_numpy(float)
        x["ret3"] = d.get("ret3", pd.Series(0, index=d.index)).to_numpy(float)
        x["ret5"] = d.get("ret5", pd.Series(0, index=d.index)).to_numpy(float)
        x["ret10"] = d.get("ret10", pd.Series(0, index=d.index)).to_numpy(float)
        x["ret20"] = d.get("ret20", pd.Series(0, index=d.index)).to_numpy(float)
        x["ma5_dev"] = close / d["ma5"].to_numpy(float) - 1
        x["ma20_dev"] = close / d["ma20"].to_numpy(float) - 1
        x["ma60_dev"] = close / d["ma60"].to_numpy(float) - 1
        x["ma5_20"] = d["ma5"].to_numpy(float) / d["ma20"].to_numpy(float) - 1
        x["ma20_60"] = d["ma20"].to_numpy(float) / d["ma60"].to_numpy(float) - 1
        x["rsi"] = (d["rsi"].to_numpy(float) - 50) / 50
        x["macd"] = d["macd_hist"].to_numpy(float) / np.maximum(close, 1e-6) * 100
        width = (d["boll_up"].to_numpy(float) - d["boll_low"].to_numpy(float)) / 2
        x["boll"] = np.clip((close - d["boll_mid"].to_numpy(float)) / np.where(width < 1e-9, 1e-9, width), -5, 5)
        x["atr"] = d["atr_pct"].to_numpy(float) * 100
        x["volratio"] = np.clip(d["vol_ratio"].to_numpy(float) - 1, -2, 5)
        x["range"] = np.clip(d["range_pos"].to_numpy(float), -0.5, 0.5)
        x["gap"] = np.clip(d["gap"].to_numpy(float), -0.09, 0.09) * 100
        x["flow"] = np.clip(d.get("flow_ratio5", pd.Series(0, index=d.index)).to_numpy(float) * 100, -8, 8)
        dates = d["date"].astype(str).str[:10].tolist()
        x["mkt"] = np.array([float((market_ret_map or {}).get(s, 0.0)) for s in dates]) * 100
        month_phase, pre = [], []
        for s in dates:
            try:
                dd = date.fromisoformat(s)
                month_phase.append((dd.day - 1) / 30.0 * 2 - 1)
                pre.append(1.0 if is_pre_holiday(dd) else 0.0)
            except Exception:
                month_phase.append(0.0)
                pre.append(0.0)
        x["month"] = month_phase
        x["preholiday"] = pre
        x = x.replace([np.inf, -np.inf], np.nan)
        return x

    # ------------------------------------------------------------------
    def _walk_forward(self, X: np.ndarray, y: np.ndarray, cum: np.ndarray,
                      matcher: AnalogMatcher, horizon: int) -> dict:
        n = len(X)
        start = max(self.min_train, 120)
        idxs = list(range(start, n - horizon))
        res = {k: [] for k in ("ridge", "logit", "knn", "actual")}
        for i in idxs:
            Xtr, ytr = X[:i], y[:i]
            mask = np.isfinite(ytr)
            Xtr, ytr = Xtr[mask], ytr[mask]
            if len(Xtr) < 80:
                res["ridge"].append(np.nan)
                res["logit"].append(np.nan)
                res["knn"].append(np.nan)
                res["actual"].append(y[i])
                continue
            mu, sd = Xtr.mean(0), Xtr.std(0)
            sd = np.where(sd < 1e-9, 1.0, sd)
            Xs = (Xtr - mu) / sd
            xt = (X[i] - mu) / sd
            sigma = float(np.std(ytr)) or 0.01
            wr = _ridge_fit(Xs, ytr * 100)
            pr = float(np.r_[1.0, xt] @ wr) / 100
            wl = _logit_fit(Xs, (ytr > 0).astype(float))
            pl = float(_logit_predict(wl, xt[None, :])[0])
            ke, kp, _ = matcher.forecast(i, horizon)
            res["ridge"].append(clamp(pr, -3 * sigma, 3 * sigma))
            res["logit"].append(pl)
            res["knn"].append(kp)
            res["actual"].append(y[i])
        out = {k: np.asarray(v, dtype=float) for k, v in res.items()}
        out["idx"] = np.asarray(idxs)
        out["sigma"] = float(np.std(y[np.isfinite(y)]) or 0.01)
        return out

    # ------------------------------------------------------------------
    def fit_validate(self, d: pd.DataFrame, market_ret_map: dict[str, float] | None = None,
                     horizons=(1, 2), force: bool = False) -> dict:
        key = (str(d["date"].iloc[-1]), len(d), tuple(horizons))
        if not force and key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < 6 * 3600:
                return val
        Xdf = self.build_features(d, market_ret_map)
        close = d["close"].to_numpy(float)
        volume = d["volume"].to_numpy(float)
        cum = np.log(np.maximum(close, 1e-9))
        matcher = AnalogMatcher(close, volume)
        X = Xdf[FEATURE_NAMES].to_numpy(float)
        valid = np.isfinite(X).all(1)
        Xv, cv = X[valid], cum[valid]
        # 用有效行重算 matcher（保持与 Xv 对齐）
        matcher = AnalogMatcher(close[valid], volume[valid])
        result = {"horizons": {}, "features": FEATURE_NAMES, "n_rows": int(valid.sum())}

        for h in horizons:
            y = np.full(len(cv), np.nan)
            if len(cv) > h:
                y[:-h] = np.log(cv[h:] / cv[:-h])
            oos = self._walk_forward(Xv, y, cv, matcher, h)
            idx = oos["idx"]
            if len(idx) < 40:
                result["horizons"][h] = {"horizon": h, "hit": 0.5, "ic": 0.0, "n": 0,
                                         "weights": {"ridge": 0.4, "logit": 0.4, "knn": 0.2},
                                         "note": "样本不足"}
                continue
            actual = oos["actual"]
            sigma = oos["sigma"]
            ridge_exp = oos["ridge"]
            logit_p = np.clip(oos["logit"], 0.02, 0.98)
            logit_exp = (logit_p - 0.5) * 2 * sigma * 1.1
            knn_p = np.clip(oos["knn"], 0.02, 0.98)
            knn_exp = (knn_p - 0.5) * 2 * sigma

            split = int(len(idx) * 0.7)
            early, late = slice(0, split), slice(split, None)
            act_late = actual[late]
            raw = {}
            for name, p in (("ridge", ridge_exp), ("logit", logit_p), ("knn", knn_p)):
                pred_up = (p[early] > 0.5) if name in ("logit", "knn") else (p[early] > 0)
                hit = float(np.mean(pred_up == (actual[early] > 0)))
                raw[name] = max(0.02, max(0.0, hit - 0.42) ** 1.6)
            total = sum(raw.values()) or 1.0
            weights = {k: 0.15 * (1 / 3) + 0.85 * v / total for k, v in raw.items()}
            # 归一化
            s = sum(weights.values())
            weights = {k: v / s for k, v in weights.items()}

            exp_late = (weights["ridge"] * ridge_exp[late] + weights["logit"] * logit_exp[late]
                        + weights["knn"] * knn_exp[late])
            p_late_raw = (weights["ridge"] * _sigmoid(ridge_exp[late] / max(1e-6, 1.2 * sigma))
                          + weights["logit"] * logit_p[late]
                          + weights["knn"] * knn_p[late])
            a, b = _platt(p_late_raw, (act_late > 0).astype(float))
            p_late = _sigmoid(a * np.log(np.clip(p_late_raw, 0.02, 0.98) /
                                          (1 - np.clip(p_late_raw, 0.02, 0.98))) + b)

            hit = float(np.mean((p_late > 0.5) == (act_late > 0)))
            ic = _spearman(exp_late, act_late)
            mae = float(np.mean(np.abs(act_late - exp_late)))
            resid = act_late - exp_late
            q10, q90 = np.quantile(resid, [0.1, 0.9]) if len(resid) > 10 else (-sigma, sigma)
            q10 = min(float(q10), -1.28 * sigma)
            q90 = max(float(q90), 1.28 * sigma)

            bins = [(0.0, 0.45), (0.45, 0.5), (0.5, 0.55), (0.55, 0.6), (0.6, 0.7), (0.7, 1.01)]
            calibration = []
            for lo, hi in bins:
                m = (p_late >= lo) & (p_late < hi)
                if m.sum() >= 3:
                    calibration.append({"bin": f"{lo:.2f}-{hi:.2f}", "pred": float(np.mean(p_late[m])),
                                        "real": float(np.mean(act_late[m] > 0)), "n": int(m.sum())})

            equity = []
            n_trades = 0
            if h == 1:
                pos = 0.0
                eq = 1.0
                for j in range(len(p_late)):
                    new_pos = 1.0 if p_late[j] > 0.56 else 0.0
                    if new_pos != pos:
                        n_trades += 1
                    cost = 0.0006 if new_pos != pos else 0.0
                    eq *= 1 + new_pos * float(act_late[j]) - cost
                    pos = new_pos
                    equity.append(float(eq))
                peak = 1.0
                max_dd = 0.0
                for v in equity:
                    peak = max(peak, v)
                    max_dd = min(max_dd, v / peak - 1)
            else:
                max_dd = 0.0
            result["horizons"][h] = {
                "horizon": h, "hit": round(hit, 4), "ic": round(ic, 4), "mae": round(mae, 6),
                "n": int(len(p_late)), "weights": {k: round(v, 3) for k, v in weights.items()},
                "sigma": sigma, "q10": float(q10), "q90": float(q90),
                "calibration": calibration, "equity": equity, "max_dd": round(max_dd, 4),
                "n_trades": int(n_trades),
                "platt": [a, b], "oos": {"idx": idx.tolist(), "prob": p_late.tolist(),
                                         "actual": actual.tolist(), "exp": exp_late.tolist()},
                "method_note": "权重用前70%样本外表现确定，指标在后30%样本外计算",
            }
        val = result
        self._cache[key] = (time.time(), val)
        return val

    # ------------------------------------------------------------------
    def predict(self, d: pd.DataFrame, market_ret_map: dict[str, float] | None = None,
                horizons=(1, 2), validation: dict | None = None) -> dict:
        validation = validation or self.fit_validate(d, market_ret_map, horizons)
        Xdf = self.build_features(d, market_ret_map)
        X = Xdf[FEATURE_NAMES].to_numpy(float)
        valid = np.isfinite(X).all(1)
        if valid.sum() < 80:
            raise ValueError("有效特征行不足")
        valid_pos = np.where(valid)[0]
        idx_last = len(valid_pos) - 1
        row_pos = int(valid_pos[-1])
        Xv = X[valid]
        close = d["close"].to_numpy(float)[valid]
        volume = d["volume"].to_numpy(float)[valid]
        matcher = AnalogMatcher(close, volume)
        last_date = str(d["date"].iloc[row_pos])[:10]
        out = {}
        for h in horizons:
            y = np.full(len(close), np.nan)
            if len(close) > h:
                y[:-h] = np.log(close[h:] / close[:-h])
            mask = np.isfinite(y)
            Xtr, ytr = Xv[mask], y[mask]
            mu, sd = Xtr.mean(0), Xtr.std(0)
            sd = np.where(sd < 1e-9, 1.0, sd)
            Xs = (Xtr - mu) / sd
            xt = (Xv[idx_last] - mu) / sd
            sigma = float(np.std(ytr)) or 0.01
            wr = _ridge_fit(Xs, ytr * 100)
            ridge_exp = float(np.r_[1.0, xt] @ wr) / 100
            wl = _logit_fit(Xs, (ytr > 0).astype(float))
            logit_p = float(_logit_predict(wl, xt[None, :])[0])
            knn_exp, knn_p, knn_n = matcher.forecast(idx_last, h)
            vh = validation["horizons"].get(h) or {}
            weights = vh.get("weights") or {"ridge": 0.4, "logit": 0.4, "knn": 0.2}
            exp_raw = (weights["ridge"] * clamp(ridge_exp, -2.2 * sigma, 2.2 * sigma)
                       + weights["logit"] * (logit_p - 0.5) * 2 * sigma * 1.1
                       + weights["knn"] * knn_exp)
            p_raw = (weights["ridge"] * _sigmoid(ridge_exp / max(1e-6, 1.2 * sigma))
                     + weights["logit"] * logit_p + weights["knn"] * knn_p)
            a, b = vh.get("platt") or (1.0, 0.0)
            pc = clamp(p_raw, 0.02, 0.98)
            p_cal = float(_sigmoid(a * math.log(pc / (1 - pc)) + b))
            # 用训练样本的条件收益把概率与期望收益对齐
            mu_up = float(np.mean(ytr[ytr > 0])) if np.any(ytr > 0) else sigma
            mu_dn = float(np.mean(-ytr[ytr < 0])) if np.any(ytr < 0) else sigma
            exp_prob = p_cal * mu_up - (1 - p_cal) * mu_dn
            exp = 0.55 * exp_raw + 0.45 * exp_prob
            q10, q90 = vh.get("q10", -1.28 * sigma), vh.get("q90", 1.28 * sigma)
            hit = float(vh.get("hit", 0.5))
            n_eval = int(vh.get("n", 0))
            agree = int(np.sign(ridge_exp) == np.sign(logit_p - 0.5) == np.sign(knn_exp))
            conf = clamp(48 + (hit - 0.5) * 240 + (6 if agree else -8) + min(6, n_eval / 40), 8, 82)
            out[h] = {
                "horizon": h, "prob_up": round(p_cal, 4), "exp_ret": round(exp * 100, 3),
                "low": round((exp + q10) * 100, 3), "high": round((exp + q90) * 100, 3),
                "confidence": round(conf, 1), "hit_rate": hit, "ic": vh.get("ic", 0.0),
                "n_eval": n_eval, "weights": weights,
                "parts": {"ridge": round(ridge_exp * 100, 3), "logit": round((logit_p - 0.5) * 100, 2),
                          "knn": round(knn_exp * 100, 3), "knn_neighbors": knn_n},
                "sigma": round(sigma * 100, 3),
                "target_date": add_trading_days(date.fromisoformat(last_date), h).isoformat(),
                "last_date": last_date,
            }
        self.last_weights = {h: out[h]["weights"] for h in out}
        return out
