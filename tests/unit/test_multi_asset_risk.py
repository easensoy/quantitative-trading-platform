import pytest
from datetime import datetime, timedelta
import numpy as np

from src.core.models import (
    Portfolio, Position, AssetType, FixedIncomeInstrument, CommodityInstrument, Order, OrderSide, OrderType
)
from src.portfolio.multi_asset_risk import MultiAssetRiskManager, RiskLimit, RiskMetricType, ScenarioAnalyzer


class TestMultiAssetRiskManager:
    def test_risk_manager_initialization(self):
        risk_manager = MultiAssetRiskManager()
        
        assert len(risk_manager.risk_limits) == 0
        assert len(risk_manager.position_limits) == 0
        assert risk_manager.correlation_matrix is None
    
    def test_add_risk_limit(self):
        risk_manager = MultiAssetRiskManager()
        
        var_limit = RiskLimit(
            metric_type=RiskMetricType.VAR_95,
            limit_value=1000000.0
        )
        
        risk_manager.add_risk_limit(var_limit)
        
        assert len(risk_manager.risk_limits) == 1
        assert risk_manager.risk_limits[0].metric_type == RiskMetricType.VAR_95
    
    def test_position_limits_validation(self):
        risk_manager = MultiAssetRiskManager()
        risk_manager.position_limits["AAPL"] = 1000
        
        portfolio = Portfolio(id="test", name="Test Portfolio")
        
        existing_position = Position(
            instrument=FixedIncomeInstrument(
                symbol="AAPL",
                asset_type=AssetType.EQUITY,
                exchange="NASDAQ",
                currency="USD",
                maturity_date=datetime.utcnow() + timedelta(days=365),
                coupon_rate=0.0
            ),
            quantity=500,
            avg_price=150.0
        )
        portfolio.add_position(existing_position)
        
        valid_order = Order(
            id="test_order_1",
            instrument=existing_position.instrument,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=400,
            price=150.0
        )
        
        invalid_order = Order(
            id="test_order_2",
            instrument=existing_position.instrument,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=600,
            price=150.0
        )
        
        assert risk_manager._check_position_limits(valid_order, portfolio) == True
        assert risk_manager._check_position_limits(invalid_order, portfolio) == False
    
    def test_concentration_limits_validation(self):
        risk_manager = MultiAssetRiskManager()
        
        portfolio = Portfolio(id="test", name="Test Portfolio", cash=1000000.0)
        
        large_position = Position(
            instrument=FixedIncomeInstrument(
                symbol="LARGE_BOND",
                asset_type=AssetType.GOVERNMENT_BOND,
                exchange="Treasury",
                currency="USD",
                maturity_date=datetime.utcnow() + timedelta(days=365*10),
                coupon_rate=0.04
            ),
            quantity=1000000,
            avg_price=100.0
        )
        portfolio.add_position(large_position)
        
        new_order = Order(
            id="concentration_test",
            instrument=FixedIncomeInstrument(
                symbol="NEW_BOND",
                asset_type=AssetType.CORPORATE_BOND,
                exchange="NYSE",
                currency="USD",
                maturity_date=datetime.utcnow() + timedelta(days=365*5),
                coupon_rate=0.05
            ),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=50000,
            price=100.0
        )
        
        result = risk_manager._check_concentration_limits(new_order, portfolio)
        assert isinstance(result, bool)
    
    def test_var_calculation(self):
        risk_manager = MultiAssetRiskManager()
        
        portfolio = Portfolio(id="test", name="Test Portfolio")
        
        bond_position = Position(
            instrument=FixedIncomeInstrument(
                symbol="US10Y",
                asset_type=AssetType.GOVERNMENT_BOND,
                exchange="Treasury",
                currency="USD",
                maturity_date=datetime.utcnow() + timedelta(days=365*10),
                coupon_rate=0.04
            ),
            quantity=1000000,
            avg_price=100.0
        )
        
        commodity_position = Position(
            instrument=CommodityInstrument(
                symbol="CL",
                asset_type=AssetType.COMMODITY_FUTURE,
                exchange="NYMEX",
                currency="USD",
                contract_month="DEC24",
                delivery_date=datetime(2024, 12, 20),
                grade="WTI",
                delivery_location="Cushing",
                lot_size_unit="barrels"
            ),
            quantity=1000,
            avg_price=75.0
        )
        
        portfolio.add_position(bond_position)
        portfolio.add_position(commodity_position)
        
        var_95 = risk_manager._calculate_portfolio_var(portfolio, confidence_level=0.95)
        
        assert var_95 >= 0
        assert isinstance(var_95, float)
    
    def test_concentration_metrics_calculation(self):
        risk_manager = MultiAssetRiskManager()
        
        portfolio = Portfolio(id="test", name="Test Portfolio")
        
        positions = []
        for i in range(5):
            position = Position(
                instrument=FixedIncomeInstrument(
                    symbol=f"BOND_{i}",
                    asset_type=AssetType.GOVERNMENT_BOND,
                    exchange="Treasury",
                    currency="USD",
                    maturity_date=datetime.utcnow() + timedelta(days=365*5),
                    coupon_rate=0.04
                ),
                quantity=100000 * (i + 1),
                avg_price=100.0
            )
            portfolio.add_position(position)
            positions.append(position)
        
        metrics = risk_manager._calculate_concentration_metrics(portfolio)
        
        assert "max_position_concentration" in metrics
        assert "top_5_concentration" in metrics
        assert "herfindahl_index" in metrics
        
        assert 0 <= metrics["max_position_concentration"] <= 1
        assert 0 <= metrics["herfindahl_index"] <= 1
    
    def test_fixed_income_risk_metrics(self):
        risk_manager = MultiAssetRiskManager()
        
        fi_positions = []
        for i in range(3):
            position = Position(
                instrument=FixedIncomeInstrument(
                    symbol=f"BOND_{i}",
                    asset_type=AssetType.GOVERNMENT_BOND,
                    exchange="Treasury",
                    currency="USD",
                    maturity_date=datetime.utcnow() + timedelta(days=365*(i+2)),
                    coupon_rate=0.04,
                    duration=float(i+2),
                    convexity=float((i+2)*5)
                ),
                quantity=1000000,
                avg_price=100.0
            )
            fi_positions.append(position)
        
        metrics = risk_manager._calculate_fixed_income_risk_metrics(fi_positions)
        
        assert "fixed_income_duration" in metrics
        assert "fixed_income_convexity" in metrics
        assert "fixed_income_dv01" in metrics
        
        assert metrics["fixed_income_duration"] > 0
        assert metrics["fixed_income_dv01"] > 0
    
    def test_commodity_risk_metrics(self):
        risk_manager = MultiAssetRiskManager()
        
        commodity_positions = []
        
        symbols = [("CL", True, False, False), ("GC", False, True, False), ("C", False, False, True)]
        
        for symbol, is_energy, is_metals, is_ag in symbols:
            position = Position(
                instrument=CommodityInstrument(
                    symbol=symbol,
                    asset_type=AssetType.COMMODITY_FUTURE,
                    exchange="TEST",
                    currency="USD",
                    contract_month="DEC24",
                    delivery_date=datetime(2024, 12, 20),
                    grade="Test",
                    delivery_location="Test",
                    lot_size_unit="units"
                ),
                quantity=1000,
                avg_price=100.0
            )
            commodity_positions.append(position)
        
        metrics = risk_manager._calculate_commodity_risk_metrics(commodity_positions)
        
        assert "commodity_energy_exposure" in metrics
        assert "commodity_metals_exposure" in metrics
        assert "commodity_agriculture_exposure" in metrics
        
        assert 0 <= metrics["commodity_energy_exposure"] <= 1
        assert 0 <= metrics["commodity_metals_exposure"] <= 1
        assert 0 <= metrics["commodity_agriculture_exposure"] <= 1
    
    def test_correlation_estimation(self):
        risk_manager = MultiAssetRiskManager()
        
        equity_pos = {'symbol': 'AAPL', 'asset_type': AssetType.EQUITY}
        bond_pos = {'symbol': 'US10Y', 'asset_type': AssetType.GOVERNMENT_BOND}
        commodity_pos = {'symbol': 'CL', 'asset_type': AssetType.COMMODITY}
        
        corr_equity_bond = risk_manager._get_correlation(equity_pos, bond_pos)
        corr_equity_commodity = risk_manager._get_correlation(equity_pos, commodity_pos)
        corr_bond_commodity = risk_manager._get_correlation(bond_pos, commodity_pos)
        
        assert -1 <= corr_equity_bond <= 1
        assert -1 <= corr_equity_commodity <= 1
        assert -1 <= corr_bond_commodity <= 1
    
    def test_portfolio_volatility_calculation(self):
        risk_manager = MultiAssetRiskManager()
        
        positions_data = [
            {'symbol': 'AAPL', 'value': 1000000, 'volatility': 0.20, 'asset_type': AssetType.EQUITY},
            {'symbol': 'US10Y', 'value': 2000000, 'volatility': 0.05, 'asset_type': AssetType.GOVERNMENT_BOND},
            {'symbol': 'CL', 'value': 500000, 'volatility': 0.30, 'asset_type': AssetType.COMMODITY}
        ]
        
        portfolio_vol = risk_manager._calculate_portfolio_volatility(positions_data)
        
        assert portfolio_vol > 0
        assert portfolio_vol < max(pos['volatility'] for pos in positions_data)
    
    def test_risk_limit_breach_detection(self):
        risk_manager = MultiAssetRiskManager()
        
        var_limit = RiskLimit(
            metric_type=RiskMetricType.VAR_95,
            limit_value=100000.0
        )
        risk_manager.add_risk_limit(var_limit)
        
        metrics = {"var_95": 150000.0}
        
        risk_manager._check_limit_breaches(metrics)
        
        assert var_limit.breach_count == 1
        assert var_limit.last_breach is not None
    
    def test_risk_report_generation(self):
        risk_manager = MultiAssetRiskManager()
        
        portfolio = Portfolio(id="test", name="Test Portfolio")
        
        position = Position(
            instrument=FixedIncomeInstrument(
                symbol="US10Y",
                asset_type=AssetType.GOVERNMENT_BOND,
                exchange="Treasury",
                currency="USD",
                maturity_date=datetime.utcnow() + timedelta(days=365*10),
                coupon_rate=0.04
            ),
            quantity=1000000,
            avg_price=100.0
        )
        portfolio.add_position(position)
        
        report = risk_manager.get_risk_report(portfolio)
        
        assert "timestamp" in report
        assert "portfolio_value" in report
        assert "risk_metrics" in report
        assert "asset_allocation" in report
        assert isinstance(report["risk_metrics"], dict)


class TestScenarioAnalyzer:
    def test_scenario_analyzer_initialization(self):
        risk_manager = MultiAssetRiskManager()
        scenario_analyzer = ScenarioAnalyzer(risk_manager)
        
        assert scenario_analyzer.risk_manager is risk_manager
    
    def test_stress_test_execution(self):
        risk_manager = MultiAssetRiskManager()
        scenario_analyzer = ScenarioAnalyzer(risk_manager)
        
        portfolio = Portfolio(id="test", name="Test Portfolio")
        
        position = Position(
            instrument=FixedIncomeInstrument(
                symbol="US10Y",
                asset_type=AssetType.GOVERNMENT_BOND,
                exchange="Treasury",
                currency="USD",
                maturity_date=datetime.utcnow() + timedelta(days=365*10),
                coupon_rate=0.04
            ),
            quantity=1000000,
            avg_price=100.0
        )
        portfolio.add_position(position)
        
        risk_manager.volatility_estimates["US10Y"] = 0.05
        
        scenario = {"US10Y": 0.5}
        
        stress_result = scenario_analyzer.run_stress_test(portfolio, scenario)
        
        assert "scenario" in stress_result
        assert "base_metrics" in stress_result
        assert "stressed_metrics" in stress_result
        assert "impact" in stress_result
        
        assert stress_result["scenario"] == scenario
    
    def test_volatility_estimate_by_asset_type(self):
        risk_manager = MultiAssetRiskManager()
        
        equity_vol = risk_manager._estimate_volatility_by_asset_type(AssetType.EQUITY)
        bond_vol = risk_manager._estimate_volatility_by_asset_type(AssetType.GOVERNMENT_BOND)
        commodity_vol = risk_manager._estimate_volatility_by_asset_type(AssetType.COMMODITY)
        
        assert equity_vol > bond_vol
        assert commodity_vol > bond_vol
        assert commodity_vol > equity_vol
    
    def test_z_score_calculation(self):
        risk_manager = MultiAssetRiskManager()
        
        z_95 = risk_manager._get_z_score(0.95)
        z_99 = risk_manager._get_z_score(0.99)
        
        assert z_99 > z_95
        assert z_95 > 1.0
        assert z_99 > 2.0


class TestRiskLimitAndMetric:
    def test_risk_limit_creation(self):
        limit = RiskLimit(
            metric_type=RiskMetricType.VAR_95,
            limit_value=1000000.0,
            asset_type=AssetType.EQUITY,
            strategy_id="momentum_strategy"
        )
        
        assert limit.metric_type == RiskMetricType.VAR_95
        assert limit.limit_value == 1000000.0
        assert limit.asset_type == AssetType.EQUITY
        assert limit.breach_count == 0
    
    def test_risk_metric_types(self):
        metric_types = list(RiskMetricType)
        
        expected_types = [
            RiskMetricType.VAR_95,
            RiskMetricType.VAR_99,
            RiskMetricType.EXPECTED_SHORTFALL,
            RiskMetricType.MAXIMUM_DRAWDOWN,
            RiskMetricType.VOLATILITY,
            RiskMetricType.BETA,
            RiskMetricType.CORRELATION,
            RiskMetricType.CONCENTRATION
        ]
        
        assert len(metric_types) == len(expected_types)
        
        for expected_type in expected_types:
            assert expected_type in metric_types