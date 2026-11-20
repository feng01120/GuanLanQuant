"""Audit probe: data-source timing, DB integrity, recommend output."""
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.context import build_context
from app.config import DATA_DIR
from app.services.recommend import RecommendService


def sec(fn, label):
    t0 = time.time()
    try:
        out = fn()
        print(f"{label}: {time.time()-t0:.1f}s -> {str(out)[:160]}")
        return out
    except Exception as e:
        print(f"{label}: {time.time()-t0:.1f}s !! {type(e).__name__}: {e}")
        return None


ctx = build_context()
print("registry", ctx.registry.summary())
print("plugins", [(m.id, m.priority, m.load_error) for m in ctx.registry.manifests.values()])
db = Path(DATA_DIR) / "guanlan.db"
print("db", db, db.exists(), db.stat().st_size if db.exists() else None)
try:
    con = sqlite3.connect(db)
    print("integrity", con.execute("pragma integrity_check").fetchone())
    for t in ("bars", "quotes", "forecasts", "cycles", "sentiment"):
        try:
            print(t, con.execute(f"select count(*) from {t}").fetchone()[0])
        except Exception as e:
            print(t, "ERR", e)
    con.close()
except Exception as e:
    print("db ERR", e)

sec(lambda: ctx.market.ensure_bars("600519", 320), "bars 600519")
sec(lambda: ctx.market.ensure_bars("1.000001", 320), "bars index")
sec(lambda: ctx.market.market_context(), "market context")
rec = RecommendService(ctx.market)
out = sec(lambda: rec.daily(force=True), "recommend force")
if out:
    print("recommend keys", sorted(out.keys()))
    print("quality", out.get("data_quality"), "elapsed", out.get("elapsed"))
    print("market", json.dumps(out.get("market", {}), ensure_ascii=False, default=str)[:600])
    print("sectors", out.get("sectors", [])[:2])
    print("picks", [(x.get("symbol"), x.get("name"), round(x.get("prob3", 0), 3), x.get("grade")) for x in out.get("picks", [])])
    print("stats", out.get("stats"))
