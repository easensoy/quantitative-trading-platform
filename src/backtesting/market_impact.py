from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional
import numpy as np
import pandas as pd
from src.core.models import Order, MarketData, Instrument


@dataclass
class MarketImpactParameters:
    permanent_impact_coeff: float = 0.1
    temporary_impact_coeff: float = 0.05
    participation_rate: float = 0.1
    volatility_impact_factor: float = 0.5
    liquidity_factor: float = 1.0


class MarketImpactModel(ABC):
    @abstractmethod
    def calculate_impact(
        self,
        order: Order,
        market_data: MarketData,
        participation_rate: float = 0.1
    ) -> Dict[str, float]:
        pass


class LinearMarketImpactModel(MarketImpactModel):
    def __init__(self, params: MarketImpactParameters):
        self.params = params

    def calculate_impact(
        self,
        order: Order,
        market_data: MarketData,
        participation_rate: float = 0.1
    ) -> Dict[str, float]:
        if market_data.volume is None or market_data.volume == 0:
            return {"permanent_impact": 0.0, "temporary_impact": 0.0}

        mid_price = market_data.mid_price or market_data.last or 0
        if mid_price == 0:
            return {"permanent_impact": 0.0, "temporary_impact": 0.0}

        trade_size_ratio = order.quantity / market_data.volume
        spread = market_data.spread or (mid_price * 0.001)
        
        permanent_impact = (
            self.params.permanent_impact_coeff *
            np.sqrt(trade_size_ratio) *
            (spread / mid_price)
        )
        
        temporary_impact = (
            self.params.temporary_impact_coeff *
            trade_size_ratio *
            (spread / mid_price)
        )
        
        return {
            "permanent_impact": permanent_impact,
            "temporary_impact": temporary_impact,
            "total_impact": permanent_impact + temporary_impact
        }


class SqrtMarketImpactModel(MarketImpactModel):
    def __init__(self, params: MarketImpactParameters):
        self.params = params

    def calculate_impact(
        self,
        order: Order,
        market_data: MarketData,
        participation_rate: float = 0.1
    ) -> Dict[str, float]:
        if market_data.volume is None or market_data.volume == 0:
            return {"permanent_impact": 0.0, "temporary_impact": 0.0}

        mid_price = market_data.mid_price or market_data.last or 0
        if mid_price == 0:
            return {"permanent_impact": 0.0, "temporary_impact": 0.0}

        adv = market_data.volume
        trade_size = order.quantity
        
        sigma = self._estimate_volatility(market_data)
        
        permanent_impact = (
            self.params.permanent_impact_coeff *
            sigma *
            np.sqrt(trade_size / adv)
        )
        
        temporary_impact = (
            self.params.temporary_impact_coeff *
            sigma *
            (trade_size / adv) ** 0.6
        )
        
        if order.side.value == "sell":
            permanent_impact *= -1
            temporary_impact *= -1
        
        return {
            "permanent_impact": permanent_impact,
            "temporary_impact": temporary_impact,
            "total_impact": permanent_impact + temporary_impact
        }

    def _estimate_volatility(self, market_data: MarketData) -> float:
        spread = market_data.spread
        mid_price = market_data.mid_price or market_data.last or 1
        
        if spread is not None and mid_price > 0:
            return max(spread / mid_price, 0.001)
        else:
            return 0.02


class AlmgrenChrissFunctionalModel(MarketImpactModel):
    def __init__(self, params: MarketImpactParameters):
        self.params = params
        self.eta = params.temporary_impact_coeff
        self.gamma = params.permanent_impact_coeff

    def calculate_impact(
        self,
        order: Order,
        market_data: MarketData,
        participation_rate: float = 0.1
    ) -> Dict[str, float]:
        if market_data.volume is None or market_data.volume == 0:
            return {"permanent_impact": 0.0, "temporary_impact": 0.0}

        mid_price = market_data.mid_price or market_data.last or 0
        if mid_price == 0:
            return {"permanent_impact": 0.0, "temporary_impact": 0.0}

        adv = market_data.volume
        trade_size = order.quantity
        sigma = self._estimate_volatility(market_data)
        
        v_rate = trade_size / adv
        
        permanent_impact = self.gamma * v_rate * sigma
        
        temporary_impact = self.eta * v_rate * sigma
        
        if order.side.value == "sell":
            permanent_impact *= -1
            temporary_impact *= -1
        
        return {
            "permanent_impact": permanent_impact,
            "temporary_impact": temporary_impact,
            "total_impact": permanent_impact + temporary_impact
        }

    def _estimate_volatility(self, market_data: MarketData) -> float:
        spread = market_data.spread
        mid_price = market_data.mid_price or market_data.last or 1
        
        if spread is not None and mid_price > 0:
            return max(spread / mid_price, 0.001)
        else:
            return 0.02


class MarketImpactEngine:
    def __init__(self, model_type: str = "sqrt"):
        self.params = MarketImpactParameters()
        
        if model_type == "linear":
            self.model = LinearMarketImpactModel(self.params)
        elif model_type == "sqrt":
            self.model = SqrtMarketImpactModel(self.params)
        elif model_type == "almgren_chriss":
            self.model = AlmgrenChrissFunctionalModel(self.params)
        else:
            raise ValueError(f"Unknown market impact model: {model_type}")

    def calculate_execution_cost(
        self,
        order: Order,
        market_data: MarketData,
        participation_rate: float = 0.1
    ) -> Dict[str, float]:
        impact = self.model.calculate_impact(order, market_data, participation_rate)
        
        mid_price = market_data.mid_price or market_data.last or 0
        notional = order.quantity * mid_price
        
        permanent_cost = impact["permanent_impact"] * notional
        temporary_cost = impact["temporary_impact"] * notional
        
        spread_cost = 0
        if market_data.spread:
            spread_cost = (market_data.spread / 2) * order.quantity
        
        commission = notional * 0.001
        
        return {
            "permanent_cost": permanent_cost,
            "temporary_cost": temporary_cost,
            "spread_cost": spread_cost,
            "commission": commission,
            "total_cost": permanent_cost + temporary_cost + spread_cost + commission
        }

    def update_parameters(self, new_params: MarketImpactParameters) -> None:
        self.params = new_params
        if isinstance(self.model, LinearMarketImpactModel):
            self.model.params = new_params
        elif isinstance(self.model, SqrtMarketImpactModel):
            self.model.params = new_params
        elif isinstance(self.model, AlmgrenChrissFunctionalModel):
            self.model.params = new_params
            self.model.eta = new_params.temporary_impact_coeff
            self.model.gamma = new_params.permanent_impact_coeff