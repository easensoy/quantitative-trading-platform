import pytest
from datetime import datetime, timedelta
import numpy as np

from src.core.models import (
    AssetType, FixedIncomeInstrument, CommodityInstrument, YieldCurve, YieldCurvePoint,
    CommodityFuturesPrice, FixedIncomePricer
)


class TestFixedIncomeInstrument:
    def test_government_bond_creation(self):
        bond = FixedIncomeInstrument(
            symbol="US10Y",
            asset_type=AssetType.GOVERNMENT_BOND,
            exchange="Treasury",
            currency="USD",
            maturity_date=datetime(2034, 5, 15),
            coupon_rate=0.045,
            face_value=1000.0,
            payment_frequency=2
        )
        
        assert bond.symbol == "US10Y"
        assert bond.is_government == True
        assert bond.coupon_rate == 0.045
        assert bond.time_to_maturity > 0
    
    def test_corporate_bond_creation(self):
        bond = FixedIncomeInstrument(
            symbol="AAPL4.5_2030",
            asset_type=AssetType.CORPORATE_BOND,
            exchange="NYSE",
            currency="USD",
            maturity_date=datetime(2030, 12, 1),
            coupon_rate=0.045,
            credit_rating="AA+",
            face_value=1000.0
        )
        
        assert bond.symbol == "AAPL4.5_2030"
        assert bond.is_government == False
        assert bond.credit_rating == "AA+"
    
    def test_time_to_maturity_calculation(self):
        future_date = datetime.utcnow() + timedelta(days=365)
        bond = FixedIncomeInstrument(
            symbol="TEST",
            asset_type=AssetType.BOND,
            exchange="TEST",
            currency="USD",
            maturity_date=future_date,
            coupon_rate=0.05
        )
        
        assert abs(bond.time_to_maturity - 1.0) < 0.1


class TestCommodityInstrument:
    def test_energy_commodity_creation(self):
        oil_future = CommodityInstrument(
            symbol="CL",
            asset_type=AssetType.COMMODITY_FUTURE,
            exchange="NYMEX",
            currency="USD",
            contract_month="DEC24",
            delivery_date=datetime(2024, 12, 20),
            grade="WTI",
            delivery_location="Cushing, OK",
            lot_size_unit="barrels",
            storage_cost_rate=0.02,
            convenience_yield=0.03
        )
        
        assert oil_future.symbol == "CL"
        assert oil_future.is_energy == True
        assert oil_future.is_metals == False
        assert oil_future.is_agriculture == False
    
    def test_metals_commodity_creation(self):
        gold_future = CommodityInstrument(
            symbol="GC",
            asset_type=AssetType.COMMODITY_FUTURE,
            exchange="COMEX",
            currency="USD",
            contract_month="FEB25",
            delivery_date=datetime(2025, 2, 28),
            grade="Good Delivery",
            delivery_location="COMEX Warehouse",
            lot_size_unit="troy_ounces"
        )
        
        assert gold_future.is_metals == True
        assert gold_future.is_energy == False
    
    def test_agriculture_commodity_creation(self):
        corn_future = CommodityInstrument(
            symbol="C",
            asset_type=AssetType.COMMODITY_FUTURE,
            exchange="CBOT",
            currency="USD",
            contract_month="MAR25",
            delivery_date=datetime(2025, 3, 15),
            grade="No. 2 Yellow",
            delivery_location="Chicago",
            lot_size_unit="bushels"
        )
        
        assert corn_future.is_agriculture == True
        assert corn_future.is_energy == False


class TestYieldCurve:
    def test_yield_curve_creation(self):
        points = [
            YieldCurvePoint(maturity=0.25, yield_rate=0.025),
            YieldCurvePoint(maturity=1.0, yield_rate=0.035),
            YieldCurvePoint(maturity=5.0, yield_rate=0.055),
            YieldCurvePoint(maturity=10.0, yield_rate=0.060),
            YieldCurvePoint(maturity=30.0, yield_rate=0.068)
        ]
        
        curve = YieldCurve(points, currency="USD")
        
        assert len(curve.points) == 5
        assert curve.currency == "USD"
        assert curve.points[0].maturity == 0.25
    
    def test_yield_interpolation(self):
        points = [
            YieldCurvePoint(maturity=1.0, yield_rate=0.030),
            YieldCurvePoint(maturity=5.0, yield_rate=0.050),
            YieldCurvePoint(maturity=10.0, yield_rate=0.060)
        ]
        
        curve = YieldCurve(points)
        
        interpolated_3y = curve.interpolate_yield(3.0)
        
        assert 0.040 <= interpolated_3y <= 0.055
    
    def test_forward_rate_calculation(self):
        points = [
            YieldCurvePoint(maturity=1.0, yield_rate=0.030),
            YieldCurvePoint(maturity=2.0, yield_rate=0.035),
            YieldCurvePoint(maturity=5.0, yield_rate=0.050)
        ]
        
        curve = YieldCurve(points)
        
        forward_rate = curve.get_forward_rate(1.0, 2.0)
        
        assert forward_rate > 0


class TestCommodityFuturesPrice:
    def test_futures_price_creation(self):
        futures_price = CommodityFuturesPrice(
            spot_price=100.0,
            futures_price=102.0,
            time_to_maturity=0.25,
            risk_free_rate=0.05,
            storage_cost=0.02,
            convenience_yield=0.01
        )
        
        assert futures_price.spot_price == 100.0
        assert futures_price.futures_price == 102.0
        assert futures_price.basis == 2.0
    
    def test_cost_of_carry_calculation(self):
        futures_price = CommodityFuturesPrice(
            spot_price=100.0,
            futures_price=102.0,
            time_to_maturity=0.25,
            risk_free_rate=0.05,
            storage_cost=0.02,
            convenience_yield=0.01
        )
        
        cost_of_carry = futures_price.cost_of_carry
        expected_carry = 0.05 + 0.02 - 0.01
        
        assert abs(cost_of_carry - expected_carry) < 0.001
    
    def test_theoretical_price_calculation(self):
        futures_price = CommodityFuturesPrice(
            spot_price=100.0,
            futures_price=102.0,
            time_to_maturity=0.25,
            risk_free_rate=0.05,
            storage_cost=0.02,
            convenience_yield=0.01
        )
        
        theoretical_price = futures_price.theoretical_price
        
        assert theoretical_price > 100.0
    
    def test_contango_backwardation_detection(self):
        contango_price = CommodityFuturesPrice(
            spot_price=100.0,
            futures_price=105.0,
            time_to_maturity=0.25,
            risk_free_rate=0.05
        )
        
        backwardation_price = CommodityFuturesPrice(
            spot_price=100.0,
            futures_price=95.0,
            time_to_maturity=0.25,
            risk_free_rate=0.05
        )
        
        assert contango_price.contango_backwardation == "contango"
        assert backwardation_price.contango_backwardation == "backwardation"


class TestFixedIncomePricer:
    def test_bond_price_calculation(self):
        bond = FixedIncomeInstrument(
            symbol="TEST",
            asset_type=AssetType.BOND,
            exchange="TEST",
            currency="USD",
            maturity_date=datetime.utcnow() + timedelta(days=365*5),
            coupon_rate=0.05,
            face_value=1000.0,
            payment_frequency=2
        )
        
        yield_rate = 0.04
        price = FixedIncomePricer.calculate_bond_price(bond, yield_rate)
        
        assert price > 1000.0
    
    def test_duration_calculation(self):
        bond = FixedIncomeInstrument(
            symbol="TEST",
            asset_type=AssetType.BOND,
            exchange="TEST",
            currency="USD",
            maturity_date=datetime.utcnow() + timedelta(days=365*5),
            coupon_rate=0.05,
            face_value=1000.0,
            payment_frequency=2
        )
        
        yield_rate = 0.05
        duration = FixedIncomePricer.calculate_duration(bond, yield_rate)
        
        assert 4.0 < duration < 5.0
    
    def test_convexity_calculation(self):
        bond = FixedIncomeInstrument(
            symbol="TEST",
            asset_type=AssetType.BOND,
            exchange="TEST",
            currency="USD",
            maturity_date=datetime.utcnow() + timedelta(days=365*5),
            coupon_rate=0.05,
            face_value=1000.0,
            payment_frequency=2
        )
        
        yield_rate = 0.05
        convexity = FixedIncomePricer.calculate_convexity(bond, yield_rate)
        
        assert convexity > 0
    
    def test_zero_coupon_bond_price(self):
        bond = FixedIncomeInstrument(
            symbol="ZERO",
            asset_type=AssetType.BOND,
            exchange="TEST",
            currency="USD",
            maturity_date=datetime.utcnow() + timedelta(days=365*5),
            coupon_rate=0.0,
            face_value=1000.0,
            payment_frequency=2
        )
        
        yield_rate = 0.05
        price = FixedIncomePricer.calculate_bond_price(bond, yield_rate)
        
        expected_price = 1000.0 / (1.025 ** 10)
        
        assert abs(price - expected_price) < 1.0


class TestAssetTypeClassification:
    def test_asset_type_enum_values(self):
        assert AssetType.GOVERNMENT_BOND.value == "government_bond"
        assert AssetType.CORPORATE_BOND.value == "corporate_bond"
        assert AssetType.COMMODITY_FUTURE.value == "commodity_future"
        assert AssetType.INTEREST_RATE_FUTURE.value == "interest_rate_future"
    
    def test_commodity_classification_properties(self):
        energy_symbols = ['CL', 'NG', 'HO', 'RB', 'BZ']
        metals_symbols = ['GC', 'SI', 'HG', 'PL', 'PA']
        ag_symbols = ['C', 'W', 'S', 'SM', 'BO']
        
        for symbol in energy_symbols:
            commodity = CommodityInstrument(
                symbol=symbol,
                asset_type=AssetType.COMMODITY,
                exchange="TEST",
                currency="USD",
                contract_month="DEC24",
                delivery_date=datetime(2024, 12, 20),
                grade="Test",
                delivery_location="Test",
                lot_size_unit="units"
            )
            assert commodity.is_energy == True
        
        for symbol in metals_symbols:
            commodity = CommodityInstrument(
                symbol=symbol,
                asset_type=AssetType.COMMODITY,
                exchange="TEST",
                currency="USD",
                contract_month="DEC24",
                delivery_date=datetime(2024, 12, 20),
                grade="Test",
                delivery_location="Test",
                lot_size_unit="units"
            )
            assert commodity.is_metals == True
        
        for symbol in ag_symbols:
            commodity = CommodityInstrument(
                symbol=symbol,
                asset_type=AssetType.COMMODITY,
                exchange="TEST",
                currency="USD",
                contract_month="DEC24",
                delivery_date=datetime(2024, 12, 20),
                grade="Test",
                delivery_location="Test",
                lot_size_unit="units"
            )
            assert commodity.is_agriculture == True