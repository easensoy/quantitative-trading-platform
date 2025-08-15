from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import Ridge, Lasso
from sklearn.metrics import information_score
import warnings
warnings.filterwarnings('ignore')
from src.core.models import Instrument, MarketData, Order, OrderSide, Strategy
from src.core.event_bus import EventBus
@dataclass
class AlphaSignal:
    instrument: Instrument
    timestamp: datetime
    signal_value: float
    confidence: float
    decay_half_life: int
    signal_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    @property
    def is_strong(self) -> bool:
        return abs(self.signal_value) > 0.02 and self.confidence > 0.7
    @property
    def is_actionable(self) -> bool:
        return abs(self.signal_value) > 0.01 and self.confidence > 0.5
@dataclass 
class FeatureSet:
    features: Dict[str, float]
    timestamp: datetime
    instrument: Instrument
    def to_array(self, feature_names: List[str]) -> np.ndarray:
        return np.array([self.features.get(name, 0.0) for name in feature_names])
class FeatureEngineer:
    def __init__(self):
        self.price_history: Dict[str, List[Tuple[datetime, float]]] = {}
        self.volume_history: Dict[str, List[Tuple[datetime, int]]] = {}
        self.lookback_periods = [5, 10, 20, 60, 120]
    def update_data(self, symbol: str, market_data: MarketData) -> None:
        timestamp = market_data.timestamp
        price = market_data.mid_price or market_data.last or 0.0
        volume = market_data.volume or 0
        if symbol not in self.price_history:
            self.price_history[symbol] = []
            self.volume_history[symbol] = []
        self.price_history[symbol].append((timestamp, price))
        self.volume_history[symbol].append((timestamp, volume))
        cutoff = timestamp - timedelta(days=200)
        self.price_history[symbol] = [(t, p) for t, p in self.price_history[symbol] if t > cutoff]
        self.volume_history[symbol] = [(t, v) for t, v in self.volume_history[symbol] if t > cutoff]
    def extract_features(self, symbol: str, market_data: MarketData) -> Optional[FeatureSet]:
        if symbol not in self.price_history or len(self.price_history[symbol]) < 60:
            return None
        features = {}
        prices = [p for _, p in self.price_history[symbol]]
        volumes = [v for _, v in self.volume_history[symbol]]
        features.update(self._price_momentum_features(prices))
        features.update(self._volatility_features(prices))
        features.update(self._technical_features(prices))
        features.update(self._volume_features(volumes, prices))
        features.update(self._microstructure_features(market_data))
        features.update(self._regime_features(prices))
        return FeatureSet(features, market_data.timestamp, market_data.instrument)
    def _price_momentum_features(self, prices: List[float]) -> Dict[str, float]:
        features = {}
        for period in self.lookback_periods:
            if len(prices) > period:
                ret = (prices[-1] / prices[-period] - 1) if prices[-period] != 0 else 0
                features[f'momentum_{period}d'] = ret
                if len(prices) > period + 10:
                    vol = np.std([prices[i]/prices[i-1] - 1 for i in range(-period, -1) if prices[i-1] != 0])
                    features[f'risk_adj_momentum_{period}d'] = ret / max(vol, 0.001)
        if len(prices) > 20:
            x = np.arange(20)
            y = np.array(prices[-20:])
            trend = np.polyfit(x, np.log(y + 1e-8), 1)[0]
            features['trend_strength'] = trend
        return features
    def _volatility_features(self, prices: List[float]) -> Dict[str, float]:
        features = {}
        if len(prices) < 20:
            return features
        returns = [prices[i]/prices[i-1] - 1 for i in range(1, len(prices)) if prices[i-1] != 0]
        for period in [10, 20, 60]:
            if len(returns) > period:
                vol = np.std(returns[-period:])
                features[f'volatility_{period}d'] = vol
                if len(returns) > period + 10:
                    rolling_vols = []
                    for i in range(period, len(returns)):
                        rolling_vols.append(np.std(returns[i-period:i]))
                    features[f'vol_of_vol_{period}d'] = np.std(rolling_vols)
        negative_returns = [r for r in returns[-20:] if r < 0]
        if negative_returns:
            features['downside_deviation'] = np.std(negative_returns)
        return features
    def _technical_features(self, prices: List[float]) -> Dict[str, float]:
        features = {}
        if len(prices) < 50:
            return features
        for period in [10, 20, 50]:
            if len(prices) >= period:
                ma = np.mean(prices[-period:])
                features[f'ma_{period}_ratio'] = prices[-1] / ma - 1 if ma != 0 else 0
        if len(prices) >= 20:
            ma_20 = np.mean(prices[-20:])
            std_20 = np.std(prices[-20:])
            upper_band = ma_20 + 2 * std_20
            lower_band = ma_20 - 2 * std_20
            if upper_band != lower_band:
                features['bb_position'] = (prices[-1] - lower_band) / (upper_band - lower_band)
        gains = []
        losses = []
        for i in range(1, min(15, len(prices))):
            change = prices[-i] - prices[-i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(-change)
        if gains and losses:
            avg_gain = np.mean(gains)
            avg_loss = np.mean(losses)
            if avg_loss != 0:
                rs = avg_gain / avg_loss
                features['rsi'] = 100 - (100 / (1 + rs))
        return features
    def _volume_features(self, volumes: List[int], prices: List[float]) -> Dict[str, float]:
        features = {}
        if len(volumes) < 20 or len(prices) < 20:
            return features
        for period in [10, 20]:
            if len(volumes) >= period:
                vol_ma = np.mean(volumes[-period:])
                features[f'volume_ma_{period}_ratio'] = volumes[-1] / vol_ma if vol_ma != 0 else 0
        if len(volumes) == len(prices) and len(volumes) > 10:
            price_changes = [prices[i] - prices[i-1] for i in range(1, min(11, len(prices)))]
            volume_changes = [volumes[i] - volumes[i-1] for i in range(1, min(11, len(volumes)))]
            if len(price_changes) == len(volume_changes) and len(price_changes) > 5:
                correlation = np.corrcoef(price_changes, volume_changes)[0, 1]
                features['price_volume_corr'] = correlation if not np.isnan(correlation) else 0
        return features
    def _microstructure_features(self, market_data: MarketData) -> Dict[str, float]:
        features = {}
        if market_data.bid and market_data.ask:
            spread = market_data.ask - market_data.bid
            mid_price = (market_data.ask + market_data.bid) / 2
            features['bid_ask_spread'] = spread
            features['relative_spread'] = spread / mid_price if mid_price != 0 else 0
            if market_data.bid_size and market_data.ask_size:
                total_size = market_data.bid_size + market_data.ask_size
                features['bid_ask_imbalance'] = (market_data.bid_size - market_data.ask_size) / total_size if total_size != 0 else 0
        return features
    def _regime_features(self, prices: List[float]) -> Dict[str, float]:
        features = {}
        if len(prices) < 60:
            return features
        short_returns = [prices[i]/prices[i-1] - 1 for i in range(-20, -1) if prices[i-1] != 0]
        long_returns = [prices[i]/prices[i-1] - 1 for i in range(-60, -20) if prices[i-1] != 0]
        if len(short_returns) > 10 and len(long_returns) > 10:
            short_vol = np.std(short_returns)
            long_vol = np.std(long_returns)
            features['vol_regime'] = short_vol / long_vol if long_vol != 0 else 1
        return features
class AlphaModel(ABC):
    @abstractmethod
    def train(self, features: List[FeatureSet], targets: List[float]) -> None:
        pass
    @abstractmethod
    def predict(self, features: FeatureSet) -> Tuple[float, float]:
        pass
    @abstractmethod
    def get_feature_importance(self) -> Dict[str, float]:
        pass
class EnsembleAlphaModel(AlphaModel):
    def __init__(self):
        self.models = {
            'rf': RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42),
            'gbm': GradientBoostingRegressor(n_estimators=100, max_depth=6, random_state=42),
            'ridge': Ridge(alpha=1.0),
            'lasso': Lasso(alpha=0.1)
        }
        self.scaler = RobustScaler()
        self.feature_names: List[str] = []
        self.is_trained = False
    def train(self, features: List[FeatureSet], targets: List[float]) -> None:
        if not features or not targets:
            return
        self.feature_names = list(features[0].features.keys())
        X = np.array([f.to_array(self.feature_names) for f in features])
        y = np.array(targets)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
        if X.shape[0] < 50:  
            return
        X_scaled = self.scaler.fit_transform(X)
        for name, model in self.models.items():
            try:
                model.fit(X_scaled, y)
            except Exception as e:
                print(f"Failed to train {name}: {e}")
        self.is_trained = True
    def predict(self, features: FeatureSet) -> Tuple[float, float]:
        if not self.is_trained:
            return 0.0, 0.0
        X = features.to_array(self.feature_names).reshape(1, -1)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        X_scaled = self.scaler.transform(X)
        predictions = []
        for name, model in self.models.items():
            try:
                pred = model.predict(X_scaled)[0]
                predictions.append(pred)
            except Exception:
                continue
        if not predictions:
            return 0.0, 0.0
        signal = np.mean(predictions)
        confidence = 1.0 - (np.std(predictions) / max(abs(signal), 0.01))
        confidence = max(0.0, min(1.0, confidence))
        return signal, confidence
    def get_feature_importance(self) -> Dict[str, float]:
        if not self.is_trained:
            return {}
        importance_dict = {}
        for name, model in self.models.items():
            if hasattr(model, 'feature_importances_'):
                for i, importance in enumerate(model.feature_importances_):
                    feature_name = self.feature_names[i]
                    if feature_name not in importance_dict:
                        importance_dict[feature_name] = 0.0
                    importance_dict[feature_name] += importance
        total_importance = sum(importance_dict.values())
        if total_importance > 0:
            importance_dict = {k: v/total_importance for k, v in importance_dict.items()}
        return importance_dict
class AlphaResearchEngine:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.feature_engineer = FeatureEngineer()
        self.alpha_models: Dict[str, AlphaModel] = {}
        self.signals_history: Dict[str, List[AlphaSignal]] = {}
        self.performance_tracker: Dict[str, List[float]] = {}
    async def initialize(self) -> None:
        await self.event_bus.subscribe("market_data", self._handle_market_data)
        self.alpha_models = {
            'equity_momentum': EnsembleAlphaModel(),
            'equity_reversion': EnsembleAlphaModel(),
            'volatility_forecast': EnsembleAlphaModel(),
            'cross_asset_momentum': EnsembleAlphaModel()
        }
    async def _handle_market_data(self, data: Dict) -> None:
        symbol = data["symbol"]
        market_data = data["market_data"]
        self.feature_engineer.update_data(symbol, market_data)
        signals = await self.generate_alpha_signals(symbol, market_data)
        for signal in signals:
            await self.event_bus.publish("alpha_signal", {
                "symbol": symbol,
                "signal": signal
            })
    async def generate_alpha_signals(self, symbol: str, market_data: MarketData) -> List[AlphaSignal]:
        features = self.feature_engineer.extract_features(symbol, market_data)
        if not features:
            return []
        signals = []
        for model_name, model in self.alpha_models.items():
            if not model.is_trained:
                continue
            signal_value, confidence = model.predict(features)
            if abs(signal_value) > 0.005:  
                signal = AlphaSignal(
                    instrument=market_data.instrument,
                    timestamp=market_data.timestamp,
                    signal_value=signal_value,
                    confidence=confidence,
                    decay_half_life=self._get_decay_half_life(model_name),
                    signal_type=model_name,
                    metadata={'features_used': len(features.features)}
                )
                signals.append(signal)
                if symbol not in self.signals_history:
                    self.signals_history[symbol] = []
                self.signals_history[symbol].append(signal)
        return signals
    def _get_decay_half_life(self, model_name: str) -> int:
        decay_mapping = {
            'equity_momentum': 10,
            'equity_reversion': 3,
            'volatility_forecast': 5,
            'cross_asset_momentum': 15
        }
        return decay_mapping.get(model_name, 7)
    async def train_models(self, lookback_days: int = 252) -> None:
        print(f"Training models with {lookback_days} days of lookback data")
        for model_name, model in self.alpha_models.items():
            print(f"Training {model_name}...")
    def get_signal_performance(self, symbol: str, days_back: int = 30) -> Dict[str, float]:
        if symbol not in self.signals_history:
            return {}
        cutoff = datetime.utcnow() - timedelta(days=days_back)
        recent_signals = [s for s in self.signals_history[symbol] if s.timestamp > cutoff]
        if not recent_signals:
            return {}
        strong_signals = [s for s in recent_signals if s.is_strong]
        actionable_signals = [s for s in recent_signals if s.is_actionable]
        return {
            'total_signals': len(recent_signals),
            'strong_signals': len(strong_signals),
            'actionable_signals': len(actionable_signals),
            'avg_confidence': np.mean([s.confidence for s in recent_signals]),
            'avg_signal_strength': np.mean([abs(s.signal_value) for s in recent_signals])
        }
    def get_model_diagnostics(self) -> Dict[str, Any]:
        diagnostics = {}
        for model_name, model in self.alpha_models.items():
            if hasattr(model, 'is_trained') and model.is_trained:
                diagnostics[model_name] = {
                    'is_trained': True,
                    'feature_importance': model.get_feature_importance()
                }
            else:
                diagnostics[model_name] = {'is_trained': False}
        return diagnostics