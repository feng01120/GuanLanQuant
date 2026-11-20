"""应用上下文：把设置、存储、插件、服务装配在一起。"""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .data.http import HttpClient
from .data.store import Store
from .kernel.registry import PluginRegistry
from .services.market import MarketService
from .services.portfolio import PortfolioService
from .services.recommend import RecommendService


@dataclass
class AppContext:
    settings: Settings
    store: Store
    http: HttpClient
    registry: PluginRegistry
    market: MarketService
    portfolio: PortfolioService
    recommend: RecommendService
    active_symbol: str = ""


def build_context() -> AppContext:
    settings = Settings()
    store = Store()
    http = HttpClient()
    registry = PluginRegistry(http=http, store=store)
    registry.settings = settings
    registry.load_all()
    market = MarketService(settings, store, registry, http)
    portfolio = PortfolioService(store, market)
    recommend = RecommendService(market)
    return AppContext(settings=settings, store=store, http=http, registry=registry,
                      market=market, portfolio=portfolio, recommend=recommend)
