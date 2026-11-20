"""插件内核：清单加载、能力索引、冲突检测、健康检查。"""
from __future__ import annotations

import importlib
import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import PLUGIN_DIR
from ..util import log

PLUGIN_API = "guanlan-1"
KIND_LABELS = {
    "datasource": "数据源",
    "factor": "因子",
    "model": "模型",
    "strategy": "策略",
    "research": "研判",
}


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    api: str
    kind: str
    capabilities: list[str] = field(default_factory=list)
    entry: str = ""
    priority: int = 50
    authority: str = "internal"
    description: str = ""
    endpoints: list[str] = field(default_factory=list)
    enabled: bool = True
    dir_name: str = ""
    load_error: str = ""

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


class PluginRegistry:
    def __init__(self, plugin_dir: Path = PLUGIN_DIR, http=None, store=None):
        self.plugin_dir = Path(plugin_dir)
        self.http = http
        self.store = store
        self.manifests: dict[str, Manifest] = {}
        self.instances: dict[str, Any] = {}
        self.capabilities: dict[str, list[str]] = {}
        self.conflicts: list[str] = []

    # ------------------------------------------------------------------
    def load_all(self) -> list[Manifest]:
        self.manifests.clear()
        self.instances.clear()
        self.capabilities.clear()
        self.conflicts.clear()
        if not self.plugin_dir.exists():
            return []
        for mf in sorted(self.plugin_dir.glob("*/manifest.json")):
            try:
                raw = json.loads(mf.read_text(encoding="utf-8"))
                m = Manifest(
                    id=str(raw.get("id") or mf.parent.name),
                    name=str(raw.get("name") or mf.parent.name),
                    version=str(raw.get("version") or "0.0.0"),
                    api=str(raw.get("api") or ""),
                    kind=str(raw.get("kind") or "datasource"),
                    capabilities=list(raw.get("capabilities") or []),
                    entry=str(raw.get("entry") or ""),
                    priority=int(raw.get("priority") or 50),
                    authority=str(raw.get("authority") or "internal"),
                    description=str(raw.get("description") or ""),
                    endpoints=list(raw.get("endpoints") or []),
                    enabled=bool(raw.get("enabled", True)),
                    dir_name=mf.parent.name,
                )
            except Exception as e:
                log.warning(f"插件清单读取失败 {mf}: {e}")
                continue
            if m.api != PLUGIN_API:
                m.load_error = f"API 版本不兼容：{m.api}（需要 {PLUGIN_API}）"
            elif not m.enabled:
                m.load_error = "已在清单中禁用"
            if m.id in self.manifests:
                self.conflicts.append(f"插件 ID 重复：{m.id}（{mf.parent.name}）")
                continue
            self.manifests[m.id] = m
            if m.load_error:
                log.warning(f"插件未加载 {m.id}: {m.load_error}")
                continue
            try:
                inst = self._load_entry(m)
                self.instances[m.id] = inst
                for cap in m.capabilities:
                    self.capabilities.setdefault(cap, []).append(m.id)
            except Exception as e:
                m.load_error = f"入口加载失败：{e}"
                log.warning(f"插件入口失败 {m.id}: {e}")
        # 能力冲突（同能力多插件是允许的，但需在 UI 明示优先级）
        for cap, ids in self.capabilities.items():
            if len(ids) > 1:
                self.conflicts.append(
                    f"能力 {cap} 由 {len(ids)} 个插件提供：" + "、".join(ids) + "（按优先级回退）")
        for cap, ids in self.capabilities.items():
            ids.sort(key=lambda i: self.manifests[i].priority)
        return list(self.manifests.values())

    def _load_entry(self, m: Manifest) -> Any:
        if not m.entry:
            return None
        if ":" not in m.entry:
            return importlib.import_module(m.entry)
        mod_name, cls_name = m.entry.split(":", 1)
        module = importlib.import_module(mod_name)
        cls = getattr(module, cls_name)
        sig = inspect.signature(cls)
        kwargs = {}
        if "http" in sig.parameters:
            kwargs["http"] = self.http
        if "settings" in sig.parameters:
            kwargs["settings"] = getattr(self, "settings", None)
        if "store" in sig.parameters:
            kwargs["store"] = self.store
        return cls(**kwargs)

    # ------------------------------------------------------------------
    def get(self, plugin_id: str) -> Any | None:
        return self.instances.get(plugin_id)

    def providers(self, capability: str) -> list[tuple[Manifest, Any]]:
        ids = self.capabilities.get(capability, [])
        return [(self.manifests[i], self.instances.get(i)) for i in ids if self.instances.get(i)]

    def first(self, capability: str) -> tuple[Manifest, Any] | None:
        p = self.providers(capability)
        return p[0] if p else None

    def call(self, capability: str, method: str, *args, **kwargs):
        """按优先级回退调用；返回 (结果, 使用的插件 id)。"""
        errors = []
        for m, inst in self.providers(capability):
            fn = getattr(inst, method, None)
            if not callable(fn):
                continue
            try:
                return fn(*args, **kwargs), m.id
            except Exception as e:  # noqa: BLE001
                errors.append(f"{m.id}: {e}")
                if "已熔断" not in str(e):
                    log.warning(f"插件调用失败 {m.id}.{method}: {e}")
        raise RuntimeError("；".join(errors) or f"没有可用的 {capability} 插件")

    def call_chain(self, capability: str, method: str, *args, **kwargs):
        """逐个尝试，返回第一个非空结果（结果 + 来源）。"""
        errors = []
        for m, inst in self.providers(capability):
            fn = getattr(inst, method, None)
            if not callable(fn):
                continue
            try:
                result = fn(*args, **kwargs)
                # 空列表/空表/空 DataFrame 不能算成功，否则东财返回
                # {"data": null} 时会挡住腾讯/新浪的备用 K 线。
                if result is None:
                    errors.append(f"{m.id}: 返回空")
                    continue
                try:
                    if len(result) == 0:
                        errors.append(f"{m.id}: 返回空")
                        continue
                except TypeError:
                    pass
                return result, m.id
            except Exception as e:  # noqa: BLE001
                errors.append(f"{m.id}: {e}")
                if "已熔断" not in str(e):
                    log.warning(f"备用源失败 {m.id}.{method}: {e}")
        raise RuntimeError("；".join(errors) or f"{capability} 全部数据源失败")

    # ------------------------------------------------------------------
    def health_all(self) -> list[dict]:
        results = []
        for m in self.manifests.values():
            inst = self.instances.get(m.id)
            t0 = time.time()
            if m.load_error:
                ok, msg, latency = False, m.load_error, 0.0
            elif inst is None:
                ok, msg, latency = True, "声明型插件（模块已注册）", (time.time() - t0) * 1000
            elif hasattr(inst, "health"):
                try:
                    ok, latency, msg = inst.health()
                except Exception as e:  # noqa: BLE001
                    ok, latency, msg = False, (time.time() - t0) * 1000, str(e)[:120]
            else:
                ok, msg, latency = True, "已加载", (time.time() - t0) * 1000
            item = {"id": m.id, "name": m.name, "kind": m.kind, "ok": bool(ok),
                    "latency": float(latency), "message": msg}
            results.append(item)
            if self.store is not None:
                try:
                    self.store.save_plugin_health(m.id, bool(ok), float(latency), str(msg))
                except Exception:
                    pass
        return results

    def status_dict(self) -> dict[str, dict]:
        if self.store is None:
            return {}
        return {r["plugin"]: r for r in self.store.plugin_health()}

    def summary(self) -> dict:
        total = len(self.manifests)
        loaded = sum(1 for m in self.manifests.values() if not m.load_error)
        failing = total - loaded
        return {"total": total, "loaded": loaded, "failing": failing,
                "capabilities": len(self.capabilities), "conflicts": len(self.conflicts)}
