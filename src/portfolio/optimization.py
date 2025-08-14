from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
from scipy.optimize import minimize, Bounds, LinearConstraint
from scipy.linalg import inv, pinv
import warnings
warnings.filterwarnings('ignore')


@dataclass
class OptimizationConstraints:
    min_weight: float = 0.0
    max_weight: float = 1.0
    max_turnover: Optional[float] = None
    target_volatility: Optional[float] = None
    sector_constraints: Optional[Dict[str, Tuple[float, float]]] = None
    long_only: bool = True


@dataclass
class OptimizationResult:
    weights: np.ndarray
    expected_return: float
    volatility: float
    sharpe_ratio: float
    objective_value: float
    success: bool
    message: str
    asset_names: List[str]


class PortfolioOptimizer(ABC):
    @abstractmethod
    def optimize(
        self,
        expected_returns: np.ndarray,
        covariance_matrix: np.ndarray,
        asset_names: List[str],
        constraints: OptimizationConstraints
    ) -> OptimizationResult:
        pass


class ModernPortfolioTheoryOptimizer(PortfolioOptimizer):
    def __init__(self, risk_aversion: float = 1.0):
        self.risk_aversion = risk_aversion

    def optimize(
        self,
        expected_returns: np.ndarray,
        covariance_matrix: np.ndarray,
        asset_names: List[str],
        constraints: OptimizationConstraints
    ) -> OptimizationResult:
        n_assets = len(expected_returns)
        
        def objective(weights):
            portfolio_return = np.dot(weights, expected_returns)
            portfolio_variance = np.dot(weights, np.dot(covariance_matrix, weights))
            return -(portfolio_return - 0.5 * self.risk_aversion * portfolio_variance)
        
        bounds = Bounds(
            lb=np.full(n_assets, constraints.min_weight),
            ub=np.full(n_assets, constraints.max_weight)
        )
        
        weight_constraint = LinearConstraint(
            A=np.ones((1, n_assets)),
            lb=1.0,
            ub=1.0
        )
        
        x0 = np.full(n_assets, 1.0 / n_assets)
        
        result = minimize(
            objective,
            x0,
            method='SLSQP',
            bounds=bounds,
            constraints=weight_constraint,
            options={'ftol': 1e-9, 'disp': False}
        )
        
        if result.success:
            weights = result.x
            portfolio_return = np.dot(weights, expected_returns)
            portfolio_variance = np.dot(weights, np.dot(covariance_matrix, weights))
            portfolio_volatility = np.sqrt(portfolio_variance)
            sharpe_ratio = portfolio_return / portfolio_volatility if portfolio_volatility > 0 else 0
            
            return OptimizationResult(
                weights=weights,
                expected_return=portfolio_return,
                volatility=portfolio_volatility,
                sharpe_ratio=sharpe_ratio,
                objective_value=-result.fun,
                success=True,
                message="Optimization successful",
                asset_names=asset_names
            )
        else:
            return OptimizationResult(
                weights=np.full(n_assets, 1.0 / n_assets),
                expected_return=0.0,
                volatility=0.0,
                sharpe_ratio=0.0,
                objective_value=0.0,
                success=False,
                message=result.message,
                asset_names=asset_names
            )


class BlackLittermanOptimizer(PortfolioOptimizer):
    def __init__(
        self,
        risk_aversion: float = 3.0,
        tau: float = 0.025,
        confidence: float = 0.5
    ):
        self.risk_aversion = risk_aversion
        self.tau = tau
        self.confidence = confidence

    def optimize(
        self,
        expected_returns: np.ndarray,
        covariance_matrix: np.ndarray,
        asset_names: List[str],
        constraints: OptimizationConstraints,
        market_caps: Optional[np.ndarray] = None,
        views: Optional[Dict[str, float]] = None,
        view_uncertainties: Optional[Dict[str, float]] = None
    ) -> OptimizationResult:
        n_assets = len(expected_returns)
        
        if market_caps is None:
            market_caps = np.ones(n_assets)
        
        market_weights = market_caps / np.sum(market_caps)
        
        implied_returns = self.risk_aversion * np.dot(covariance_matrix, market_weights)
        
        if views is None or len(views) == 0:
            mu_bl = implied_returns
            sigma_bl = covariance_matrix
        else:
            mu_bl, sigma_bl = self._apply_black_litterman_views(
                implied_returns,
                covariance_matrix,
                views,
                view_uncertainties,
                asset_names
            )
        
        optimizer = ModernPortfolioTheoryOptimizer(self.risk_aversion)
        return optimizer.optimize(mu_bl, sigma_bl, asset_names, constraints)

    def _apply_black_litterman_views(
        self,
        implied_returns: np.ndarray,
        covariance_matrix: np.ndarray,
        views: Dict[str, float],
        view_uncertainties: Optional[Dict[str, float]],
        asset_names: List[str]
    ) -> Tuple[np.ndarray, np.ndarray]:
        n_assets = len(implied_returns)
        n_views = len(views)
        
        P = np.zeros((n_views, n_assets))
        Q = np.zeros(n_views)
        
        for i, (asset, view_return) in enumerate(views.items()):
            if asset in asset_names:
                asset_idx = asset_names.index(asset)
                P[i, asset_idx] = 1.0
                Q[i] = view_return
        
        if view_uncertainties is None:
            Omega = np.eye(n_views) * np.diag(np.dot(P, np.dot(covariance_matrix, P.T))) * self.confidence
        else:
            Omega = np.zeros((n_views, n_views))
            for i, (asset, uncertainty) in enumerate(view_uncertainties.items()):
                if i < n_views:
                    Omega[i, i] = uncertainty ** 2
        
        try:
            tau_sigma = self.tau * covariance_matrix
            
            M1 = inv(tau_sigma)
            M2 = np.dot(P.T, np.dot(inv(Omega), P))
            M3 = np.dot(inv(tau_sigma), implied_returns)
            M4 = np.dot(P.T, np.dot(inv(Omega), Q))
            
            mu_bl = np.dot(inv(M1 + M2), M3 + M4)
            sigma_bl = inv(M1 + M2)
            
        except np.linalg.LinAlgError:
            tau_sigma = self.tau * covariance_matrix
            
            M1_pinv = pinv(tau_sigma)
            M2 = np.dot(P.T, np.dot(pinv(Omega), P))
            M3 = np.dot(M1_pinv, implied_returns)
            M4 = np.dot(P.T, np.dot(pinv(Omega), Q))
            
            mu_bl = np.dot(pinv(M1_pinv + M2), M3 + M4)
            sigma_bl = pinv(M1_pinv + M2)
        
        return mu_bl, sigma_bl


class RiskParityOptimizer(PortfolioOptimizer):
    def __init__(self, max_iterations: int = 1000, tolerance: float = 1e-8):
        self.max_iterations = max_iterations
        self.tolerance = tolerance

    def optimize(
        self,
        expected_returns: np.ndarray,
        covariance_matrix: np.ndarray,
        asset_names: List[str],
        constraints: OptimizationConstraints,
        target_risk_contributions: Optional[np.ndarray] = None
    ) -> OptimizationResult:
        n_assets = len(expected_returns)
        
        if target_risk_contributions is None:
            target_risk_contributions = np.ones(n_assets) / n_assets
        
        def risk_contribution_objective(weights):
            portfolio_variance = np.dot(weights, np.dot(covariance_matrix, weights))
            marginal_contrib = np.dot(covariance_matrix, weights)
            contrib = weights * marginal_contrib / portfolio_variance
            
            diff = contrib - target_risk_contributions
            return np.sum(diff ** 2)
        
        bounds = Bounds(
            lb=np.full(n_assets, max(constraints.min_weight, 1e-6)),
            ub=np.full(n_assets, constraints.max_weight)
        )
        
        weight_constraint = LinearConstraint(
            A=np.ones((1, n_assets)),
            lb=1.0,
            ub=1.0
        )
        
        x0 = np.full(n_assets, 1.0 / n_assets)
        
        result = minimize(
            risk_contribution_objective,
            x0,
            method='SLSQP',
            bounds=bounds,
            constraints=weight_constraint,
            options={'ftol': self.tolerance, 'maxiter': self.max_iterations}
        )
        
        if result.success:
            weights = result.x
            portfolio_return = np.dot(weights, expected_returns)
            portfolio_variance = np.dot(weights, np.dot(covariance_matrix, weights))
            portfolio_volatility = np.sqrt(portfolio_variance)
            sharpe_ratio = portfolio_return / portfolio_volatility if portfolio_volatility > 0 else 0
            
            return OptimizationResult(
                weights=weights,
                expected_return=portfolio_return,
                volatility=portfolio_volatility,
                sharpe_ratio=sharpe_ratio,
                objective_value=result.fun,
                success=True,
                message="Risk parity optimization successful",
                asset_names=asset_names
            )
        else:
            return OptimizationResult(
                weights=np.full(n_assets, 1.0 / n_assets),
                expected_return=0.0,
                volatility=0.0,
                sharpe_ratio=0.0,
                objective_value=float('inf'),
                success=False,
                message=result.message,
                asset_names=asset_names
            )


class HierarchicalRiskParityOptimizer(PortfolioOptimizer):
    def __init__(self, linkage_method: str = 'single'):
        self.linkage_method = linkage_method

    def optimize(
        self,
        expected_returns: np.ndarray,
        covariance_matrix: np.ndarray,
        asset_names: List[str],
        constraints: OptimizationConstraints
    ) -> OptimizationResult:
        try:
            from scipy.cluster.hierarchy import linkage, dendrogram
            from scipy.spatial.distance import squareform
        except ImportError:
            raise ImportError("scipy is required for Hierarchical Risk Parity")
        
        n_assets = len(expected_returns)
        
        correlation_matrix = self._cov_to_corr(covariance_matrix)
        distance_matrix = np.sqrt(0.5 * (1 - correlation_matrix))
        
        condensed_distances = squareform(distance_matrix, checks=False)
        
        linkage_matrix = linkage(condensed_distances, method=self.linkage_method)
        
        sorted_indices = self._get_quasi_diag(linkage_matrix)
        
        hrp_weights = self._get_hrp_weights(covariance_matrix, sorted_indices)
        
        weights = np.zeros(n_assets)
        for i, idx in enumerate(sorted_indices):
            weights[idx] = hrp_weights[i]
        
        portfolio_return = np.dot(weights, expected_returns)
        portfolio_variance = np.dot(weights, np.dot(covariance_matrix, weights))
        portfolio_volatility = np.sqrt(portfolio_variance)
        sharpe_ratio = portfolio_return / portfolio_volatility if portfolio_volatility > 0 else 0
        
        return OptimizationResult(
            weights=weights,
            expected_return=portfolio_return,
            volatility=portfolio_volatility,
            sharpe_ratio=sharpe_ratio,
            objective_value=0.0,
            success=True,
            message="HRP optimization successful",
            asset_names=asset_names
        )

    def _cov_to_corr(self, covariance_matrix: np.ndarray) -> np.ndarray:
        std_devs = np.sqrt(np.diag(covariance_matrix))
        correlation_matrix = covariance_matrix / np.outer(std_devs, std_devs)
        return correlation_matrix

    def _get_quasi_diag(self, linkage_matrix: np.ndarray) -> List[int]:
        link = linkage_matrix.astype(int)
        sorted_indices = pd.Series([link[-1, 0], link[-1, 1]])
        
        num_items = link[-1, 3]
        
        while sorted_indices.max() >= num_items:
            sorted_indices.index = range(0, sorted_indices.shape[0] * 2, 2)
            df0 = sorted_indices[sorted_indices >= num_items]
            i = df0.index
            j = df0.values - num_items
            sorted_indices[i] = link[j, 0]
            df0 = pd.Series(link[j, 1], index=i + 1)
            sorted_indices = pd.concat([sorted_indices, df0])
            sorted_indices = sorted_indices.sort_index()
            sorted_indices.index = range(sorted_indices.shape[0])
        
        return sorted_indices.tolist()

    def _get_hrp_weights(self, covariance_matrix: np.ndarray, sorted_indices: List[int]) -> np.ndarray:
        w = pd.Series(1, index=sorted_indices)
        clusters = [sorted_indices]
        
        while len(clusters) > 0:
            clusters = [cluster[start:end] for cluster in clusters
                       for start, end in ((0, len(cluster) // 2), (len(cluster) // 2, len(cluster)))
                       if len(cluster) > 1]
            
            for i in range(0, len(clusters), 2):
                cluster1 = clusters[i]
                cluster2 = clusters[i + 1] if i + 1 < len(clusters) else []
                
                if len(cluster2) == 0:
                    continue
                
                cov1 = covariance_matrix[np.ix_(cluster1, cluster1)]
                cov2 = covariance_matrix[np.ix_(cluster2, cluster2)]
                
                ivp1 = 1.0 / np.sqrt(np.dot(w[cluster1], np.dot(cov1, w[cluster1])))
                ivp2 = 1.0 / np.sqrt(np.dot(w[cluster2], np.dot(cov2, w[cluster2])))
                
                alpha = ivp1 / (ivp1 + ivp2)
                
                w[cluster1] *= alpha
                w[cluster2] *= (1 - alpha)
        
        return w.values


class PortfolioOptimizationEngine:
    def __init__(self):
        self.optimizers = {
            'mpt': ModernPortfolioTheoryOptimizer(),
            'black_litterman': BlackLittermanOptimizer(),
            'risk_parity': RiskParityOptimizer(),
            'hrp': HierarchicalRiskParityOptimizer()
        }

    def optimize_portfolio(
        self,
        method: str,
        expected_returns: np.ndarray,
        covariance_matrix: np.ndarray,
        asset_names: List[str],
        constraints: Optional[OptimizationConstraints] = None,
        **kwargs
    ) -> OptimizationResult:
        if method not in self.optimizers:
            raise ValueError(f"Unknown optimization method: {method}")
        
        if constraints is None:
            constraints = OptimizationConstraints()
        
        optimizer = self.optimizers[method]
        
        if method == 'black_litterman':
            return optimizer.optimize(
                expected_returns, covariance_matrix, asset_names, constraints, **kwargs
            )
        elif method == 'risk_parity':
            return optimizer.optimize(
                expected_returns, covariance_matrix, asset_names, constraints, **kwargs
            )
        else:
            return optimizer.optimize(expected_returns, covariance_matrix, asset_names, constraints)

    def calculate_efficient_frontier(
        self,
        expected_returns: np.ndarray,
        covariance_matrix: np.ndarray,
        asset_names: List[str],
        n_points: int = 50
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        min_variance_result = self._calculate_minimum_variance_portfolio(
            covariance_matrix, asset_names
        )
        max_return_result = self._calculate_maximum_return_portfolio(
            expected_returns, asset_names
        )
        
        min_return = min_variance_result.expected_return
        max_return = max_return_result.expected_return
        
        target_returns = np.linspace(min_return, max_return, n_points)
        efficient_returns = []
        efficient_volatilities = []
        efficient_weights = []
        
        for target_return in target_returns:
            result = self._calculate_minimum_variance_for_target_return(
                expected_returns, covariance_matrix, asset_names, target_return
            )
            if result.success:
                efficient_returns.append(result.expected_return)
                efficient_volatilities.append(result.volatility)
                efficient_weights.append(result.weights)
        
        return (
            np.array(efficient_returns),
            np.array(efficient_volatilities),
            np.array(efficient_weights)
        )

    def _calculate_minimum_variance_portfolio(
        self, covariance_matrix: np.ndarray, asset_names: List[str]
    ) -> OptimizationResult:
        n_assets = len(asset_names)
        
        def objective(weights):
            return np.dot(weights, np.dot(covariance_matrix, weights))
        
        bounds = Bounds(lb=np.zeros(n_assets), ub=np.ones(n_assets))
        constraint = LinearConstraint(A=np.ones((1, n_assets)), lb=1.0, ub=1.0)
        
        x0 = np.ones(n_assets) / n_assets
        result = minimize(objective, x0, method='SLSQP', bounds=bounds, constraints=constraint)
        
        if result.success:
            weights = result.x
            expected_return = 0.0
            volatility = np.sqrt(objective(weights))
            
            return OptimizationResult(
                weights=weights,
                expected_return=expected_return,
                volatility=volatility,
                sharpe_ratio=0.0,
                objective_value=result.fun,
                success=True,
                message="Minimum variance optimization successful",
                asset_names=asset_names
            )
        
        return OptimizationResult(
            weights=np.ones(n_assets) / n_assets,
            expected_return=0.0,
            volatility=0.0,
            sharpe_ratio=0.0,
            objective_value=0.0,
            success=False,
            message="Optimization failed",
            asset_names=asset_names
        )

    def _calculate_maximum_return_portfolio(
        self, expected_returns: np.ndarray, asset_names: List[str]
    ) -> OptimizationResult:
        max_return_idx = np.argmax(expected_returns)
        weights = np.zeros(len(expected_returns))
        weights[max_return_idx] = 1.0
        
        return OptimizationResult(
            weights=weights,
            expected_return=expected_returns[max_return_idx],
            volatility=0.0,
            sharpe_ratio=0.0,
            objective_value=0.0,
            success=True,
            message="Maximum return portfolio",
            asset_names=asset_names
        )

    def _calculate_minimum_variance_for_target_return(
        self,
        expected_returns: np.ndarray,
        covariance_matrix: np.ndarray,
        asset_names: List[str],
        target_return: float
    ) -> OptimizationResult:
        n_assets = len(expected_returns)
        
        def objective(weights):
            return np.dot(weights, np.dot(covariance_matrix, weights))
        
        bounds = Bounds(lb=np.zeros(n_assets), ub=np.ones(n_assets))
        
        constraints = [
            LinearConstraint(A=np.ones((1, n_assets)), lb=1.0, ub=1.0),
            LinearConstraint(A=expected_returns.reshape(1, -1), lb=target_return, ub=target_return)
        ]
        
        x0 = np.ones(n_assets) / n_assets
        result = minimize(objective, x0, method='SLSQP', bounds=bounds, constraints=constraints)
        
        if result.success:
            weights = result.x
            portfolio_return = np.dot(weights, expected_returns)
            volatility = np.sqrt(objective(weights))
            sharpe_ratio = portfolio_return / volatility if volatility > 0 else 0
            
            return OptimizationResult(
                weights=weights,
                expected_return=portfolio_return,
                volatility=volatility,
                sharpe_ratio=sharpe_ratio,
                objective_value=result.fun,
                success=True,
                message="Target return optimization successful",
                asset_names=asset_names
            )
        
        return OptimizationResult(
            weights=np.ones(n_assets) / n_assets,
            expected_return=0.0,
            volatility=0.0,
            sharpe_ratio=0.0,
            objective_value=0.0,
            success=False,
            message="Optimization failed",
            asset_names=asset_names
        )


def create_portfolio_optimizer(method: str = "mpt") -> PortfolioOptimizationEngine:
    return PortfolioOptimizationEngine()