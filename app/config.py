"""全局配置与路径。"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

APP_NAME = "观澜 QuantDesk"
APP_NAME_EN = "GUANLAN QUANTDESK"
APP_VERSION = "1.1.5"
APP_SLOGAN = "多维研判 · 长短周期 · 每小时自校准"

# 源码运行：根目录是 app/ 的上一级；打包后：可写数据放在 exe 同级，只读插件随包。
_FROZEN = bool(getattr(sys, "frozen", False))
if _FROZEN:
    ROOT = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", ROOT))
else:
    ROOT = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = ROOT
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = ROOT / "logs"
REPORT_DIR = ROOT / "reports"
PLUGIN_DIR = BUNDLE_DIR / "plugins"
DB_PATH = DATA_DIR / "guanlan.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

for _p in (DATA_DIR, CACHE_DIR, LOG_DIR, REPORT_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# 指数（secid, 名称, 简称）
INDICES = [
    ("1.000001", "上证指数", "SH"),
    ("0.399001", "深证成指", "SZ"),
    ("0.399006", "创业板指", "CYB"),
    ("1.000300", "沪深300", "HS300"),
]

# 默认自选池：覆盖消费、金融、科技、新能源、资源、医药与宽基 ETF
DEFAULT_WATCHLIST = [
    ("600519", "贵州茅台"),
    ("300750", "宁德时代"),
    ("601318", "中国平安"),
    ("000858", "五粮液"),
    ("002594", "比亚迪"),
    ("600036", "招商银行"),
    ("601899", "紫金矿业"),
    ("300059", "东方财富"),
    ("688981", "中芯国际"),
    ("510300", "沪深300ETF"),
]

DEFAULT_SETTINGS: dict[str, Any] = {
    "watchlist": [c for c, _ in DEFAULT_WATCHLIST],
    "watchlist_names": {c: n for c, n in DEFAULT_WATCHLIST},
    "hourly_interval_sec": 3600,
    "quote_refresh_sec": 20,
    "history_days": 900,
    "backtest_days": 260,
    "min_train": 180,
    "monte_carlo_paths": 2600,
    "enable_humanities": True,
    "enable_macro": True,
    "risk_free_proxy": "1.511010",
    "max_position_pct": 0.2,
    "theme": "dark",
}


class Settings:
    """线程安全的 JSON 设置。"""

    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> dict[str, Any]:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        merged = dict(DEFAULT_SETTINGS)
                        merged.update(raw)
                        self._data = merged
                except Exception:
                    pass
            return self._data

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, self.path)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        with self._lock:
            self._data[key] = value
            if persist:
                self.save()

    def update(self, values: dict[str, Any], persist: bool = True) -> None:
        with self._lock:
            self._data.update(values)
            if persist:
                self.save()

    @property
    def watchlist(self) -> list[str]:
        wl = self.get("watchlist", [])
        return [str(x) for x in wl if str(x).strip()]

    @property
    def watchlist_names(self) -> dict[str, str]:
        return dict(self.get("watchlist_names", {}))

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)


def env_flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}
