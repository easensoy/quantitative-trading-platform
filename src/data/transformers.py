from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
import numpy as np
from dataclasses import dataclass
import re

from src.core.exceptions import DatabaseError


@dataclass
class DataQualityRule:
    name: str
    column: str
    rule_type: str
    parameters: Dict[str, Any]
    severity: str = 'error'


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    metrics: Dict[str, Any]


class DataTransformer(ABC):
    @abstractmethod
    def transform(self, data: Any) -> Any:
        pass


class DataCleaner:
    def __init__(self):
        self.cleaning_rules = {
            'remove_duplicates': True,
            'handle_missing_values': True,
            'outlier_detection': True,
            'data_type_validation': True
        }

    def clean_market_data(self, data: List[Dict]) -> List[Dict]:
        if not data:
            return data
        
        df = pd.DataFrame(data)
        
        df = self._remove_duplicates(df)
        df = self._handle_missing_values(df)
        df = self._validate_price_data(df)
        df = self._detect_and_handle_outliers(df)
        df = self._standardize_timestamps(df)
        
        return df.to_dict('records')

    def clean_fundamental_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cleaned_data = {}
        
        for statement_type, statements in data.items():
            if statement_type == 'source':
                cleaned_data[statement_type] = statements
                continue
            
            if isinstance(statements, list):
                cleaned_statements = []
                for statement in statements:
                    cleaned_statement = self._clean_financial_statement(statement)
                    cleaned_statements.append(cleaned_statement)
                cleaned_data[statement_type] = cleaned_statements
            else:
                cleaned_data[statement_type] = statements
        
        return cleaned_data

    def _remove_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'timestamp' in df.columns and 'symbol' in df.columns:
            return df.drop_duplicates(subset=['timestamp', 'symbol'], keep='last')
        return df.drop_duplicates()

    def _handle_missing_values(self, df: pd.DataFrame) -> pd.DataFrame:
        numeric_columns = df.select_dtypes(include=[np.number]).columns
        
        for col in numeric_columns:
            if col in ['open', 'high', 'low', 'close']:
                df[col] = df[col].fillna(method='ffill').fillna(method='bfill')
            elif col == 'volume':
                df[col] = df[col].fillna(0)
            else:
                df[col] = df[col].fillna(df[col].median())
        
        return df

    def _validate_price_data(self, df: pd.DataFrame) -> pd.DataFrame:
        price_columns = ['open', 'high', 'low', 'close']
        
        for col in price_columns:
            if col in df.columns:
                df = df[df[col] > 0]
        
        if all(col in df.columns for col in price_columns):
            df = df[df['high'] >= df['low']]
            df = df[df['high'] >= df['open']]
            df = df[df['high'] >= df['close']]
            df = df[df['low'] <= df['open']]
            df = df[df['low'] <= df['close']]
        
        return df

    def _detect_and_handle_outliers(self, df: pd.DataFrame, z_threshold: float = 5.0) -> pd.DataFrame:
        numeric_columns = df.select_dtypes(include=[np.number]).columns
        
        for col in numeric_columns:
            if col in ['open', 'high', 'low', 'close']:
                z_scores = np.abs((df[col] - df[col].mean()) / df[col].std())
                outliers = z_scores > z_threshold
                
                if outliers.any():
                    median_value = df[col].median()
                    df.loc[outliers, col] = median_value
        
        return df

    def _standardize_timestamps(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
        
        return df

    def _clean_financial_statement(self, statement: Dict[str, Any]) -> Dict[str, Any]:
        cleaned_statement = {}
        
        for key, value in statement.items():
            if isinstance(value, str):
                try:
                    if value.lower() in ['none', 'null', '', 'n/a']:
                        cleaned_statement[key] = None
                    elif key.lower() != 'fiscaldateending':
                        cleaned_statement[key] = float(value.replace(',', ''))
                    else:
                        cleaned_statement[key] = value
                except (ValueError, AttributeError):
                    cleaned_statement[key] = value
            else:
                cleaned_statement[key] = value
        
        return cleaned_statement


class DataValidator:
    def __init__(self):
        self.market_data_rules = [
            DataQualityRule('price_positive', 'close', 'greater_than', {'value': 0}),
            DataQualityRule('volume_non_negative', 'volume', 'greater_equal', {'value': 0}),
            DataQualityRule('high_ge_low', 'high', 'greater_equal_column', {'column': 'low'}),
            DataQualityRule('timestamp_recent', 'timestamp', 'within_days', {'days': 30}),
            DataQualityRule('no_nulls_price', 'close', 'not_null', {}),
        ]
        
        self.fundamental_data_rules = [
            DataQualityRule('revenue_reasonable', 'totalRevenue', 'range', {'min': 0, 'max': 1e12}),
            DataQualityRule('date_format', 'fiscalDateEnding', 'date_format', {'format': '%Y-%m-%d'}),
        ]

    def validate_market_data(self, data: List[Dict]) -> ValidationResult:
        if not data:
            return ValidationResult(False, ['No data provided'], [], {})
        
        df = pd.DataFrame(data)
        errors = []
        warnings = []
        
        for rule in self.market_data_rules:
            result = self._apply_rule(df, rule)
            if not result['passed'] and rule.severity == 'error':
                errors.extend(result['messages'])
            elif not result['passed'] and rule.severity == 'warning':
                warnings.extend(result['messages'])
        
        metrics = self._calculate_data_metrics(df)
        
        is_valid = len(errors) == 0
        return ValidationResult(is_valid, errors, warnings, metrics)

    def validate_fundamental_data(self, data: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        
        for statement_type, statements in data.items():
            if statement_type == 'source':
                continue
            
            if isinstance(statements, list):
                for i, statement in enumerate(statements):
                    statement_df = pd.DataFrame([statement])
                    
                    for rule in self.fundamental_data_rules:
                        if rule.column in statement_df.columns:
                            result = self._apply_rule(statement_df, rule)
                            if not result['passed'] and rule.severity == 'error':
                                errors.extend([f"{statement_type}[{i}]: {msg}" for msg in result['messages']])
                            elif not result['passed'] and rule.severity == 'warning':
                                warnings.extend([f"{statement_type}[{i}]: {msg}" for msg in result['messages']])
        
        is_valid = len(errors) == 0
        return ValidationResult(is_valid, errors, warnings, {})

    def _apply_rule(self, df: pd.DataFrame, rule: DataQualityRule) -> Dict[str, Any]:
        if rule.column not in df.columns:
            return {'passed': False, 'messages': [f"Column '{rule.column}' not found"]}
        
        column_data = df[rule.column]
        
        if rule.rule_type == 'greater_than':
            condition = column_data > rule.parameters['value']
            violations = (~condition).sum()
            
        elif rule.rule_type == 'greater_equal':
            condition = column_data >= rule.parameters['value']
            violations = (~condition).sum()
            
        elif rule.rule_type == 'greater_equal_column':
            other_column = rule.parameters['column']
            if other_column in df.columns:
                condition = column_data >= df[other_column]
                violations = (~condition).sum()
            else:
                return {'passed': False, 'messages': [f"Column '{other_column}' not found"]}
                
        elif rule.rule_type == 'not_null':
            violations = column_data.isnull().sum()
            
        elif rule.rule_type == 'within_days':
            if column_data.dtype == 'datetime64[ns]':
                cutoff_date = datetime.now() - timedelta(days=rule.parameters['days'])
                condition = column_data >= cutoff_date
                violations = (~condition).sum()
            else:
                return {'passed': False, 'messages': [f"Column '{rule.column}' is not datetime"]}
                
        elif rule.rule_type == 'range':
            min_val = rule.parameters.get('min', float('-inf'))
            max_val = rule.parameters.get('max', float('inf'))
            condition = (column_data >= min_val) & (column_data <= max_val)
            violations = (~condition).sum()
            
        elif rule.rule_type == 'date_format':
            try:
                pd.to_datetime(column_data, format=rule.parameters['format'])
                violations = 0
            except:
                violations = len(column_data)
        else:
            return {'passed': False, 'messages': [f"Unknown rule type: {rule.rule_type}"]}
        
        passed = violations == 0
        messages = [] if passed else [f"Rule '{rule.name}' failed: {violations} violations"]
        
        return {'passed': passed, 'messages': messages, 'violations': violations}

    def _calculate_data_metrics(self, df: pd.DataFrame) -> Dict[str, Any]:
        metrics = {
            'row_count': len(df),
            'column_count': len(df.columns),
            'null_percentage': (df.isnull().sum().sum() / (len(df) * len(df.columns))) * 100,
            'duplicate_count': df.duplicated().sum()
        }
        
        if 'timestamp' in df.columns:
            timestamps = pd.to_datetime(df['timestamp'])
            metrics['date_range'] = {
                'start': timestamps.min().isoformat(),
                'end': timestamps.max().isoformat(),
                'span_days': (timestamps.max() - timestamps.min()).days
            }
        
        numeric_columns = df.select_dtypes(include=[np.number]).columns
        if len(numeric_columns) > 0:
            metrics['numeric_summary'] = df[numeric_columns].describe().to_dict()
        
        return metrics


class TechnicalIndicatorCalculator:
    @staticmethod
    def calculate_moving_averages(df: pd.DataFrame, windows: List[int] = [5, 10, 20, 50, 200]) -> pd.DataFrame:
        for window in windows:
            df[f'sma_{window}'] = df['close'].rolling(window=window).mean()
            df[f'ema_{window}'] = df['close'].ewm(span=window).mean()
        
        return df

    @staticmethod
    def calculate_rsi(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=window).mean()
        avg_loss = loss.rolling(window=window).mean()
        
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        return df

    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, window: int = 20, num_std: float = 2) -> pd.DataFrame:
        df['bb_middle'] = df['close'].rolling(window=window).mean()
        bb_std = df['close'].rolling(window=window).std()
        
        df['bb_upper'] = df['bb_middle'] + (bb_std * num_std)
        df['bb_lower'] = df['bb_middle'] - (bb_std * num_std)
        df['bb_width'] = df['bb_upper'] - df['bb_lower']
        df['bb_position'] = (df['close'] - df['bb_lower']) / df['bb_width']
        
        return df

    @staticmethod
    def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        ema_fast = df['close'].ewm(span=fast).mean()
        ema_slow = df['close'].ewm(span=slow).mean()
        
        df['macd'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd'].ewm(span=signal).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        return df

    @staticmethod
    def calculate_stochastic(df: pd.DataFrame, k_window: int = 14, d_window: int = 3) -> pd.DataFrame:
        lowest_low = df['low'].rolling(window=k_window).min()
        highest_high = df['high'].rolling(window=k_window).max()
        
        df['stoch_k'] = 100 * (df['close'] - lowest_low) / (highest_high - lowest_low)
        df['stoch_d'] = df['stoch_k'].rolling(window=d_window).mean()
        
        return df

    @staticmethod
    def calculate_atr(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        true_range = np.maximum(high_low, np.maximum(high_close, low_close))
        df['atr'] = true_range.rolling(window=window).mean()
        
        return df


class MarketDataTransformer(DataTransformer):
    def __init__(self):
        self.indicator_calculator = TechnicalIndicatorCalculator()

    def transform(self, data: List[Dict]) -> pd.DataFrame:
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        df = self._calculate_basic_metrics(df)
        df = self.indicator_calculator.calculate_moving_averages(df)
        df = self.indicator_calculator.calculate_rsi(df)
        df = self.indicator_calculator.calculate_bollinger_bands(df)
        df = self.indicator_calculator.calculate_macd(df)
        df = self.indicator_calculator.calculate_stochastic(df)
        df = self.indicator_calculator.calculate_atr(df)
        df = self._calculate_volatility_metrics(df)
        df = self._calculate_volume_metrics(df)
        
        return df

    def _calculate_basic_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        df['price_range'] = df['high'] - df['low']
        df['body_size'] = np.abs(df['close'] - df['open'])
        df['upper_shadow'] = df['high'] - np.maximum(df['open'], df['close'])
        df['lower_shadow'] = np.minimum(df['open'], df['close']) - df['low']
        
        return df

    def _calculate_volatility_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        df['volatility_5d'] = df['returns'].rolling(window=5).std() * np.sqrt(252)
        df['volatility_20d'] = df['returns'].rolling(window=20).std() * np.sqrt(252)
        df['volatility_60d'] = df['returns'].rolling(window=60).std() * np.sqrt(252)
        
        df['parkinson_volatility'] = np.sqrt(
            (1 / (4 * np.log(2))) * 
            np.log(df['high'] / df['low']) ** 2
        ).rolling(window=20).mean() * np.sqrt(252)
        
        return df

    def _calculate_volume_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        df['volume_sma_20'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma_20']
        df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
        
        df['price_volume'] = df['close'] * df['volume']
        df['on_balance_volume'] = (df['volume'] * np.sign(df['returns'])).cumsum()
        
        return df


class FundamentalDataTransformer(DataTransformer):
    def transform(self, data: Dict[str, Any]) -> Dict[str, Any]:
        transformed_data = {}
        
        for statement_type, statements in data.items():
            if statement_type == 'source':
                transformed_data[statement_type] = statements
                continue
            
            if isinstance(statements, list) and len(statements) > 0:
                df = pd.DataFrame(statements)
                
                if statement_type == 'income_statement':
                    df = self._calculate_income_ratios(df)
                elif statement_type == 'balance_sheet':
                    df = self._calculate_balance_sheet_ratios(df)
                elif statement_type == 'cash_flow':
                    df = self._calculate_cash_flow_ratios(df)
                
                transformed_data[statement_type] = df.to_dict('records')
            else:
                transformed_data[statement_type] = statements
        
        combined_ratios = self._calculate_combined_ratios(transformed_data)
        transformed_data['financial_ratios'] = combined_ratios
        
        return transformed_data

    def _calculate_income_ratios(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'totalRevenue' in df.columns and 'grossProfit' in df.columns:
            df['gross_margin'] = df['grossProfit'] / df['totalRevenue']
        
        if 'totalRevenue' in df.columns and 'operatingIncome' in df.columns:
            df['operating_margin'] = df['operatingIncome'] / df['totalRevenue']
        
        if 'totalRevenue' in df.columns and 'netIncome' in df.columns:
            df['net_margin'] = df['netIncome'] / df['totalRevenue']
        
        return df

    def _calculate_balance_sheet_ratios(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'totalLiabilities' in df.columns and 'totalShareholderEquity' in df.columns:
            df['debt_to_equity'] = df['totalLiabilities'] / df['totalShareholderEquity']
        
        if 'totalAssets' in df.columns and 'totalShareholderEquity' in df.columns:
            df['equity_ratio'] = df['totalShareholderEquity'] / df['totalAssets']
        
        return df

    def _calculate_cash_flow_ratios(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'operatingCashflow' in df.columns and 'capitalExpenditures' in df.columns:
            df['fcf_margin'] = (df['operatingCashflow'] + df['capitalExpenditures']) / df['operatingCashflow']
        
        return df

    def _calculate_combined_ratios(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        ratios = []
        
        income_statements = data.get('income_statement', [])
        balance_sheets = data.get('balance_sheet', [])
        
        for i in range(min(len(income_statements), len(balance_sheets))):
            income = income_statements[i]
            balance = balance_sheets[i]
            
            ratio_dict = {'fiscal_year': income.get('fiscalDateEnding')}
            
            revenue = income.get('totalRevenue', 0) or 0
            total_assets = balance.get('totalAssets', 0) or 0
            total_equity = balance.get('totalShareholderEquity', 0) or 0
            net_income = income.get('netIncome', 0) or 0
            
            if total_assets > 0:
                ratio_dict['roa'] = net_income / total_assets
                ratio_dict['asset_turnover'] = revenue / total_assets
            
            if total_equity > 0:
                ratio_dict['roe'] = net_income / total_equity
            
            ratios.append(ratio_dict)
        
        return ratios


class DataAggregator:
    def aggregate_by_time(
        self,
        data: pd.DataFrame,
        time_column: str = 'timestamp',
        frequency: str = '1H',
        aggregation_functions: Dict[str, str] = None
    ) -> pd.DataFrame:
        if aggregation_functions is None:
            aggregation_functions = {
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }
        
        data[time_column] = pd.to_datetime(data[time_column])
        data.set_index(time_column, inplace=True)
        
        available_functions = {
            col: func for col, func in aggregation_functions.items() 
            if col in data.columns
        }
        
        aggregated = data.groupby('symbol').resample(frequency).agg(available_functions)
        
        return aggregated.reset_index()

    def calculate_cross_sectional_stats(
        self,
        data: pd.DataFrame,
        group_column: str = 'timestamp',
        value_column: str = 'close'
    ) -> pd.DataFrame:
        stats = data.groupby(group_column)[value_column].agg([
            'count', 'mean', 'median', 'std', 'min', 'max',
            lambda x: x.quantile(0.25),
            lambda x: x.quantile(0.75)
        ]).reset_index()
        
        stats.columns = [group_column, 'count', 'mean', 'median', 'std', 'min', 'max', 'q25', 'q75']
        
        return stats