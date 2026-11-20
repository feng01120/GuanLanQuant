"""研报渲染：Markdown 与 HTML（可打印为 PDF）。"""
from __future__ import annotations

import re

from ..util import esc, money, pct, price


def _fmt(v, digits=2):
    try:
        return f"{float(v):.{digits}f}"
    except Exception:
        return "--"


def build_markdown(r: dict) -> str:
    q = r.get("quote")
    snap = r.get("snapshot", {})
    fused = r.get("fused", {})
    short = r.get("short", {})
    long = r.get("long", {})
    res = r.get("research", {})
    dims = r.get("dimensions", {})
    name, symbol = r.get("name", ""), r.get("symbol", "")
    close = float(getattr(q, "price", 0) or snap.get("close", 0)) if q else float(snap.get("close", 0))
    p = float(getattr(q, "pct", 0) or 0) if q else 0.0

    lines = [
        f"# 观澜研判｜{name}（{symbol}）",
        "",
        f"> 生成时间：{res.get('generated_at', '')}　收盘/最新：{price(close)}　当日：{pct(p)}　"
        f"行业：{r.get('industry', '') or '行业数据缺失'}",
        "",
        "## 一、结论摘要",
        "",
        res.get("summary", ""),
        "",
        f"- 六维综合：**{fused.get('total', 0):+.1f}**（{fused.get('verdict', '中性')}），置信度 {fused.get('confidence', 0):.0f}/100",
        f"- T+1：上涨概率 {short.get(1, {}).get('prob_up', 0.5) * 100:.1f}%，期望 {short.get(1, {}).get('exp_ret', 0):+.2f}%，区间 {short.get(1, {}).get('low', 0):+.2f}% ~ {short.get(1, {}).get('high', 0):+.2f}%",
        f"- T+2：上涨概率 {short.get(2, {}).get('prob_up', 0.5) * 100:.1f}%，期望 {short.get(2, {}).get('exp_ret', 0):+.2f}%",
        f"- 20日：上涨概率 {long.get('horizons', {}).get(20, {}).get('prob_up', 0.5) * 100:.1f}%，中性情形 {long.get('horizons', {}).get(20, {}).get('median_ret', 0):+.2f}%，90% 区间 {long.get('horizons', {}).get(20, {}).get('low', 0):+.2f}% ~ {long.get('horizons', {}).get(20, {}).get('high', 0):+.2f}%",
        f"- 交易员建议：**{res.get('decision', {}).get('action', '观望')}**，参考仓位 {res.get('decision', {}).get('position_pct', 0):.1f}%",
        "",
        "## 二、六维评分",
        "",
        "| 维度 | 权重 | 得分 | 贡献 | 核心依据 |",
        "|---|---:|---:|---:|---|",
    ]
    for d in fused.get("radar", []):
        dim = dims.get(d["key"], {})
        reason = "；".join(dim.get("reasons", [])[:2])
        lines.append(f"| {d['label']} | {d['weight'] * 100:.0f}% | {d['score']:+.1f} | {d['contribution']:+.1f} | {reason} |")
    lines += ["", "## 三、分析师观点", ""]
    for v in res.get("views", []):
        lines.append(f"### {v['role']}｜{v['stance']}（{v['score']:+.1f}）")
        for b in v.get("bullets", []):
            lines.append(f"- {b}")
        lines.append("")
    lines += ["## 四、多空辩论", "", "### 多头研究员", ""]
    for b in res.get("bull", []):
        lines.append(f"- {b}")
    lines += ["", "### 空头研究员", ""]
    for b in res.get("bear", []):
        lines.append(f"- {b}")
    dec = res.get("decision", {})
    lines += ["", "## 五、交易计划（研究用途，非投资建议）", "",
              f"- 方向：{dec.get('action', '观望')}；多空偏置 {dec.get('bias', 0):+.2f}",
              f"- 参考建仓区间：{price(dec.get('entry_low', 0))} ~ {price(dec.get('entry_high', 0))}",
              f"- 止损：{price(dec.get('stop', 0))}；目标：{price(dec.get('target', 0))}；盈亏比 {dec.get('risk_reward', 0):.1f}",
              f"- 建议仓位上限：{dec.get('position_pct', 0):.1f}%（按 100% 资金计）",
              f"- 周期：{dec.get('horizon', '')}",
              "", "## 六、风险清单", "",
              f"**风险等级：{res.get('risk_level', '中')}**", ""]
    for risk in res.get("risks", []):
        lines.append(f"- {risk}")
    lines += ["", "## 七、方法与声明", "",
              "1. 数据：行情来自公开行情接口（东方财富/腾讯/新浪，按优先级回退）；公告来自巨潮资讯；"
              "宏观来自国家统计局（经数据中心转发）；汇率来自中国外汇交易中心。",
              "2. 模型：短周期为 Ridge + Logistic + 历史形态类比的滚动样本外集成；"
              "长周期为六维评分驱动的蒙特卡洛分布（bootstrap 残差）。",
              "3. 每小时校准：重新拉取行情、重算因子、重估模型与集成权重；非交易时段使用最近收盘数据。",
              "4. 所有概率均为统计倾向，不构成收益承诺；A 股存在涨跌停、停牌、复权与流动性约束，回测无法完全复现。",
              "5. 本报告由观澜 QuantDesk 自动生成，仅用于研究与学习，不构成任何投资建议。",
              "6. 软件设计与实现责任归属：@烬羽鱼。"]
    return "\n".join(lines)


def build_html(r: dict) -> str:
    q = r.get("quote")
    snap = r.get("snapshot", {})
    fused = r.get("fused", {})
    short, long = r.get("short", {}), r.get("long", {})
    res = r.get("research", {})
    dims = r.get("dimensions", {})
    name, symbol = esc(r.get("name", "")), esc(r.get("symbol", ""))
    close = float(getattr(q, "price", 0) or snap.get("close", 0)) if q else float(snap.get("close", 0))
    p = float(getattr(q, "pct", 0) or 0) if q else 0.0
    up_color = "#C0392B" if p >= 0 else "#1E8449"
    verdict = esc(fused.get("verdict", "中性"))
    signal_color = {"BULL": "#C0392B", "LEAN_BULL": "#D35400", "NEUTRAL": "#7F8C8D",
                    "LEAN_BEAR": "#2471A3", "BEAR": "#1E8449"}.get(fused.get("signal", ""), "#7F8C8D")

    def row(d):
        dim = dims.get(d["key"], {})
        reason = esc("；".join(dim.get("reasons", [])[:2]))
        return (f"<tr><td>{esc(d['label'])}</td><td>{d['weight'] * 100:.0f}%</td>"
                f"<td class='num'>{d['score']:+.1f}</td><td class='num'>{d['contribution']:+.1f}</td>"
                f"<td class='muted'>{reason}</td></tr>")

    views_html = ""
    for v in res.get("views", []):
        bullets = "".join(f"<li>{esc(b)}</li>" for b in v.get("bullets", []))
        views_html += (f"<div class='card'><div class='role'>{esc(v['role'])}"
                       f"<span class='tag'>{esc(v['stance'])} {v['score']:+.1f}</span></div>"
                       f"<ul>{bullets}</ul></div>")

    bull = "".join(f"<li>{esc(b)}</li>" for b in res.get("bull", []))
    bear = "".join(f"<li>{esc(b)}</li>" for b in res.get("bear", []))
    risks = "".join(f"<li>{esc(x)}</li>" for x in res.get("risks", []))
    dec = res.get("decision", {})

    def hs(h):
        x = long.get("horizons", {}).get(h, {})
        return (f"<td class='kpi'><div class='k'>20日</div><div class='v'>{x.get('prob_up', 0) * 100:.0f}%</div>"
                f"<div class='s'>上涨概率 · 中性 {x.get('median_ret', 0):+.2f}%</div></td>")

    s1 = short.get(1, {})
    s2 = short.get(2, {})
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{font-family:'Microsoft YaHei UI','Segoe UI',sans-serif;background:#FBFBF8;color:#1C2833;margin:0;padding:34px 46px;line-height:1.62;}}
p, td, th, li, div, span{{color:#1C2833;}}
h1, h2, h3{{color:#1C2833;}}
h1{{font-size:26px;margin:0 0 4px;letter-spacing:.5px;}}
.meta{{color:#7F8C8D;font-size:12px;border-bottom:1px solid #E5E8E8;padding-bottom:14px;margin-bottom:18px;}}
.price{{font-size:30px;font-weight:700;color:{up_color};}} .delta{{color:{up_color};font-weight:600;}}
.badge{{color:{signal_color};font-weight:700;font-size:13px;}}
h2{{font-size:16px;margin:26px 0 10px;border-left:3px solid #B7950B;padding-left:9px;}}
p.lead{{background:#F4F6F7;border-left:3px solid #B7950B;padding:12px 15px;font-size:13.5px;}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;}}
th{{background:#F2F3F4;text-align:left;padding:7px 8px;border-bottom:1px solid #D5DBDB;font-weight:600;}}
td{{padding:7px 8px;border-bottom:1px solid #ECF0F1;vertical-align:top;}}
.num{{text-align:right;font-variant-numeric:tabular-nums;}} .muted{{color:#5D6D7E;font-size:11.5px;}}
.card{{border:1px solid #ECF0F1;border-radius:6px;padding:10px 14px;margin:8px 0;background:#fff;}}
.role{{font-weight:700;font-size:13px;margin-bottom:4px;}} .tag{{margin-left:10px;font-weight:400;color:#566573;font-size:11.5px;}}
.card ul{{margin:4px 0 0 16px;padding:0;}} li{{font-size:12px;color:#2C3E50;margin:2px 0;}}
.two{{width:100%;border-collapse:collapse;}} .two td{{width:50%;vertical-align:top;border:1px solid #ECF0F1;border-radius:6px;padding:10px 14px;background:#fff;}}
.two h3{{font-size:13px;margin:0 0 6px;color:#C0392B;}} .two .bear h3{{color:#1E8449;}}
.kpis{{width:100%;border-collapse:collapse;margin:12px 0;}} .kpi{{width:33%;border:1px solid #ECF0F1;border-radius:6px;padding:10px;background:#fff;}}
.k{{font-size:11px;color:#7F8C8D;}} .v{{font-size:22px;font-weight:700;color:#1C2833;}} .s{{font-size:11px;color:#5D6D7E;}}
.plan{{background:#FEF9E7;border:1px solid #F7DC6F;border-radius:6px;padding:12px 16px;font-size:12.5px;}}
.footer{{margin-top:26px;border-top:1px solid #E5E8E8;padding-top:10px;color:#7F8C8D;font-size:10.5px;}}
</style></head><body text="#1C2833" link="#1C2833" vlink="#1C2833">
<h1>观澜研判 · {name} <span style="font-size:13px;color:#7F8C8D">{symbol}</span></h1>
<div class="meta">生成时间 {esc(res.get('generated_at', ''))}　|　行业 {esc(r.get('industry', '') or '行业数据缺失')}　|　数据截至 {esc(snap.get('date', ''))}<br>
<div class="quote">现价 <span class="price">{price(close)}</span>　<span class="delta">{pct(p)}</span>　<b class="badge">「{verdict}」</b></div>
综合 {fused.get('total', 0):+.1f} / 100 · 置信度 {fused.get('confidence', 0):.0f}</div>

<h2>结论摘要</h2>
<p class="lead">{esc(res.get('summary', ''))}</p>

<table class="kpis" width="100%"><tr>
<td class="kpi"><div class="k">T+1</div><div class="v">{s1.get('prob_up', 0.5) * 100:.0f}%</div>
<div class="s">上涨概率 · 期望 {s1.get('exp_ret', 0):+.2f}%</div></td>
<td class="kpi"><div class="k">T+2</div><div class="v">{s2.get('prob_up', 0.5) * 100:.0f}%</div>
<div class="s">上涨概率 · 期望 {s2.get('exp_ret', 0):+.2f}%</div></td>
{hs(20)}
</tr></table>

<h2>六维评分</h2>
<table width="98%"><thead><tr><th>维度</th><th>权重</th><th>得分</th><th>贡献</th><th>核心依据</th></tr></thead>
<tbody>{''.join(row(d) for d in fused.get('radar', []))}</tbody></table>

<h2>分析师团队</h2>
{views_html}

<h2>多空辩论</h2>
<table class="two" width="100%"><tr>
<td><h3>多头研究员</h3><ul>{bull}</ul></td>
<td class="bear"><h3>空头研究员</h3><ul>{bear}</ul></td>
</tr></table>

<h2>交易计划</h2>
<div class="plan">
<b>{esc(dec.get('action', '观望'))}</b>　参考仓位上限 {dec.get('position_pct', 0):.1f}%　周期 {esc(dec.get('horizon', ''))}<br>
建仓区间 {price(dec.get('entry_low', 0))} ~ {price(dec.get('entry_high', 0))}　|　
止损 {price(dec.get('stop', 0))}　|　目标 {price(dec.get('target', 0))}　|　盈亏比 {dec.get('risk_reward', 0):.1f}
</div>

<h2>风险清单 · {esc(res.get('risk_level', '中'))}风险</h2>
<ul>{risks}</ul>

<h2>方法与声明</h2>
<div class="footer">
数据：公开行情接口（东方财富/腾讯/新浪，按优先级回退）；公告巨潮资讯；宏观国家统计局（经数据中心转发）；汇率中国外汇交易中心。<br>
模型：短周期 Ridge + Logistic + 历史形态类比，滚动样本外集成；长周期六维评分 + 蒙特卡洛（bootstrap 残差）。每小时重新拉取数据、重算因子、重估权重。<br>
所有概率均为统计倾向，不构成收益承诺或投资建议。A 股存在涨跌停、停牌、复权与流动性约束，回测无法完全复现。<br>
观澜 QuantDesk · {esc(res.get('generated_at', ''))}　|　责任归属：@烬羽鱼
</div>
</body></html>"""


def build_print_html(r: dict) -> str:
    """打印版：把 CSS 的 px 换算为 pt，避免高 DPI 打印机把正文缩成亚像素。"""
    html = build_html(r)
    return re.sub(r"(\d+(?:\.\d+)?)px", lambda m: f"{float(m.group(1)) * 0.75:g}pt", html)
