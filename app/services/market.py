"""市场服务：取数、因子装配、模型调用、研判编排。"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from ..config import DEFAULT_WATCHLIST, INDICES
from ..data.http import HttpClient
from ..data.models import Quote
from ..data.sources import EastmoneySource, OfficialSource, symbol_to_secid
from ..data.store import Store
from ..features import fund, humanities, sentiment, technical, valuation
from ..features.fusion import fuse
from ..features.macro import build_context
from ..kernel.registry import PluginRegistry
from ..models.long_term import LongTermEngine
from ..models.short_term import ShortTermEngine
from ..research.agents import build_research
from ..research.report import build_html, build_markdown
from ..util import (add_trading_days, is_trading_day, log, market_phase, prev_trading_day,
                    safe_float, session_progress)
from ..config import Settings


def _circuit_open(error: Exception | str) -> bool:
    """主机熔断是预期降级，不应按源故障在每个刷新周期重复刷屏。"""
    return "已熔断" in str(error)


class MarketService:
    def __init__(self, settings: Settings, store: Store, registry: PluginRegistry,
                 http: HttpClient | None = None):
        self.settings = settings
        self.store = store
        self.registry = registry
        self.http = http or HttpClient()
        self.short_engine = ShortTermEngine(settings)
        self.long_engine = LongTermEngine(settings)
        self._ctx_cache: tuple[float, dict | None] = (0.0, None)
        self._breadth_cache: tuple[float, dict] = (0.0, {})
        self._analysis_cache: dict[str, tuple[float, dict]] = {}
        self._flow_cache: dict[str, tuple[float, pd.DataFrame]] = {}
        self._ann_cache: dict[str, tuple[float, list]] = {}
        self._last_bar_fetch: dict[str, float] = {}
        self._bar_fail_at: dict[str, float] = {}
        self._lock = threading.RLock()
        self._analyze_lock = threading.RLock()
        self._saved: dict[tuple, float] = {}

    # ------------------------------------------------------------------ 行情
    def _quotes(self, symbols: list[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        # 批量接口可能只返回部分标的，不能一有结果就 return；
        # 先把各数据源的批量结果合并，再逐个补齐缺失项。
        for m, inst in self.registry.providers("quote.realtime"):
            fn = getattr(inst, "quotes", None)
            if callable(fn):
                try:
                    got = fn(symbols)
                    if got:
                        # 批量结果按优先级“先到先得”，后面的备用源只补缺失标的，
                        # 不能用字段更少的报价覆盖前面的完整报价。
                        for k, v in got.items():
                            if k in out or v is None:
                                continue
                            if float(getattr(v, "price", 0) or 0) <= 0:
                                continue
                            out[k] = v
                except Exception as e:
                    if not _circuit_open(e):
                        log.warning(f"{m.id} 批量报价失败: {e}")
        missing = [s for s in symbols if s not in out]
        for s in missing:
            for m, inst in self.registry.providers("quote.realtime"):
                fn = getattr(inst, "quote", None)
                if not callable(fn):
                    continue
                try:
                    q = fn(s)
                    if q and q.price > 0:
                        out[s] = q
                        break
                except Exception:
                    continue
        return out

    def refresh_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        qs = self._quotes(symbols)
        for q in qs.values():
            try:
                self.store.save_quote(q)
            except Exception:
                pass
        return qs

    def ensure_bars(self, symbol: str, limit: int | None = None, force: bool = False,
                    quote: Quote | None = None) -> pd.DataFrame:
        limit = int(limit or self.settings.get("history_days", 900))
        now = time.time()
        df = self.store.get_bars(symbol, limit)
        today = date.today()
        if is_trading_day(today) and datetime.now().time() >= dtime(9, 35):
            min_date = today.isoformat()
        else:
            min_date = prev_trading_day(today).isoformat()
        fresh = (len(df) >= 120 and str(df["date"].iloc[-1])[:10] >= min_date
                 and ((now - self._last_bar_fetch.get(symbol, 0)) < 900
                      or (datetime.now().time() >= dtime(15, 0)
                          and str(df["date"].iloc[-1])[:10] == today.isoformat()))
                 and not force)
        if fresh:
            return self._stamp_quote_amount(symbol, df, quote)
        # 刚失败过的标的不要在每次切页/刷新时重新跑完整数据源链；
        # 有本地 K 线就先使用，120 秒后再探测一次。
        failed_at = self._bar_fail_at.get(symbol, 0.0)
        if not force and len(df) >= 30 and now - failed_at < 120:
            return self._stamp_quote_amount(symbol, df, quote)
        fetched = []
        try:
            fetched, src = self.registry.call_chain("bar.daily", "bars", symbol, limit)
            log.info(f"K线 {symbol}: {len(fetched)} 根，来源 {src}")
        except Exception as e:
            self._bar_fail_at[symbol] = now
            if not _circuit_open(e):
                log.warning(f"K线获取失败 {symbol}: {e}")
        if fetched:
            self._bar_fail_at.pop(symbol, None)
            try:
                self.store.upsert_bars(symbol, fetched)
            except Exception as e:
                log.warning(f"K线入库失败 {symbol}: {e}")
            self._last_bar_fetch[symbol] = now
            df = self.store.get_bars(symbol, limit)
        else:
            self._bar_fail_at[symbol] = now
        if len(df) < 30:
            raise RuntimeError(f"{symbol} K线不足（{len(df)} 根）")
        return self._stamp_quote_amount(symbol, df, quote)

    def _stamp_quote_amount(self, symbol: str, df: pd.DataFrame,
                            quote: Quote | None) -> pd.DataFrame:
        """把实时报价的成交额补到当天日 K；只补 0 值，不改历史真实值。"""
        if quote is None or df is None or df.empty:
            return df
        amount = float(getattr(quote, "amount", 0) or 0)
        if amount <= 0:
            return df
        last = str(df["date"].iloc[-1])[:10]
        if last != date.today().isoformat():
            return df
        try:
            current = float(df["amount"].iloc[-1] or 0)
        except Exception:
            current = 0.0
        if current > 0 and current >= amount * 0.5:
            return df
        try:
            self.store.set_bar_amount(symbol, last, amount)
            df.loc[df.index[-1], "amount"] = amount
        except Exception as e:
            log.debug(f"补成交额失败 {symbol}: {e}")
        return df

    def _flow(self, symbol: str) -> pd.DataFrame:
        ts, cached = self._flow_cache.get(symbol, (0.0, None))
        if cached is not None and time.time() - ts < 900:
            return cached
        inst = self.registry.get("datasource.eastmoney")
        df = pd.DataFrame()
        if inst is not None:
            try:
                rows = inst.money_flow(symbol, 90)
                if rows:
                    df = pd.DataFrame(rows)
            except Exception as e:
                if not _circuit_open(e):
                    log.warning(f"资金流失败 {symbol}: {e}")
        self._flow_cache[symbol] = (time.time(), df)
        return df

    # ------------------------------------------------------------------ 市场上下文
    def _breadth_fallback(self) -> dict:
        ts, cached = self._breadth_cache
        if cached and time.time() - ts < 300:
            return cached
        sina = self.registry.get("datasource.sina")
        if sina is None:
            return {}
        try:
            mb = sina.market_breadth()
            if mb and int(mb.get("up", 0)) + int(mb.get("down", 0)) > 0:
                self._breadth_cache = (time.time(), mb)
                return mb
        except Exception as e:
            log.warning(f"新浪全市场宽度补数失败: {e}")
        # 失败也记 5 分钟，避免每个页面/每次总览都重试几十页。
        self._breadth_cache = (time.time(), {})
        return {}

    def market_context(self, force: bool = False) -> dict:
        ts, cached = self._ctx_cache
        if cached is not None and time.time() - ts < 300 and not force:
            return cached
        with self._lock:
            ts, cached = self._ctx_cache
            if cached is not None and time.time() - ts < 300 and not force:
                return cached
            idx_symbols = [s for s, _, _ in INDICES]
            iq = self._quotes(idx_symbols)
            sh = iq.get("1.000001")
            sz = iq.get("0.399001")
            up = (sh.up_count or 0) + (sz.up_count or 0) if sh and sz else 0
            down = (sh.down_count or 0) + (sz.down_count or 0) if sh and sz else 0
            flat = (sh.flat_count or 0) + (sz.flat_count or 0) if sh and sz else 0
            amount = (sh.amount if sh else 0.0) + (sz.amount if sz else 0.0)
            if up + down == 0:
                # 东财 ulist 空响应时，用新浪全市场分页补宽度；
                # 这里统一补一次，总览/荐股/情绪都受益，且 5 分钟内复用。
                mb = self._breadth_fallback()
                if mb:
                    up = int(mb.get("up") or 0)
                    down = int(mb.get("down") or 0)
                    flat = int(mb.get("flat") or 0)
                    if amount <= 0:
                        amount = float(mb.get("amount") or 0.0)
            breadth = up / max(1, up + down)
            progress = session_progress()
            amount_est = amount / max(0.02, progress) if progress < 0.98 else amount
            index_pct = sh.pct if sh else 0.0

            # 成交额历史（沪 + 深）
            amount_hist: list[float] = []
            try:
                a = self.ensure_bars("1.000001", 160, quote=sh)
                b = self.ensure_bars("0.399001", 160, quote=sz)
                m = pd.merge(a[["date", "amount"]], b[["date", "amount"]], on="date", how="inner",
                             suffixes=("_sh", "_sz"))
                raw = (m["amount_sh"].fillna(0) + m["amount_sz"].fillna(0)).tolist()
                if raw and progress < 0.98:
                    raw = raw[:-1]  # 去掉未走完的当日
                # 腾讯/新浪 K 线没有成交额字段，早期回退数据里是 0；
                # 成交额分位只使用真实的正值，避免把历史分位算成 0。
                amount_hist = [float(x) for x in raw if float(x) > 0]
            except Exception as e:
                log.warning(f"成交额历史失败: {e}")

            # 涨停/跌停
            limit_up, limit_down, pool = 0, 0, {}
            inst = self.registry.get("datasource.eastmoney")
            if inst is not None:
                try:
                    pool = inst.limit_pool()
                    limit_up, limit_down = pool.get("up_count", 0), pool.get("down_count", 0)
                except Exception as e:
                    log.warning(f"涨停池失败: {e}")

            # 资讯
            news = []
            if inst is not None:
                try:
                    news = inst.news(30)
                except Exception as e:
                    log.warning(f"资讯失败: {e}")

            # 宏观
            official = self.registry.get("datasource.official") or OfficialSource(self.http)
            points, fx = [], []
            try:
                points = official.macro_points()
            except Exception as e:
                log.warning(f"宏观指标失败: {e}")
            try:
                fx = official.fx_history("USD/CNY", 60)
            except Exception as e:
                log.warning(f"汇率失败: {e}")
            bond_df = pd.DataFrame()
            try:
                bond_df = self.ensure_bars("511010", 90)
            except Exception as e:
                log.warning(f"国债ETF失败: {e}")
            commodities = self._quotes(["101.GC00Y", "102.CL00Y"])
            gold_q = next((q for q in commodities.values() if "黄金" in q.name), None)
            oil_q = next((q for q in commodities.values() if "原油" in q.name), None)
            gold_pct = gold_q.pct if gold_q else 0.0
            oil_pct = oil_q.pct if oil_q else 0.0

            sdim = sentiment.sentiment_dimension(news, breadth, limit_up, limit_down,
                                                 amount_est, amount_hist, index_pct)
            macro_ctx = build_context(points, fx, bond_df, gold_pct, oil_pct, amount_hist, index_pct)
            try:
                self.store.save_sentiment(sdim["score"], breadth, limit_up, limit_down, amount,
                                          sdim.get("label_text", ""))
            except Exception:
                pass
            ctx = {
                "quotes": iq, "up": up, "down": down, "flat": flat, "breadth": breadth,
                "amount": amount, "amount_est": amount_est, "progress": progress,
                "amount_history": amount_hist, "index_pct": index_pct,
                "limit_up": limit_up, "limit_down": limit_down, "pool": pool,
                "news": news, "scored_news": sdim.get("news", []), "sentiment": sdim,
                "macro": macro_ctx, "gold_pct": gold_pct, "oil_pct": oil_pct,
                "gold_available": bool(gold_q), "oil_available": bool(oil_q),
                "updated": datetime.now().strftime("%H:%M:%S"),
            }
            self._ctx_cache = (time.time(), ctx)
            return ctx

    # ------------------------------------------------------------------ 个股分析
    def _announcements(self, symbol: str, name: str) -> list:
        ts, cached = self._ann_cache.get(symbol, (0.0, None))
        if cached is not None and time.time() - ts < 1800:
            return cached
        out = []
        official = self.registry.get("datasource.official")
        if official is not None:
            try:
                out = official.cninfo(symbol, days=180, limit=8)
            except Exception as e:
                log.warning(f"巨潮公告失败 {symbol}: {e}")
        if not out:
            inst = self.registry.get("datasource.eastmoney")
            if inst is not None:
                try:
                    out = inst.announcements(symbol, 8)
                except Exception:
                    out = []
        self._ann_cache[symbol] = (time.time(), out)
        return out

    def analyze(self, symbol: str, force: bool = False, persist: bool = False) -> dict:
        with self._analyze_lock:
            return self._analyze(symbol, force=force, persist=persist)

    def _analyze(self, symbol: str, force: bool = False, persist: bool = False) -> dict:
        symbol = str(symbol).strip()
        ts, cached = self._analysis_cache.get(symbol, (0.0, None))
        if cached is not None and time.time() - ts < 480 and not force:
            return cached
        ctx = self.market_context()
        quote = ctx["quotes"].get(symbol)
        if quote is None:
            quote = self.refresh_quotes([symbol]).get(symbol)
        df = self.ensure_bars(symbol, quote=quote)
        flow = self._flow(symbol)
        d = technical.enrich(df, flow if len(flow) else None)
        snap = technical.snapshot(d)

        # 市场收益特征
        market_map = {}
        try:
            idx_df = self.ensure_bars("1.000001", 400)
            close = idx_df["close"].to_numpy(float)
            rets = np.zeros(len(close))
            if len(close) > 1:
                rets[1:] = np.diff(np.log(np.maximum(close, 1e-9)))
            market_map = {str(x)[:10]: float(r) for x, r in zip(idx_df["date"], rets)}
        except Exception as e:
            log.warning(f"市场收益特征失败: {e}")

        industry = getattr(quote, "industry", "") if quote else ""
        dims = {
            "technical": technical.technical_dimension(d),
            "fund": fund.fund_dimension(d, quote),
            "valuation": valuation.valuation_dimension(d, quote),
            "sentiment": dict(ctx["sentiment"]),
            "macro": ctx["macro"].dimension(),
            "humanities": humanities.dimension(industry),
        }
        fused = fuse(dims)
        short_val = self.short_engine.fit_validate(d, market_map)
        short = self.short_engine.predict(d, market_map, validation=short_val)
        long = self.long_engine.forecast(d, dims, quote, last_close=float(d["close"].iloc[-1]))

        name = getattr(quote, "name", "") or symbol
        stale = False
        phase = market_phase()[0]
        if quote is not None and quote.ts and phase in ("交易中", "集合竞价", "午间休市"):
            if time.time() - quote.ts > 1800:
                stale = True
        last_bar = str(d["date"].iloc[-1])[:10]
        today = date.today()
        now_t = datetime.now().time()
        if is_trading_day(today):
            expected = today.isoformat() if now_t >= dtime(15, 0) else prev_trading_day(today).isoformat()
        else:
            expected = prev_trading_day(today).isoformat()
        if last_bar < expected:
            stale = True

        anns = self._announcements(symbol, name)
        events = []
        from ..util import calendar_events
        events = calendar_events(today, 30)

        result = {
            "symbol": symbol, "name": name, "industry": industry,
            "quote": quote, "df": d, "snapshot": snap, "dimensions": dims, "fused": fused,
            "short": short, "short_validation": short_val, "long": long,
            "news": ctx["scored_news"], "announcements": anns, "events": events,
            "context": ctx, "index_pct": ctx["index_pct"], "breadth": ctx["breadth"],
            "limit_up": ctx["limit_up"], "limit_down": ctx["limit_down"],
            "stale": stale, "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "max_position": self.settings.get("max_position_pct", 0.2),
            "market_phase": market_phase()[0],
        }
        result["research"] = build_research(result)
        result["markdown"] = build_markdown(result)
        result["html"] = build_html(result)

        if persist:
            self._persist_forecasts(result)
        self._analysis_cache[symbol] = (time.time(), result)
        return result

    def _persist_forecasts(self, r: dict) -> None:
        today_start = time.time() - (time.time() % 86400)
        targets = []
        for h, x in r["short"].items():
            targets.append((int(h), x["prob_up"], x["exp_ret"], x["low"], x["high"],
                            "short_ensemble", x["target_date"]))
        for h, x in r["long"]["horizons"].items():
            targets.append((int(h), x["prob_up"], x["exp_ret"], x["low"], x["high"],
                            "long_mc", x["target_date"]))
        for h, prob, exp, lo, hi, model, tdate in targets:
            try:
                if self.store.has_forecast_since(r["symbol"], h, tdate, today_start):
                    continue
                self.store.save_forecast(r["symbol"], r["name"], h, prob, exp, lo, hi,
                                         r["fused"]["total"], model, tdate)
            except Exception as e:
                log.warning(f"预测入库失败 {r['symbol']} h{h}: {e}")

    # ------------------------------------------------------------------ 自选池
    def refresh_watchlist(self, force: bool = True, persist: bool = True) -> dict:
        t0 = time.time()
        symbols = self.settings.watchlist
        self.refresh_quotes(symbols)
        results, errors = [], []
        for s in symbols:
            try:
                results.append(self.analyze(s, force=force, persist=persist))
            except Exception as e:
                errors.append(f"{s}: {e}")
                log.warning(f"分析失败 {s}: {e}")
        ev = self.evaluate_forecasts()
        elapsed = round(time.time() - t0, 1)
        avg = float(np.mean([r["fused"]["total"] for r in results])) if results else 0.0
        top = max(results, key=lambda x: x["fused"]["total"]) if results else None
        stats = {"n": len(results), "errors": len(errors), "elapsed": elapsed,
                 "avg_score": round(avg, 1), "top": top["name"] if top else "",
                 "evaluated": ev}
        msg = f"完成 {len(results)} 只标的校准，耗时 {elapsed}s"
        if errors:
            msg += f"，{len(errors)} 只失败"
        self.store.add_cycle("ok" if not errors else "partial", msg, stats)
        self._analysis_cache = {r["symbol"]: (time.time(), r) for r in results}
        return {"results": results, "errors": errors, "stats": stats, "message": msg}

    # ------------------------------------------------------------------ 预测评估
    def evaluate_forecasts(self) -> int:
        symbols = self.store.forecast_symbols()
        last_dates = {s: self.store.last_bar_date(s) for s in symbols}
        pending = self.store.pending_forecasts(last_dates)
        n = 0
        for f in pending:
            try:
                bars = self.store.get_bars(f["symbol"], 1200)
                if bars.empty:
                    continue
                fdate = datetime.fromtimestamp(f["ts"]).strftime("%Y-%m-%d")
                entry = bars[bars["date"] <= fdate]
                target = bars[bars["date"] >= str(f["target_date"])]
                if entry.empty or target.empty:
                    continue
                entry_close = float(entry["close"].iloc[-1])
                target_close = float(target["close"].iloc[0])
                realized = float(np.log(max(1e-9, target_close) / max(1e-9, entry_close)) * 100)
                pred_up = float(f["prob"]) > 0.5
                hit = int(pred_up == (realized > 0))
                self.store.mark_evaluated(f["id"], realized, hit)
                n += 1
            except Exception as e:
                log.warning(f"预测评估失败 {f.get('id')}: {e}")
        return n

    # ------------------------------------------------------------------ 其他
    def search(self, keyword: str) -> list[dict]:
        kw = str(keyword or "").strip()
        if not kw:
            return []
        inst = self.registry.get("datasource.eastmoney")
        if inst is not None:
            try:
                rows = inst.search(kw)
                if rows:
                    return rows
            except Exception as e:
                log.warning(f"搜索失败 {kw}: {e}")
        # 东财搜索接口失败时至少保证六位代码能直接进入终端/研究页，
        # 文本则从本地自选名称里做一次包含匹配，避免搜索框完全无响应。
        if kw.isdigit() and len(kw) == 6:
            cached = self.store.get_quote(kw) or {}
            return [{"symbol": kw, "secid": symbol_to_secid(kw),
                     "name": cached.get("name") or kw, "market": "本地"}]
        names = self.settings.watchlist_names
        return [{"symbol": s, "secid": symbol_to_secid(s), "name": n, "market": "自选"}
                for s, n in names.items() if kw.lower() in str(n).lower()][:8]

    def watchlist_quotes(self) -> dict[str, Quote]:
        return self.refresh_quotes(self.settings.watchlist)

    def set_watchlist(self, symbols: list[str]) -> None:
        names = self.settings.watchlist_names
        for s in symbols:
            if s not in names:
                q = self.refresh_quotes([s]).get(s)
                if q:
                    names[s] = q.name
        self.settings.update({"watchlist": symbols, "watchlist_names": names})

    def add_watch(self, symbol: str, name: str = "") -> None:
        wl = self.settings.watchlist
        if symbol not in wl:
            wl.append(symbol)
        names = self.settings.watchlist_names
        names[symbol] = name or names.get(symbol, symbol)
        self.settings.update({"watchlist": wl, "watchlist_names": names})

    def remove_watch(self, symbol: str) -> None:
        wl = [s for s in self.settings.watchlist if s != symbol]
        self.settings.set("watchlist", wl)

    def status(self) -> dict:
        ctx = self._ctx_cache[1] or {}
        return {
            "phase": market_phase()[0],
            "updated": ctx.get("updated", "--"),
            "breadth": ctx.get("breadth", 0.5),
            "index_pct": ctx.get("index_pct", 0.0),
            "limit_up": ctx.get("limit_up", 0),
            "limit_down": ctx.get("limit_down", 0),
            "sentiment": (ctx.get("sentiment") or {}).get("score", 0),
            "macro": (ctx.get("macro").score if ctx.get("macro") else 0),
            "db": self.store.stats(),
        }
