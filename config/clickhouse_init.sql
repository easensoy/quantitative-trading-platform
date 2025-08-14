-- ClickHouse Database Initialization Script for Trading Analytics

-- Create database if it doesn't exist
CREATE DATABASE IF NOT EXISTS trading_analytics;

USE trading_analytics;

-- Market analytics table (fact table for time series data)
CREATE TABLE IF NOT EXISTS market_analytics (
    symbol String,
    timestamp DateTime64(3),
    date Date MATERIALIZED toDate(timestamp),
    open_price Float64,
    high_price Float64,
    low_price Float64,
    close_price Float64,
    volume UInt64,
    returns Float64,
    log_returns Float64,
    volatility_5d Float64,
    volatility_20d Float64,
    volatility_60d Float64,
    sma_5 Float64,
    sma_10 Float64,
    sma_20 Float64,
    sma_50 Float64,
    sma_200 Float64,
    ema_5 Float64,
    ema_10 Float64,
    ema_20 Float64,
    ema_50 Float64,
    rsi Float64,
    bb_upper Float64,
    bb_middle Float64,
    bb_lower Float64,
    bb_width Float64,
    bb_position Float64,
    macd Float64,
    macd_signal Float64,
    macd_histogram Float64,
    stoch_k Float64,
    stoch_d Float64,
    atr Float64,
    volume_sma_20 Float64,
    volume_ratio Float64,
    vwap Float64,
    on_balance_volume Float64,
    parkinson_volatility Float64,
    price_range Float64,
    body_size Float64,
    upper_shadow Float64,
    lower_shadow Float64,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, timestamp)
SETTINGS index_granularity = 8192;

-- Portfolio analytics table
CREATE TABLE IF NOT EXISTS portfolio_analytics (
    portfolio_id String,
    strategy_id String,
    timestamp DateTime64(3),
    date Date MATERIALIZED toDate(timestamp),
    total_value Float64,
    cash Float64,
    positions_value Float64,
    num_positions UInt32,
    daily_pnl Float64,
    cumulative_pnl Float64,
    daily_return Float64,
    cumulative_return Float64,
    volatility Float64,
    sharpe_ratio Float64,
    max_drawdown Float64,
    var_95 Float64,
    var_99 Float64,
    beta Float64,
    alpha Float64,
    correlation Float64,
    tracking_error Float64,
    information_ratio Float64,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (portfolio_id, timestamp)
SETTINGS index_granularity = 8192;

-- Trade analytics table
CREATE TABLE IF NOT EXISTS trade_analytics (
    trade_id String,
    order_id String,
    strategy_id String,
    portfolio_id String,
    symbol String,
    side Enum('buy' = 1, 'sell' = 2),
    quantity UInt32,
    price Float64,
    notional Float64,
    commission Float64,
    venue String,
    timestamp DateTime64(3),
    date Date MATERIALIZED toDate(timestamp),
    market_price_at_time Float64,
    slippage Float64,
    market_impact Float64,
    execution_time_ms UInt32,
    is_aggressive Bool,
    fill_rate Float64,
    parent_order_id String,
    slice_number UInt16,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (strategy_id, timestamp)
SETTINGS index_granularity = 8192;

-- Risk metrics table
CREATE TABLE IF NOT EXISTS risk_metrics (
    portfolio_id String,
    strategy_id String,
    timestamp DateTime64(3),
    date Date MATERIALIZED toDate(timestamp),
    var_95 Float64,
    var_99 Float64,
    expected_shortfall Float64,
    max_drawdown Float64,
    volatility Float64,
    downside_deviation Float64,
    sortino_ratio Float64,
    calmar_ratio Float64,
    omega_ratio Float64,
    skewness Float64,
    kurtosis Float64,
    tail_ratio Float64,
    conditional_var Float64,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (portfolio_id, timestamp)
SETTINGS index_granularity = 8192;

-- Factor exposures table
CREATE TABLE IF NOT EXISTS factor_exposures (
    portfolio_id String,
    symbol String,
    timestamp DateTime64(3),
    date Date MATERIALIZED toDate(timestamp),
    market_beta Float64,
    size_factor Float64,
    value_factor Float64,
    momentum_factor Float64,
    quality_factor Float64,
    volatility_factor Float64,
    growth_factor Float64,
    profitability_factor Float64,
    investment_factor Float64,
    sector_exposure Map(String, Float64),
    country_exposure Map(String, Float64),
    currency_exposure Map(String, Float64),
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (portfolio_id, symbol, timestamp)
SETTINGS index_granularity = 8192;

-- Market microstructure table
CREATE TABLE IF NOT EXISTS market_microstructure (
    symbol String,
    timestamp DateTime64(3),
    date Date MATERIALIZED toDate(timestamp),
    bid_price Float64,
    ask_price Float64,
    bid_size UInt32,
    ask_size UInt32,
    mid_price Float64,
    spread Float64,
    spread_bps Float64,
    effective_spread Float64,
    price_impact Float64,
    order_imbalance Float64,
    trade_count UInt32,
    trade_volume UInt64,
    vwap Float64,
    implementation_shortfall Float64,
    arrival_price Float64,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, timestamp)
SETTINGS index_granularity = 8192;

-- News sentiment analytics
CREATE TABLE IF NOT EXISTS news_sentiment (
    symbol String,
    news_id String,
    timestamp DateTime64(3),
    date Date MATERIALIZED toDate(timestamp),
    title String,
    source String,
    sentiment_score Float64,
    sentiment_label Enum('bearish' = 1, 'neutral' = 2, 'bullish' = 3),
    relevance_score Float64,
    topic String,
    keywords Array(String),
    impact_score Float64,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, timestamp)
SETTINGS index_granularity = 8192;

-- Alternative data table
CREATE TABLE IF NOT EXISTS alternative_data (
    symbol String,
    data_type String,
    timestamp DateTime64(3),
    date Date MATERIALIZED toDate(timestamp),
    satellite_data Map(String, Float64),
    social_sentiment Map(String, Float64),
    web_traffic Map(String, Float64),
    economic_indicators Map(String, Float64),
    esg_metrics Map(String, Float64),
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, data_type, timestamp)
SETTINGS index_granularity = 8192;

-- Materialized views for common aggregations

-- Daily OHLCV aggregation
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_ohlcv
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date)
AS SELECT
    symbol,
    date,
    argMinState(open_price, timestamp) as open_price,
    maxState(high_price) as high_price,
    minState(low_price) as low_price,
    argMaxState(close_price, timestamp) as close_price,
    sumState(volume) as volume,
    avgState(returns) as avg_return,
    stddevPopState(returns) as volatility
FROM market_analytics
GROUP BY symbol, date;

-- Hourly portfolio performance
CREATE MATERIALIZED VIEW IF NOT EXISTS hourly_portfolio_performance
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (portfolio_id, date, hour)
AS SELECT
    portfolio_id,
    date,
    toHour(timestamp) as hour,
    argMaxState(total_value, timestamp) as total_value,
    sumState(daily_pnl) as hourly_pnl,
    avgState(daily_return) as avg_return,
    stddevPopState(daily_return) as volatility
FROM portfolio_analytics
GROUP BY portfolio_id, date, hour;

-- Trade execution analytics
CREATE MATERIALIZED VIEW IF NOT EXISTS trade_execution_stats
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (strategy_id, symbol, date)
AS SELECT
    strategy_id,
    symbol,
    date,
    countState() as trade_count,
    sumState(notional) as total_notional,
    avgState(price) as avg_price,
    avgState(slippage) as avg_slippage,
    avgState(market_impact) as avg_market_impact,
    avgState(execution_time_ms) as avg_execution_time,
    sumState(commission) as total_commission
FROM trade_analytics
GROUP BY strategy_id, symbol, date;

-- Risk metrics aggregation
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_risk_metrics
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (portfolio_id, date)
AS SELECT
    portfolio_id,
    date,
    argMaxState(var_95, timestamp) as var_95,
    argMaxState(var_99, timestamp) as var_99,
    maxState(max_drawdown) as max_drawdown,
    avgState(volatility) as avg_volatility,
    argMaxState(expected_shortfall, timestamp) as expected_shortfall
FROM risk_metrics
GROUP BY portfolio_id, date;

-- Function for calculating rolling metrics
CREATE FUNCTION rolling_sharpe_ratio AS (returns, window_size) -> 
    if(count(returns) >= window_size,
       avg(returns) / nullIf(stddevPop(returns), 0) * sqrt(252),
       NULL
    );

CREATE FUNCTION rolling_max_drawdown AS (values, window_size) ->
    if(count(values) >= window_size,
       min((values - runningAccumulate(max, values)) / runningAccumulate(max, values)),
       NULL
    );

-- Create dictionaries for fast lookups

-- Instrument metadata dictionary
CREATE DICTIONARY IF NOT EXISTS instrument_dict (
    symbol String,
    asset_type String,
    exchange String,
    currency String,
    multiplier Float64,
    tick_size Float64
)
PRIMARY KEY symbol
SOURCE(MYSQL(
    HOST 'localhost'
    PORT 3306
    USER 'trading_user'
    PASSWORD ''
    DB 'trading_db'
    TABLE 'instruments'
    REPLICA(HOST 'localhost' PORT 3306 PRIORITY 1)
))
LIFETIME(MIN 300 MAX 3600)
LAYOUT(HASHED());

-- Create sample data insertion procedures
CREATE OR REPLACE FUNCTION insert_market_data AS (
    symbol_val String,
    timestamp_val DateTime64(3),
    open_val Float64,
    high_val Float64,
    low_val Float64,
    close_val Float64,
    volume_val UInt64
) -> UInt8
LANGUAGE SQL
AS $$
    INSERT INTO market_analytics (
        symbol, timestamp, open_price, high_price, low_price, close_price, volume,
        returns, volatility_20d, sma_20, rsi
    ) VALUES (
        symbol_val, timestamp_val, open_val, high_val, low_val, close_val, volume_val,
        (close_val - open_val) / open_val,
        0.02,  -- placeholder volatility
        close_val,  -- placeholder SMA
        50.0   -- placeholder RSI
    );
    SELECT 1;
$$;

-- Performance optimization settings
SET allow_experimental_object_type = 1;
SET allow_experimental_map_type = 1;
SET flatten_nested = 0;

-- Create projections for better query performance
ALTER TABLE market_analytics ADD PROJECTION symbol_time_projection (
    SELECT symbol, timestamp, close_price, volume, returns
    ORDER BY symbol, timestamp
);

ALTER TABLE trade_analytics ADD PROJECTION strategy_performance_projection (
    SELECT strategy_id, date, symbol, sum(notional), avg(slippage)
    GROUP BY strategy_id, date, symbol
);

-- Refresh projections to build them
-- ALTER TABLE market_analytics MATERIALIZE PROJECTION symbol_time_projection;
-- ALTER TABLE trade_analytics MATERIALIZE PROJECTION strategy_performance_projection;