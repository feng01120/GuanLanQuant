"""收盘复盘与 3 日涨幅候选。

定位：每日收盘后生成市场复盘、热门板块研判，并用“历史相似形态”估算
个股在未来 3 个交易日收盘涨幅达到 3% 的条件概率。它是研究工具，不是
收益承诺，也不构成投资建议。
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import date, datetime, time as dtime

import numpy as np
import pandas as pd

from ..config import CACHE_DIR, INDICES
from ..util import is_trading_day, log, market_phase

CACHE_VERSION = 3


def _rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    diff = np.diff(close)
    up = np.where(diff > 0, diff, 0.0)
    dn = np.where(diff < 0, -diff, 0.0)
    au = np.zeros(len(close))
    ad = np.zeros(len(close))
    for i in range(1, len(close)):
        au[i] = (au[i - 1] * (n - 1) + up[i - 1]) / n
        ad[i] = (ad[i - 1] * (n - 1) + dn[i - 1]) / n
    rs = au / np.maximum(ad, 1e-9)
    return 100.0 - 100.0 / (1.0 + rs)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class RecommendService:
    """收盘复盘、热门板块与 3 日事件概率筛选。"""

    def __init__(self, market):
        self.market = market
        self._lock = threading.RLock()
        self._cache = None
        self._cache_key = None
        self._cache_ts = 0.0

    # ------------------------------------------------------------------
    def daily(self, force: bool = False) -> dict:
        now = time.time()
        final = self._is_final()
        key = (date.today().isoformat(), "final" if final else "live")
        cache_path = CACHE_DIR / f"recommend-{key[0]}-{key[1]}.json"
        with self._lock:
            if not force and cache_path.exists():
                try:
                    data = json.loads(cache_path.read_text(encoding="utf-8"))
                    if int(data.get("schema", 1)) >= CACHE_VERSION:
                        effective_ttl = 1800 if data.get("data_quality") == "ok" else 300
                        if now - cache_path.stat().st_mtime < effective_ttl:
                            data["from_cache"] = True
                            self._cache = data
                            self._cache_key = key
                            self._cache_ts = now
                            return data
                except Exception as e:  # noqa: BLE001
                    log.warning(f"荐股缓存读取失败: {e}")
            if (not force and self._cache is not None and self._cache_key == key
                    and now - self._cache_ts < (1800 if self._cache.get("data_quality") == "ok" else 300)):
                return self._cache
            out = self._build(force=force)
            # 完整结果缓存 30 分钟；指数/板块/候选都在、仅宽度等字段缺失时，
            # 允许短缓存 5 分钟，避免接口异常时每次进页都重跑几十秒。
            cacheable = bool(out.get("market", {}).get("indices")) and bool(out.get("sectors")) \
                and bool(out.get("picks"))
            if out.get("data_quality") == "ok" or cacheable:
                try:
                    tmp = cache_path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
                    os.replace(tmp, cache_path)
                except Exception as e:  # noqa: BLE001
                    log.warning(f"荐股缓存写入失败: {e}")
            else:
                log.warning("荐股数据不完整，本次不写入缓存")
            self._cache = out
            self._cache_key = key
            self._cache_ts = now
            return out

    @staticmethod
    def _is_final() -> bool:
        today = date.today()
        if not is_trading_day(today):
            return True
        return datetime.now().time() >= dtime(15, 0)

    # ------------------------------------------------------------------
    def _build(self, force: bool = False) -> dict:
        t0 = time.time()
        ctx = self.market.market_context(force=force)
        phase = market_phase()[0]
        final = self._is_final()
        em = self.market.registry.get("datasource.eastmoney")
        if em is None:
            log.warning("东方财富数据源未加载，使用新浪降级生成复盘")

        last_date = self.market.store.last_bar_date("1.000001") or date.today().isoformat()
        market = self._market_block(ctx)
        sectors = self._sector_block(em, force=force)
        picks, stats = self._pick_block(em, sectors, market, force=force)
        quality = ("ok" if market.get("data_quality") == "ok" and sectors
                   and not stats.get("errors") and market.get("amount_avg20", 0) > 0 else "partial")
        data_notes = []
        if not sectors:
            data_notes.append("行业板块数据暂缺，热门方向无法判断")
        elif stats.get("board_source") == "sina":
            data_notes.append("行业板块使用新浪口径，板块涨跌家数暂不可得")
        if market.get("amount_avg20", 0) <= 0:
            data_notes.append("成交额历史数据不足，20 日均量暂缺")
        if stats.get("errors"):
            data_notes.append(f"{stats['errors']} 只候选分析失败，已跳过")

        top_names = [s["name"] for s in sectors[:3]]
        if top_names and sectors[0].get("pct", 0) >= 0 and not market.get("weak"):
            market["style_text"] = f"今日强势集中在{'、'.join(top_names)}。"
        elif top_names and market.get("weak"):
            market["style_text"] = f"今日普跌，相对抗跌的是{'、'.join(top_names)}。"
        elif top_names:
            market["style_text"] = f"今日没有上涨板块，相对抗跌的是{'、'.join(top_names)}。"
        else:
            market["style_text"] = "今日板块信号较弱，暂无明确主线。"

        # 推荐与热门板块不必重合：解释两条线的关系，避免误导。
        linked = sum(1 for x in picks if x.get("sector_hot"))
        if picks and linked < len(picks):
            market["style_text"] += (
                " 3 日概率筛选偏向近期波动放大、且出现超跌修复形态的个股，"
                "与今日最强板块并不完全重合；本页按“板块观察 + 个股概率”两条线呈现。"
            )

        recap = [
            {"label": "指数", "text": market["index_text"]},
            {"label": "赚钱效应", "text": market["breadth_text"]},
            {"label": "量能", "text": market["amount_text"]},
            {"label": "风格", "text": market["style_text"]},
            {"label": "明日观察", "text": market["outlook"]},
        ]
        out = {
            "schema": CACHE_VERSION,
            "date": last_date,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated": datetime.now().strftime("%H:%M:%S"),
            "phase": phase,
            "is_final": final,
            "title_phase": "收盘复盘" if final else "盘中预览",
            "market": market,
            "sectors": sectors,
            "picks": picks,
            "stats": stats,
            "recap": recap,
            "data_notes": data_notes,
            "method": (
                "候选池：沪深主板、创业板、科创板中成交额不低于 3 亿元、换手率 0.8%–25%、"
                "市值不低于 30 亿元，剔除 ST/退市/新股；并从当日强势板块成分股中补充。\n"
                "概率口径：对每只股票取最近 320 根日 K，按 5 日/20 日动量、RSI(14)、量比"
                "寻找 45 个历史相似形态，统计这些形态出现后第 3 个交易日收盘涨幅 ≥3% 的比例；"
                "再用板块热度和市场宽度做小幅修正。\n"
                "等级：估算概率 ≥45% 标为“重点关注”，35%–45% 为“观察”，低于 35% 只作弱信号展示。\n"
                "重要：这是历史条件概率，不是未来收益承诺；样本相似不代表必然重复，"
                "高波动个股可能同时出现较大回撤。"
            ),
            "threshold": 0.35,
            "data_quality": quality,
            "disclaimer": "仅供研究，不构成投资建议；不接入实盘，不代客下单。",
            "elapsed": round(time.time() - t0, 1),
        }
        return out

    # ------------------------------------------------------------------
    def _market_block(self, ctx: dict) -> dict:
        quotes = ctx.get("quotes") or {}
        idx = []
        for code, name, short in INDICES:
            q = quotes.get(code)
            if q is None:
                continue
            idx.append({"code": code, "short": short, "name": name,
                        "price": float(q.price), "pct": float(q.pct)})
        # 报价接口失败时，用日 K 的最后两根收盘价兜底，至少不让指数整块空白。
        if not idx:
            for code, name, short in INDICES:
                try:
                    bars = self.market.ensure_bars(code, 120, force=False)
                    if len(bars) >= 2:
                        last = float(bars["close"].iloc[-1])
                        prev = float(bars["close"].iloc[-2])
                        idx.append({"code": code, "short": short, "name": name, "price": last,
                                    "pct": (last / prev - 1) * 100 if prev else 0.0})
                except Exception:
                    continue
        up, down, flat = int(ctx.get("up") or 0), int(ctx.get("down") or 0), int(ctx.get("flat") or 0)
        breadth_missing = up + down == 0
        amount_yuan = float(ctx.get("amount") or 0.0)
        if breadth_missing:
            # 东财 ulist 空响应时，指数报价拿不到涨跌家数；用新浪全市场分页补，
            # 避免整页长期显示“涨跌家数暂缺”。宽度查询在 MarketService 里
            # 已有 5 分钟缓存，这里不重复拉几十页。
            mb = self.market._breadth_fallback()
            if mb:
                up, down, flat = int(mb.get("up") or 0), int(mb.get("down") or 0), int(mb.get("flat") or 0)
                if amount_yuan <= 0:
                    amount_yuan = float(mb.get("amount") or 0.0)
                breadth_missing = up + down == 0
        breadth = float(ctx.get("breadth") or 0.0) if not breadth_missing else 0.5
        amount = amount_yuan / 1e8
        hist = [float(x) for x in (ctx.get("amount_history") or []) if x and float(x) > 0]
        avg20 = float(np.mean(hist[-20:])) / 1e8 if len(hist) >= 5 else 0.0
        amount_ratio = amount / avg20 if avg20 else 0.0
        limit_up, limit_down = int(ctx.get("limit_up") or 0), int(ctx.get("limit_down") or 0)
        if breadth_missing:
            effect = "涨跌家数暂缺"
        elif breadth >= 0.65:
            effect = "赚钱效应偏强"
        elif breadth <= 0.35:
            effect = "亏钱效应明显"
        else:
            effect = "多空分化"
        if amount_ratio >= 1.08:
            vol_text = "放量"
        elif 0 < amount_ratio <= 0.85:
            vol_text = "缩量"
        elif amount_ratio:
            vol_text = "量能平稳"
        else:
            vol_text = "成交额暂缺"
        style = f"{vol_text}、{effect}" if amount_ratio else effect
        weak = (not breadth_missing and breadth < 0.35) or limit_down > max(8, int(limit_up * 1.5))
        if weak:
            risk_level, risk_text = "高", "今日属于弱势/普跌格局，3 日反弹概率只能作为观察信号，不宜逆势重仓。"
        elif breadth_missing:
            risk_level, risk_text = "中", "市场宽度接口暂缺，只能参考指数与涨跌停数据，结论完整度下降。"
        elif breadth < 0.5:
            risk_level, risk_text = "中", "市场分化偏弱，候选需要等待指数止跌后再确认。"
        else:
            risk_level, risk_text = "低", "市场环境尚可，仍应控制单票仓位并设置止损。"
        index_text = "；".join(f"{x['name']} {x['pct']:+.2f}%" for x in idx[:3]) or "指数数据暂缺"
        breadth_text = (f"上涨 {up} 家 / 下跌 {down} 家 / 平盘 {flat} 家，"
                        f"涨停 {limit_up} 家、跌停 {limit_down} 家"
                        if not breadth_missing else
                        f"涨跌家数暂缺；涨停 {limit_up} 家、跌停 {limit_down} 家")
        if avg20:
            amount_text = f"两市成交额 {amount:.0f} 亿元，约为近 20 日均量的 {amount_ratio * 100:.0f}%"
        elif amount:
            amount_text = f"两市成交额 {amount:.0f} 亿元"
        else:
            amount_text = "两市成交额数据暂缺"
        if breadth_missing:
            outlook = "市场宽度接口暂缺，先以指数和涨跌停家数判断风险，数据恢复后重新生成。"
        elif weak:
            outlook = "普跌日先看指数能否止跌、跌停家数能否收敛；在赚钱效应恢复前，候选只做跟踪，不急于建仓。"
        elif breadth >= 0.6 and amount_ratio >= 1.0:
            outlook = "量价配合尚可，明日重点看强势板块能否继续放量、以及涨停家数是否扩散。"
        elif breadth < 0.4:
            outlook = "赚钱效应偏弱，明日先看指数能否止跌，弱市中不宜把反弹概率当成趋势。"
        else:
            outlook = "分化格局，明日关注资金是否从防御板块回流成长方向，避免同时追高和抄底。"
        quality = "ok"
        if breadth_missing or not idx or amount <= 0 or avg20 <= 0:
            quality = "partial"
        return {"indices": idx, "up": up, "down": down, "flat": flat,
                "breadth": breadth, "breadth_missing": breadth_missing,
                "amount": amount, "amount_avg20": avg20,
                "amount_ratio": amount_ratio, "limit_up": limit_up, "limit_down": limit_down,
                "style": style, "index_text": index_text, "breadth_text": breadth_text,
                "amount_text": amount_text, "outlook": outlook,
                "weak": weak, "risk_level": risk_level, "risk_text": risk_text,
                "index_pct": float(idx[0]["pct"]) if idx else 0.0,
                "data_quality": quality,
                "summary": f"{index_text}。{breadth_text}；{amount_text}；市场{style}。"}

    # ------------------------------------------------------------------
    def _sector_block(self, em, force: bool = False) -> list[dict]:
        sina = self.market.registry.get("datasource.sina")
        source = "eastmoney"
        try:
            if em is None:
                raise RuntimeError("东方财富数据源未加载")
            boards = em.boards(90)
        except Exception as e:
            log.warning(f"热门板块获取失败，改用新浪行业: {e}")
            if sina is None:
                return []
            try:
                boards = sina.boards(90)
                source = "sina"
            except Exception as e2:
                log.warning(f"新浪行业也失败: {e2}")
                return []
        if not boards and sina is not None:
            try:
                boards = sina.boards(90)
                source = "sina"
            except Exception:
                return []
        rows = []
        seen = set()
        candidates = []
        for b in boards:
            if source == "eastmoney":
                if b.up + b.down < 2 or b.amount < 5e7:
                    continue
                breadth = b.up / max(1, b.up + b.down)
                narrow = (b.up + b.down) < 4
            else:
                # 新浪行业只给板块涨跌幅/成交额与家数，不给涨跌家数。
                if b.amount < 5e7:
                    continue
                breadth = 0.5
                narrow = False
            # 普跌日没有上涨板块时，保留“相对抗跌”板块，避免整页无研判。
            if b.pct < -5.0 or b.pct > 15.0:
                continue
            base_name = b.name.replace("Ⅱ", "").replace("Ⅲ", "").replace("II", "").replace("III", "")
            if base_name in seen:
                continue
            seen.add(base_name)
            heat = b.pct + breadth * 2
            if b.pct >= 4:
                tone = "强势领涨"
            elif b.pct >= 2:
                tone = "板块走强"
            elif b.pct >= 1:
                tone = "温和活跃"
            elif b.pct >= 0.2:
                tone = "小幅走强"
            elif b.pct > -1:
                tone = "相对抗跌"
            else:
                tone = "跌幅较小"
            if source == "eastmoney" and b.pct >= 0.2 and narrow:
                tone += "；成分股少，样本偏窄"
            candidates.append({
                "code": b.code, "name": b.name, "pct": float(b.pct),
                "amount": b.amount, "up": b.up, "down": b.down,
                "breadth": breadth, "leader": b.leader or "--", "heat": heat,
                "narrow": narrow, "comment": tone, "source": source,
                "updown_text": f"{b.up}/{b.down}" if source == "eastmoney" else "--",
            })
        positive = [r for r in candidates if r["pct"] >= 0.2]
        if positive:
            rows = positive
        else:
            rows = sorted(candidates, key=lambda x: x["pct"], reverse=True)
        rows.sort(key=lambda x: x["heat"], reverse=True)
        for i, r in enumerate(rows[:8], 1):
            r["rank"] = i
        return rows[:8]

    # ------------------------------------------------------------------
    def _pick_block(self, em, sectors: list[dict], market: dict, force: bool = False):
        pool: dict[str, dict] = {}
        sina = self.market.registry.get("datasource.sina")
        # 热门板块成分股优先纳入候选池
        for b in sectors[:6]:
            try:
                if b.get("source") == "sina":
                    rows = sina.board_stocks(b["code"], 30) if sina else []
                elif em is not None:
                    rows = em.board_stocks(b["code"], 30)
                else:
                    rows = []
            except Exception as e:
                log.warning(f"板块成分股失败 {b['name']}: {e}")
                rows = []
            for r in rows:
                r["_sector"] = b["name"]
                r["_sector_pct"] = b["pct"]
                if not r.get("industry"):
                    r["industry"] = b["name"]
                pool.setdefault(r["symbol"], r)
        try:
            use_sina = (em is None or market.get("data_quality") != "ok"
                        or (sectors and sectors[0].get("source") == "sina"))
            if use_sina and sina is not None:
                # 东财报价/板块已降级时，全市场榜也直接走新浪，避免再等一次
                # push2 超时；新浪列表的成交额排序足以支撑候选池。
                for r in sina.stock_list(100):
                    pool.setdefault(r["symbol"], r)
            else:
                for r in em.stock_list(180):
                    pool.setdefault(r["symbol"], r)
        except Exception as e:
            log.warning(f"全市场列表失败，改用新浪成交额榜: {e}")
            if sina is not None:
                try:
                    for r in sina.stock_list(100):
                        pool.setdefault(r["symbol"], r)
                except Exception as e2:
                    log.warning(f"新浪全市场列表也失败: {e2}")
        used_watchlist = False
        if len(pool) < 8:
            # 东财列表接口偶发断连时，用自选池兜底，至少保留一个可复核的候选集。
            used_watchlist = True
            names = self.market.settings.get("watchlist_names", {})
            for sym in self.market.settings.watchlist:
                if sym in pool:
                    continue
                try:
                    bars = self.market.ensure_bars(sym, 6, force=False)
                    if len(bars) < 2:
                        continue
                    last, prev = float(bars["close"].iloc[-1]), float(bars["close"].iloc[-2])
                    pool[sym] = {"symbol": sym, "name": names.get(sym, sym), "price": last,
                                 "pct": (last / prev - 1) * 100 if prev else 0.0,
                                 "amount": 1e9, "turnover": 5.0, "pe": 0.0,
                                 "market_cap": 0.0, "industry": ""}
                except Exception:
                    continue

        def basic(r: dict) -> bool:
            sym = str(r.get("symbol") or "")
            name = str(r.get("name") or "")
            if len(sym) != 6 or not sym.isdigit():
                return False
            if "ST" in name.upper() or "退" in name:
                return False
            price = float(r.get("price") or 0)
            amount = float(r.get("amount") or 0)
            turnover = float(r.get("turnover") or 0)
            pct = float(r.get("pct") or 0)
            cap = float(r.get("market_cap") or 0)
            if price < 3 or price > 500 or amount < 3e8:
                return False
            if turnover < 0.8 or turnover > 25:
                return False
            if pct < -6 or pct > 12:
                return False
            if cap and cap < 30e8:
                return False
            return True

        pre = {k: v for k, v in pool.items() if basic(v)}
        # stock_list / board_stocks 已经带现价、涨跌幅、换手、成交额与行业；
        # 不再对上百只股票做一次批量报价，避免首屏被单一接口拖慢。
        for r in pre.values():
            if not r.get("industry"):
                r["industry"] = ""

        def sector_for(industry: str):
            if not industry:
                return None, 99
            for i, b in enumerate(sectors):
                n = b["name"].replace("Ⅱ", "").replace("Ⅲ", "").replace("Ⅱ", "")
                ind = industry.replace("Ⅱ", "").replace("Ⅲ", "")
                if (ind == n or ind in n or n in ind):
                    return b, i
            return None, 99

        def pre_score(r: dict) -> float:
            pct = float(r.get("pct") or 0)
            turn = float(r.get("turnover") or 0)
            b, rank = sector_for(str(r.get("industry") or r.get("_sector") or ""))
            s = 1.0 if 0 < pct < 6 else 0.0
            s += 0.5 if 2 < turn < 15 else 0.0
            if b is not None:
                s += max(0.0, 2.0 - rank * 0.25)
            if r.get("_sector"):
                s += 0.3
            return s

        ranked = sorted(pre.values(), key=pre_score, reverse=True)[:20]
        picks = []
        errors = []
        for r in ranked:
            try:
                # 刷新行情时可以强制重拉列表，但候选 K 线不必强制重拉：
                # 收盘后本地已有当日 K 线即可复用，避免 20 只股票逐个等待
                # 东财 push2his 超时再回退腾讯，把首屏拖到两分钟。
                bars = self.market.ensure_bars(r["symbol"], 320, force=False)
                out = self._analyze(r, bars, sectors, market)
                picks.append(out)
            except Exception as e:
                errors.append(f"{r['symbol']}: {e}")
                log.warning(f"荐股分析失败 {r.get('symbol')}: {e}")

        picks.sort(key=lambda x: x["prob3"], reverse=True)
        qualified = [x for x in picks if x["prob3"] >= 0.35]
        target = min(6, len(picks))
        if qualified:
            shown = qualified[:target]
            if len(shown) < target:
                shown += [x for x in picks if x not in shown][:target - len(shown)]
        else:
            shown = picks[:4]
        note = ""
        if market.get("weak"):
            note = "今日为弱势/普跌格局，候选只作超跌反弹观察，不宜逆势重仓。"
        if not qualified:
            note += (" " if note else "") + "今日没有股票达到 35% 的估算门槛，下表仅展示概率最高的弱信号，不建议强行交易。"
        elif len(qualified) < 4:
            note += (" " if note else "") + f"今日达到 35% 估算门槛的股票只有 {len(qualified)} 只，其余为补足的观察标的。"
        for i, x in enumerate(shown, 1):
            x["rank"] = i
        stats = {"pool": len(pool), "basic": len(pre), "analyzed": len(picks),
                 "qualified": len(qualified), "shown": len(shown), "errors": len(errors),
                 "error_samples": errors[:4],
                 "threshold": 0.35, "note": note, "fallback": "自选池" if used_watchlist else "",
                 "board_source": (sectors[0].get("source") if sectors else "")}
        return shown, stats

    # ------------------------------------------------------------------
    def _analyze(self, r: dict, bars: pd.DataFrame, sectors: list[dict], market: dict) -> dict:
        close = bars["close"].to_numpy(float)
        vol = bars["volume"].to_numpy(float)
        if len(close) < 100:
            raise RuntimeError("K线不足 100 根")
        ret = np.zeros(len(close))
        ret[1:] = np.diff(np.log(np.maximum(close, 1e-9)))
        rs = _rsi(close)
        vol20 = pd.Series(ret).rolling(20).std().to_numpy()
        i = len(close) - 1
        if not np.isfinite(vol20[i]) or vol20[i] < 1e-6:
            raise RuntimeError("波动率异常")

        def vratio(j: int) -> float:
            return float(np.mean(vol[j - 4:j + 1]) / max(1e-9, np.mean(vol[j - 24:j - 4])))

        m5 = close[i] / close[i - 5] - 1
        m20 = close[i] / close[i - 20] - 1
        m60 = close[i] / close[i - 60] - 1
        ma20 = float(np.mean(close[-20:]))
        ma20_gap = close[i] / ma20 - 1
        vr = vratio(i)
        state = np.array([m5 / vol20[i], m20 / vol20[i], rs[i] / 60, vr])
        rows = []
        for j in range(70, len(close) - 3):
            if not np.isfinite(vol20[j]) or vol20[j] < 1e-6:
                continue
            s = np.array([(close[j] / close[j - 5] - 1) / vol20[j],
                          (close[j] / close[j - 20] - 1) / vol20[j],
                          rs[j] / 60, vratio(j)])
            dist = float(np.sum(((s - state) / np.array([1.0, 1.0, 0.25, 0.8])) ** 2))
            fwd = close[j + 3] / close[j] - 1
            rows.append((dist, fwd))
        rows.sort(key=lambda x: x[0])
        sample = np.array([x[1] for x in rows[:45]], dtype=float)
        if len(sample) < 20:
            raise RuntimeError("历史样本不足")
        hits = int((sample >= 0.03).sum())
        n = len(sample)
        raw_p = (hits + 1) / (n + 2)
        med = float(np.median(sample))
        q25, q75 = float(np.quantile(sample, 0.25)), float(np.quantile(sample, 0.75))

        industry = str(r.get("industry") or r.get("_sector") or "")
        sector_hot = None
        sector_rank = 99
        for k, b in enumerate(sectors):
            nname = b["name"].replace("Ⅱ", "").replace("Ⅲ", "")
            ind = industry.replace("Ⅱ", "").replace("Ⅲ", "")
            if industry and (ind == nname or ind in nname or nname in ind):
                sector_hot, sector_rank = b, k
                break

        p = raw_p
        if sector_hot is not None and sector_rank < 4:
            p += 0.015 if sector_hot["pct"] >= 1.5 else 0.0
        # 市场环境权重：普跌日不能只看个股历史形态。
        p += (float(market.get("breadth") or 0.5) - 0.5) * 0.12
        if market.get("weak"):
            p -= 0.04
        if float(market.get("index_pct") or 0) <= -2.0:
            p -= 0.02
        today_pct = float(r.get("pct") or 0)
        if today_pct >= 7:
            p -= 0.02
        if m20 >= 0.30:
            p -= 0.02
        if rs[i] >= 75:
            p -= 0.03
        p = _clamp(p, 0.05, 0.85)

        reasons = [
            f"历史相似形态 {n} 个，其中 {hits} 个在 3 日内收盘涨幅 ≥3%",
            f"近 5 日 {m5 * 100:+.1f}%，近 20 日 {m20 * 100:+.1f}%，"
            f"{'处于超跌修复区' if m20 < -0.10 else '趋势偏强' if m20 > 0.10 else '区间震荡'}",
            f"现价{'站上' if ma20_gap >= 0 else '低于'} 20 日线 {abs(ma20_gap) * 100:.1f}%",
        ]
        if sector_hot is not None:
            reasons.append(f"所属“{sector_hot['name']}”今日 {sector_hot['pct']:+.2f}%，"
                           f"居热门板块第 {sector_rank + 1} 位")
        risks = []
        if today_pct >= 7:
            risks.append("今日涨幅已大，追高回撤风险")
        if float(r.get("turnover") or 0) > 15:
            risks.append("换手偏高，多空分歧较大")
        if vol20[i] >= 0.06:
            risks.append("20 日波动率偏高，仓位宜轻")
        if q25 <= -0.06:
            risks.append("历史类比下沿较深，可能先回撤")
        if m20 <= -0.20:
            risks.append("20 日跌幅较深，属于超跌反弹思路")
        if m20 >= 0.30:
            risks.append("中期涨幅已大，防高位震荡")
        if not risks:
            risks.append("暂无突出风险，但仍需按纪律设置止损")
        if market.get("weak"):
            grade = "弱市观察" if p >= 0.35 else "弱信号"
        else:
            grade = "重点关注" if p >= 0.45 else "观察" if p >= 0.35 else "弱信号"
        return {
            "symbol": r["symbol"], "name": r.get("name", ""), "industry": industry,
            "price": float(r.get("price") or 0), "pct": today_pct,
            "turnover": float(r.get("turnover") or 0), "amount": float(r.get("amount") or 0),
            "pe": float(r.get("pe") or 0),
            "market_cap": float(r.get("market_cap") or 0),
            "prob3": float(p), "raw_prob": float(raw_p), "hits": hits, "samples": n,
            "med3": med, "q25": q25, "q75": q75,
            "grade": grade, "reasons": reasons, "risks": risks,
            "sector_hot": sector_hot["name"] if sector_hot else "",
            "tech": {"m5": float(m5), "m20": float(m20), "m60": float(m60),
                     "rsi": float(rs[i]), "vol20": float(vol20[i]), "vr": float(vr),
                     "ma20_gap": float(ma20_gap)},
        }
