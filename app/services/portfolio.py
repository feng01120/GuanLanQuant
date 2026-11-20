"""模拟组合与风险分析（纯 dry-run，不接任何实盘接口）。"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..util import clamp, money, pct, price


class PortfolioService:
    def __init__(self, store, market):
        self.store = store
        self.market = market

    # ------------------------------------------------------------------
    def positions(self) -> list[dict]:
        rows = self.store.portfolio_list()
        if not rows:
            return []
        symbols = list({r["symbol"] for r in rows})
        quotes = self.market.refresh_quotes(symbols)
        out = []
        for r in rows:
            q = quotes.get(r["symbol"])
            px = float(q.price) if q else float(r["cost"])
            prev = float(q.prev_close) if q and q.prev_close else px
            mv = px * float(r["qty"])
            cost = float(r["cost"]) * float(r["qty"])
            pnl = mv - cost
            out.append({
                "id": r["id"], "symbol": r["symbol"], "name": r["name"] or (q.name if q else ""),
                "qty": float(r["qty"]), "cost": float(r["cost"]), "price": px,
                "prev_close": prev, "market_value": mv, "pnl": pnl,
                "pnl_pct": (pnl / cost * 100) if cost else 0.0,
                "day_pnl": (px - prev) * float(r["qty"]),
                "weight": 0.0,
            })
        total = sum(x["market_value"] for x in out)
        for x in out:
            x["weight"] = x["market_value"] / total if total else 0.0
        return out

    # ------------------------------------------------------------------
    def _returns_frame(self, symbols: list[str], days: int = 90) -> pd.DataFrame:
        frames = []
        for s in symbols:
            try:
                self.market.ensure_bars(s, max(60, days + 10))
            except Exception:
                pass
            df = self.store.get_bars(s, days + 10)
            if df.empty or len(df) < 10:
                continue
            df = df[["date", "close"]].copy()
            df["date"] = df["date"].astype(str).str[:10]
            df[s] = pd.to_numeric(df["close"], errors="coerce").pct_change()
            frames.append(df[["date", s]].set_index("date"))
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, axis=1).dropna(how="all")
        return out.dropna()

    def analytics(self, positions: list[dict] | None = None) -> dict:
        pos = positions if positions is not None else self.positions()
        total = sum(x["market_value"] for x in pos)
        total_cost = sum(x["qty"] * x["cost"] for x in pos)
        day = sum(x["day_pnl"] for x in pos)
        pnl = sum(x["pnl"] for x in pos)
        weights = np.array([x["weight"] for x in pos]) if pos else np.array([])
        symbols = [x["symbol"] for x in pos]
        rets = self._returns_frame(symbols) if symbols else pd.DataFrame()
        vol_annual = 0.0
        var95 = 0.0
        max_dd = 0.0
        sharpe = 0.0
        series = []
        if len(rets) >= 10 and len(rets.columns) > 0:
            r = rets.to_numpy(float)
            w = np.array([weights[symbols.index(s)] if s in symbols else 0
                          for s in rets.columns], dtype=float)
            if w.sum() > 0:
                w = w / w.sum()
            port = r @ w
            vol_daily = float(np.std(port))
            vol_annual = vol_daily * math.sqrt(252) * 100
            var95 = 1.645 * vol_daily * total
            eq = np.cumprod(1 + port)
            peak = np.maximum.accumulate(eq)
            max_dd = float(np.min(eq / peak - 1)) * 100
            sharpe = float(np.mean(port) / (vol_daily + 1e-9) * math.sqrt(252))
            series = [float(x) for x in eq]
        conc = float(max(weights)) if len(weights) else 0.0
        risk_flags = []
        if conc > 0.35:
            risk_flags.append(f"单一持仓占比 {conc * 100:.0f}%，集中度偏高")
        if vol_annual > 35:
            risk_flags.append(f"组合年化波动 {vol_annual:.1f}%，风险预算偏高")
        if total > 0 and len(pos) < 4:
            risk_flags.append("持仓数量少于 4 只，分散不足")
        if not pos:
            risk_flags.append("当前为空仓；以下风险指标为 0")
        if not risk_flags:
            risk_flags.append("未触发主要集中度/波动阈值")
        return {
            "n": len(pos), "market_value": total, "cost": total_cost, "pnl": pnl,
            "pnl_pct": (pnl / total_cost * 100) if total_cost else 0.0,
            "day_pnl": day, "day_pct": (day / (total - day) * 100) if total - day else 0.0,
            "vol_annual": round(vol_annual, 1), "var95": round(var95, 0),
            "max_dd": round(max_dd, 1), "sharpe": round(sharpe, 2),
            "concentration": round(conc * 100, 1), "curve": series,
            "risk_flags": risk_flags,
        }

    # ------------------------------------------------------------------
    def add(self, symbol: str, qty: float, cost: float, name: str = "") -> dict:
        if not name:
            cached = self.store.get_quote(symbol) or {}
            name = str(cached.get("name") or symbol)
        pid = self.store.portfolio_add(symbol, name, qty, cost)
        return {"id": pid, "symbol": symbol, "name": name, "qty": qty, "cost": cost}

    def update(self, pid: int, qty: float, cost: float) -> None:
        self.store.portfolio_update(pid, qty, cost)

    def delete(self, pid: int) -> None:
        self.store.portfolio_delete(pid)

    # ------------------------------------------------------------------
    def rebalance(self, positions: list[dict] | None = None) -> list[dict]:
        pos = positions if positions is not None else self.positions()
        if not pos:
            return []
        total = sum(x["market_value"] for x in pos)
        scores = {}
        for x in pos:
            cached = self.market._analysis_cache.get(x["symbol"])
            scores[x["symbol"]] = cached[1]["fused"]["total"] if cached else 0.0
        raw = {}
        for x in pos:
            s = scores.get(x["symbol"], 0.0)
            raw[x["symbol"]] = max(0.02, 1.0 + s / 180.0)
        norm = sum(raw.values())
        out = []
        for x in pos:
            target_w = raw[x["symbol"]] / norm
            target_val = total * target_w
            delta_val = target_val - x["market_value"]
            delta_shares = int(delta_val / max(1e-6, x["price"]) / 100) * 100
            out.append({
                "symbol": x["symbol"], "name": x["name"], "current": round(x["weight"] * 100, 1),
                "target": round(target_w * 100, 1), "delta_value": round(delta_val, 0),
                "delta_shares": delta_shares, "score": scores.get(x["symbol"], 0.0),
                "action": "买入" if delta_shares > 0 else "卖出" if delta_shares < 0 else "不动",
            })
        return out

    def dry_run_orders(self, rebalances: list[dict]) -> list[dict]:
        orders = []
        for r in rebalances:
            if r["delta_shares"] == 0:
                continue
            orders.append({
                "symbol": r["symbol"], "name": r["name"], "side": r["action"],
                "shares": abs(r["delta_shares"]), "est_value": abs(r["delta_value"]),
                "mode": "DRY-RUN", "approved": False,
            })
        return orders
