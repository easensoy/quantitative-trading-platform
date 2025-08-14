from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA, FactorAnalysis
from sklearn.covariance import LedoitWolf, OAS, ShrunkCovariance
import warnings
warnings.filterwarnings('ignore')


@dataclass
class RiskFactors:
    factor_exposures: pd.DataFrame
    factor_returns: pd.DataFrame
    specific_risk: pd.Series
    factor_covariance: pd.DataFrame


class RiskModel(ABC):
    @abstractmethod
    def estimate_risk_model(
        self,
        returns: pd.DataFrame,
        **kwargs
    ) -> RiskFactors:
        pass

    @abstractmethod
    def calculate_portfolio_risk(
        self,
        weights: np.ndarray,
        risk_factors: RiskFactors
    ) -> Dict[str, float]:
        pass


class HistoricalCovarianceModel(RiskModel):
    def __init__(self, window: int = 252, shrinkage_method: str = 'ledoit_wolf'):
        self.window = window
        self.shrinkage_method = shrinkage_method

    def estimate_risk_model(
        self,
        returns: pd.DataFrame,
        **kwargs
    ) -> RiskFactors:
        if len(returns) < self.window:
            window = len(returns)
        else:
            window = self.window
        
        recent_returns = returns.iloc[-window:]
        
        if self.shrinkage_method == 'ledoit_wolf':
            lw = LedoitWolf()
            covariance_matrix = lw.fit(recent_returns).covariance_
        elif self.shrinkage_method == 'oas':
            oas = OAS()
            covariance_matrix = oas.fit(recent_returns).covariance_
        elif self.shrinkage_method == 'shrunk':
            shrunk = ShrunkCovariance()
            covariance_matrix = shrunk.fit(recent_returns).covariance_
        else:
            covariance_matrix = recent_returns.cov().values
        
        covariance_df = pd.DataFrame(
            covariance_matrix,
            index=returns.columns,
            columns=returns.columns
        )
        
        specific_risk = pd.Series(
            np.sqrt(np.diag(covariance_matrix)),
            index=returns.columns
        )
        
        return RiskFactors(
            factor_exposures=pd.DataFrame(index=returns.columns),
            factor_returns=pd.DataFrame(),
            specific_risk=specific_risk,
            factor_covariance=covariance_df
        )

    def calculate_portfolio_risk(
        self,
        weights: np.ndarray,
        risk_factors: RiskFactors
    ) -> Dict[str, float]:
        portfolio_variance = np.dot(weights, np.dot(risk_factors.factor_covariance.values, weights))
        portfolio_volatility = np.sqrt(portfolio_variance)
        
        return {
            'total_risk': portfolio_volatility,
            'factor_risk': 0.0,
            'specific_risk': portfolio_volatility
        }


class FactorRiskModel(RiskModel):
    def __init__(
        self,
        n_factors: int = 10,
        factor_method: str = 'pca',
        window: int = 252
    ):
        self.n_factors = n_factors
        self.factor_method = factor_method
        self.window = window

    def estimate_risk_model(
        self,
        returns: pd.DataFrame,
        **kwargs
    ) -> RiskFactors:
        if len(returns) < self.window:
            window = len(returns)
        else:
            window = self.window
        
        recent_returns = returns.iloc[-window:]
        
        if self.factor_method == 'pca':
            factor_model = PCA(n_components=self.n_factors)
        elif self.factor_method == 'factor_analysis':
            factor_model = FactorAnalysis(n_components=self.n_factors)
        else:
            raise ValueError(f"Unknown factor method: {self.factor_method}")
        
        factor_exposures = factor_model.fit_transform(recent_returns.T)
        factor_exposures_df = pd.DataFrame(
            factor_exposures,
            index=returns.columns,
            columns=[f'Factor_{i+1}' for i in range(self.n_factors)]
        )
        
        factor_returns = recent_returns @ factor_exposures_df
        factor_returns.columns = [f'Factor_{i+1}' for i in range(self.n_factors)]
        
        factor_covariance = factor_returns.cov()
        
        residuals = recent_returns - (factor_returns @ factor_exposures_df.T)
        specific_risk = residuals.std()
        
        return RiskFactors(
            factor_exposures=factor_exposures_df,
            factor_returns=factor_returns,
            specific_risk=specific_risk,
            factor_covariance=factor_covariance
        )

    def calculate_portfolio_risk(
        self,
        weights: np.ndarray,
        risk_factors: RiskFactors
    ) -> Dict[str, float]:
        portfolio_factor_exposure = risk_factors.factor_exposures.T @ weights
        
        factor_risk_contribution = np.dot(
            portfolio_factor_exposure,
            np.dot(risk_factors.factor_covariance.values, portfolio_factor_exposure)
        )
        
        specific_risk_contribution = np.sum(
            (weights ** 2) * (risk_factors.specific_risk.values ** 2)
        )
        
        total_risk = np.sqrt(factor_risk_contribution + specific_risk_contribution)
        
        return {
            'total_risk': total_risk,
            'factor_risk': np.sqrt(factor_risk_contribution),
            'specific_risk': np.sqrt(specific_risk_contribution)
        }


class FamaFrenchRiskModel(RiskModel):
    def __init__(self, factors: List[str] = None):
        if factors is None:
            self.factors = ['MKT', 'SMB', 'HML', 'RMW', 'CMA']
        else:
            self.factors = factors

    def estimate_risk_model(
        self,
        returns: pd.DataFrame,
        factor_returns: pd.DataFrame,
        **kwargs
    ) -> RiskFactors:
        available_factors = [f for f in self.factors if f in factor_returns.columns]
        
        if not available_factors:
            raise ValueError("No Fama-French factors found in factor_returns")
        
        aligned_returns, aligned_factors = returns.align(
            factor_returns[available_factors],
            join='inner',
            axis=0
        )
        
        factor_exposures = []
        specific_risks = []
        
        for asset in aligned_returns.columns:
            asset_returns = aligned_returns[asset].dropna()
            asset_factors = aligned_factors.loc[asset_returns.index]
            
            if len(asset_returns) < 20:
                factor_exposures.append(np.zeros(len(available_factors)))
                specific_risks.append(asset_returns.std())
                continue
            
            X = asset_factors.values
            y = asset_returns.values
            
            try:
                beta = np.linalg.lstsq(X, y, rcond=None)[0]
            except np.linalg.LinAlgError:
                beta = np.zeros(len(available_factors))
            
            factor_exposures.append(beta)
            
            predicted_returns = X @ beta
            residuals = y - predicted_returns
            specific_risk = np.std(residuals)
            specific_risks.append(specific_risk)
        
        factor_exposures_df = pd.DataFrame(
            factor_exposures,
            index=returns.columns,
            columns=available_factors
        )
        
        factor_covariance = aligned_factors.cov()
        
        specific_risk_series = pd.Series(
            specific_risks,
            index=returns.columns
        )
        
        return RiskFactors(
            factor_exposures=factor_exposures_df,
            factor_returns=aligned_factors,
            specific_risk=specific_risk_series,
            factor_covariance=factor_covariance
        )

    def calculate_portfolio_risk(
        self,
        weights: np.ndarray,
        risk_factors: RiskFactors
    ) -> Dict[str, float]:
        portfolio_factor_exposure = risk_factors.factor_exposures.T @ weights
        
        factor_risk_contribution = np.dot(
            portfolio_factor_exposure,
            np.dot(risk_factors.factor_covariance.values, portfolio_factor_exposure)
        )
        
        specific_risk_contribution = np.sum(
            (weights ** 2) * (risk_factors.specific_risk.values ** 2)
        )
        
        total_risk = np.sqrt(factor_risk_contribution + specific_risk_contribution)
        
        return {
            'total_risk': total_risk,
            'factor_risk': np.sqrt(factor_risk_contribution),
            'specific_risk': np.sqrt(specific_risk_contribution)
        }


class GARCHRiskModel(RiskModel):
    def __init__(self, window: int = 252):
        self.window = window

    def estimate_risk_model(
        self,
        returns: pd.DataFrame,
        **kwargs
    ) -> RiskFactors:
        if len(returns) < self.window:
            window = len(returns)
        else:
            window = self.window
        
        recent_returns = returns.iloc[-window:]
        
        garch_volatilities = []
        
        for column in recent_returns.columns:
            asset_returns = recent_returns[column].dropna()
            
            if len(asset_returns) < 50:
                garch_volatilities.append(asset_returns.std())
                continue
            
            volatility = self._estimate_garch_volatility(asset_returns)
            garch_volatilities.append(volatility)
        
        specific_risk = pd.Series(
            garch_volatilities,
            index=returns.columns
        )
        
        correlation_matrix = recent_returns.corr()
        volatility_matrix = np.outer(garch_volatilities, garch_volatilities)
        covariance_matrix = correlation_matrix * volatility_matrix
        
        return RiskFactors(
            factor_exposures=pd.DataFrame(index=returns.columns),
            factor_returns=pd.DataFrame(),
            specific_risk=specific_risk,
            factor_covariance=covariance_matrix
        )

    def _estimate_garch_volatility(self, returns: pd.Series) -> float:
        alpha = 0.1
        beta = 0.85
        omega = 0.05
        
        returns_array = returns.values
        n = len(returns_array)
        
        variance = np.var(returns_array)
        
        for i in range(1, min(n, 50)):
            variance = omega + alpha * (returns_array[i-1] ** 2) + beta * variance
        
        return np.sqrt(variance)

    def calculate_portfolio_risk(
        self,
        weights: np.ndarray,
        risk_factors: RiskFactors
    ) -> Dict[str, float]:
        portfolio_variance = np.dot(weights, np.dot(risk_factors.factor_covariance.values, weights))
        portfolio_volatility = np.sqrt(portfolio_variance)
        
        return {
            'total_risk': portfolio_volatility,
            'factor_risk': 0.0,
            'specific_risk': portfolio_volatility
        }


class MultiFactorRiskModel(RiskModel):
    def __init__(
        self,
        style_factors: List[str] = None,
        industry_factors: List[str] = None,
        country_factors: List[str] = None
    ):
        self.style_factors = style_factors or ['Size', 'Value', 'Momentum', 'Quality', 'Volatility']
        self.industry_factors = industry_factors or []
        self.country_factors = country_factors or []

    def estimate_risk_model(
        self,
        returns: pd.DataFrame,
        factor_data: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> RiskFactors:
        if factor_data is None:
            return self._estimate_statistical_factors(returns)
        else:
            return self._estimate_fundamental_factors(returns, factor_data)

    def _estimate_statistical_factors(self, returns: pd.DataFrame) -> RiskFactors:
        n_factors = min(10, len(returns.columns) // 3)
        
        pca = PCA(n_components=n_factors)
        factor_exposures = pca.fit_transform(returns.T)
        
        factor_exposures_df = pd.DataFrame(
            factor_exposures,
            index=returns.columns,
            columns=[f'Factor_{i+1}' for i in range(n_factors)]
        )
        
        factor_returns = returns @ factor_exposures_df
        factor_covariance = factor_returns.cov()
        
        residuals = returns - (factor_returns @ factor_exposures_df.T)
        specific_risk = residuals.std()
        
        return RiskFactors(
            factor_exposures=factor_exposures_df,
            factor_returns=factor_returns,
            specific_risk=specific_risk,
            factor_covariance=factor_covariance
        )

    def _estimate_fundamental_factors(
        self,
        returns: pd.DataFrame,
        factor_data: pd.DataFrame
    ) -> RiskFactors:
        all_factors = self.style_factors + self.industry_factors + self.country_factors
        available_factors = [f for f in all_factors if f in factor_data.columns]
        
        if not available_factors:
            return self._estimate_statistical_factors(returns)
        
        factor_exposures_df = factor_data[available_factors].loc[returns.columns]
        
        factor_returns_list = []
        specific_risks = []
        
        for date in returns.index:
            cross_section_returns = returns.loc[date].dropna()
            cross_section_factors = factor_exposures_df.loc[cross_section_returns.index]
            
            if len(cross_section_returns) < len(available_factors):
                continue
            
            try:
                factor_returns = np.linalg.lstsq(
                    cross_section_factors.values,
                    cross_section_returns.values,
                    rcond=None
                )[0]
                factor_returns_list.append(factor_returns)
            except np.linalg.LinAlgError:
                continue
        
        if not factor_returns_list:
            return self._estimate_statistical_factors(returns)
        
        factor_returns_df = pd.DataFrame(
            factor_returns_list,
            columns=available_factors,
            index=returns.index[:len(factor_returns_list)]
        )
        
        factor_covariance = factor_returns_df.cov()
        
        predicted_returns = factor_exposures_df @ factor_returns_df.T
        residuals = returns.T - predicted_returns
        specific_risk = residuals.std(axis=1)
        
        return RiskFactors(
            factor_exposures=factor_exposures_df,
            factor_returns=factor_returns_df,
            specific_risk=specific_risk,
            factor_covariance=factor_covariance
        )

    def calculate_portfolio_risk(
        self,
        weights: np.ndarray,
        risk_factors: RiskFactors
    ) -> Dict[str, float]:
        portfolio_factor_exposure = risk_factors.factor_exposures.T @ weights
        
        factor_risk_contribution = np.dot(
            portfolio_factor_exposure,
            np.dot(risk_factors.factor_covariance.values, portfolio_factor_exposure)
        )
        
        specific_risk_contribution = np.sum(
            (weights ** 2) * (risk_factors.specific_risk.values ** 2)
        )
        
        total_risk = np.sqrt(factor_risk_contribution + specific_risk_contribution)
        
        factor_contributions = {}
        for i, factor in enumerate(risk_factors.factor_exposures.columns):
            factor_exposure = portfolio_factor_exposure[i]
            factor_var = risk_factors.factor_covariance.iloc[i, i]
            factor_contributions[factor] = abs(factor_exposure) * np.sqrt(factor_var)
        
        return {
            'total_risk': total_risk,
            'factor_risk': np.sqrt(factor_risk_contribution),
            'specific_risk': np.sqrt(specific_risk_contribution),
            'factor_contributions': factor_contributions
        }


class RiskModelEngine:
    def __init__(self):
        self.models = {
            'historical': HistoricalCovarianceModel(),
            'factor': FactorRiskModel(),
            'fama_french': FamaFrenchRiskModel(),
            'garch': GARCHRiskModel(),
            'multi_factor': MultiFactorRiskModel()
        }

    def estimate_risk(
        self,
        method: str,
        returns: pd.DataFrame,
        **kwargs
    ) -> RiskFactors:
        if method not in self.models:
            raise ValueError(f"Unknown risk model method: {method}")
        
        return self.models[method].estimate_risk_model(returns, **kwargs)

    def calculate_portfolio_risk(
        self,
        method: str,
        weights: np.ndarray,
        risk_factors: RiskFactors
    ) -> Dict[str, float]:
        if method not in self.models:
            raise ValueError(f"Unknown risk model method: {method}")
        
        return self.models[method].calculate_portfolio_risk(weights, risk_factors)