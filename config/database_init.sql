-- MySQL Database Initialization Script for Trading Infrastructure

-- Create database if it doesn't exist
CREATE DATABASE IF NOT EXISTS trading_db 
CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

USE trading_db;

-- Instruments table
CREATE TABLE IF NOT EXISTS instruments (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL UNIQUE,
    asset_type ENUM('equity', 'bond', 'option', 'future', 'fx', 'crypto', 'commodity') NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    multiplier DECIMAL(10,4) DEFAULT 1.0000,
    tick_size DECIMAL(10,8) DEFAULT 0.01000000,
    lot_size INT DEFAULT 1,
    metadata JSON,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_symbol (symbol),
    INDEX idx_asset_type (asset_type),
    INDEX idx_exchange (exchange)
);

-- Market data table
CREATE TABLE IF NOT EXISTS market_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp DATETIME(3) NOT NULL,
    open_price DECIMAL(15,4),
    high_price DECIMAL(15,4),
    low_price DECIMAL(15,4),
    close_price DECIMAL(15,4),
    volume BIGINT UNSIGNED DEFAULT 0,
    bid_price DECIMAL(15,4),
    ask_price DECIMAL(15,4),
    bid_size INT UNSIGNED,
    ask_size INT UNSIGNED,
    last_price DECIMAL(15,4),
    source VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_symbol_timestamp (symbol, timestamp),
    INDEX idx_timestamp (timestamp),
    INDEX idx_source (source),
    UNIQUE KEY unique_symbol_timestamp_source (symbol, timestamp, source)
);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id VARCHAR(100) NOT NULL UNIQUE,
    strategy_id VARCHAR(100),
    symbol VARCHAR(20) NOT NULL,
    side ENUM('buy', 'sell') NOT NULL,
    order_type ENUM('market', 'limit', 'stop', 'stop_limit') NOT NULL,
    quantity INT NOT NULL,
    price DECIMAL(15,4),
    stop_price DECIMAL(15,4),
    status ENUM('pending', 'submitted', 'partially_filled', 'filled', 'cancelled', 'rejected') DEFAULT 'pending',
    filled_quantity INT DEFAULT 0,
    avg_fill_price DECIMAL(15,4),
    venue ENUM('nyse', 'nasdaq', 'bats', 'arca', 'iex', 'dark_pool'),
    submitted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_order_id (order_id),
    INDEX idx_strategy_id (strategy_id),
    INDEX idx_symbol (symbol),
    INDEX idx_status (status),
    INDEX idx_submitted_at (submitted_at),
    
    FOREIGN KEY (symbol) REFERENCES instruments(symbol) ON UPDATE CASCADE
);

-- Fills table
CREATE TABLE IF NOT EXISTS fills (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    fill_id VARCHAR(100) NOT NULL UNIQUE,
    order_id VARCHAR(100) NOT NULL,
    trade_id VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side ENUM('buy', 'sell') NOT NULL,
    quantity INT NOT NULL,
    price DECIMAL(15,4) NOT NULL,
    venue ENUM('nyse', 'nasdaq', 'bats', 'arca', 'iex', 'dark_pool'),
    commission DECIMAL(10,4) DEFAULT 0.0000,
    timestamp DATETIME(3) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_order_id (order_id),
    INDEX idx_symbol (symbol),
    INDEX idx_timestamp (timestamp),
    INDEX idx_trade_id (trade_id),
    
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON UPDATE CASCADE,
    FOREIGN KEY (symbol) REFERENCES instruments(symbol) ON UPDATE CASCADE
);

-- Positions table
CREATE TABLE IF NOT EXISTS positions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    portfolio_id VARCHAR(100) NOT NULL,
    strategy_id VARCHAR(100),
    symbol VARCHAR(20) NOT NULL,
    quantity INT NOT NULL DEFAULT 0,
    avg_price DECIMAL(15,4) NOT NULL,
    unrealized_pnl DECIMAL(15,4) DEFAULT 0.0000,
    realized_pnl DECIMAL(15,4) DEFAULT 0.0000,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_portfolio_id (portfolio_id),
    INDEX idx_strategy_id (strategy_id),
    INDEX idx_symbol (symbol),
    UNIQUE KEY unique_portfolio_symbol (portfolio_id, symbol),
    
    FOREIGN KEY (symbol) REFERENCES instruments(symbol) ON UPDATE CASCADE
);

-- Portfolios table
CREATE TABLE IF NOT EXISTS portfolios (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    portfolio_id VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    cash DECIMAL(20,4) DEFAULT 0.0000,
    total_value DECIMAL(20,4) DEFAULT 0.0000,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_portfolio_id (portfolio_id),
    INDEX idx_name (name),
    INDEX idx_is_active (is_active)
);

-- Strategies table
CREATE TABLE IF NOT EXISTS strategies (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    strategy_id VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    parameters JSON,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_strategy_id (strategy_id),
    INDEX idx_name (name),
    INDEX idx_is_active (is_active)
);

-- PnL Attribution table
CREATE TABLE IF NOT EXISTS pnl_attribution (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    strategy_id VARCHAR(100) NOT NULL,
    portfolio_id VARCHAR(100) NOT NULL,
    timestamp DATETIME(3) NOT NULL,
    realized_pnl DECIMAL(15,4) DEFAULT 0.0000,
    unrealized_pnl DECIMAL(15,4) DEFAULT 0.0000,
    total_pnl DECIMAL(15,4) DEFAULT 0.0000,
    attribution_factors JSON,
    benchmark_pnl DECIMAL(15,4) DEFAULT 0.0000,
    alpha DECIMAL(15,4) DEFAULT 0.0000,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_strategy_id (strategy_id),
    INDEX idx_portfolio_id (portfolio_id),
    INDEX idx_timestamp (timestamp),
    UNIQUE KEY unique_strategy_portfolio_timestamp (strategy_id, portfolio_id, timestamp),
    
    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id) ON UPDATE CASCADE,
    FOREIGN KEY (portfolio_id) REFERENCES portfolios(portfolio_id) ON UPDATE CASCADE
);

-- Risk metrics table
CREATE TABLE IF NOT EXISTS risk_metrics (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    portfolio_id VARCHAR(100) NOT NULL,
    timestamp DATETIME(3) NOT NULL,
    var_95 DECIMAL(15,4),
    var_99 DECIMAL(15,4),
    expected_shortfall DECIMAL(15,4),
    max_drawdown DECIMAL(15,4),
    volatility DECIMAL(15,4),
    sharpe_ratio DECIMAL(15,4),
    beta DECIMAL(15,4),
    alpha DECIMAL(15,4),
    correlation DECIMAL(15,4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_portfolio_id (portfolio_id),
    INDEX idx_timestamp (timestamp),
    
    FOREIGN KEY (portfolio_id) REFERENCES portfolios(portfolio_id) ON UPDATE CASCADE
);

-- Fundamental data table
CREATE TABLE IF NOT EXISTS fundamental_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    statement_type ENUM('income_statement', 'balance_sheet', 'cash_flow') NOT NULL,
    fiscal_date_ending DATE NOT NULL,
    total_revenue BIGINT,
    gross_profit BIGINT,
    operating_income BIGINT,
    net_income BIGINT,
    ebitda BIGINT,
    total_assets BIGINT,
    total_liabilities BIGINT,
    total_shareholder_equity BIGINT,
    cash BIGINT,
    operating_cashflow BIGINT,
    capital_expenditures BIGINT,
    free_cash_flow BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_symbol (symbol),
    INDEX idx_statement_type (statement_type),
    INDEX idx_fiscal_date (fiscal_date_ending),
    UNIQUE KEY unique_symbol_type_date (symbol, statement_type, fiscal_date_ending),
    
    FOREIGN KEY (symbol) REFERENCES instruments(symbol) ON UPDATE CASCADE
);

-- News and events table
CREATE TABLE IF NOT EXISTS news_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20),
    title VARCHAR(500) NOT NULL,
    content TEXT,
    source VARCHAR(100),
    url VARCHAR(1000),
    sentiment_score DECIMAL(5,4),
    sentiment_label ENUM('bearish', 'neutral', 'bullish'),
    published_at DATETIME(3) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_symbol (symbol),
    INDEX idx_published_at (published_at),
    INDEX idx_source (source),
    INDEX idx_sentiment_label (sentiment_label)
);

-- Audit log table
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    record_id VARCHAR(100) NOT NULL,
    action ENUM('INSERT', 'UPDATE', 'DELETE') NOT NULL,
    old_values JSON,
    new_values JSON,
    user_id VARCHAR(100),
    timestamp DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    
    INDEX idx_table_name (table_name),
    INDEX idx_record_id (record_id),
    INDEX idx_action (action),
    INDEX idx_timestamp (timestamp)
);

-- Insert sample instruments
INSERT IGNORE INTO instruments (symbol, asset_type, exchange, currency) VALUES
('AAPL', 'equity', 'NASDAQ', 'USD'),
('GOOGL', 'equity', 'NASDAQ', 'USD'),
('MSFT', 'equity', 'NASDAQ', 'USD'),
('TSLA', 'equity', 'NASDAQ', 'USD'),
('SPY', 'equity', 'ARCA', 'USD'),
('QQQ', 'equity', 'NASDAQ', 'USD'),
('IWM', 'equity', 'ARCA', 'USD'),
('GLD', 'equity', 'ARCA', 'USD'),
('TLT', 'equity', 'NASDAQ', 'USD'),
('VIX', 'equity', 'CBOE', 'USD');

-- Insert sample portfolio
INSERT IGNORE INTO portfolios (portfolio_id, name, cash) VALUES
('main_portfolio', 'Main Trading Portfolio', 1000000.00),
('test_portfolio', 'Test Portfolio', 100000.00);

-- Insert sample strategy
INSERT IGNORE INTO strategies (strategy_id, name, description, parameters) VALUES
('momentum_strategy', 'Momentum Strategy', 'Long-term momentum strategy', '{"lookback_period": 252, "rebalance_frequency": "monthly"}'),
('mean_reversion', 'Mean Reversion Strategy', 'Short-term mean reversion strategy', '{"lookback_period": 20, "rebalance_frequency": "daily"}');

-- Create stored procedures for common operations

DELIMITER //

-- Procedure to update position after fill
CREATE PROCEDURE UpdatePositionAfterFill(
    IN p_portfolio_id VARCHAR(100),
    IN p_symbol VARCHAR(20),
    IN p_fill_quantity INT,
    IN p_fill_price DECIMAL(15,4),
    IN p_side ENUM('buy', 'sell')
)
BEGIN
    DECLARE current_quantity INT DEFAULT 0;
    DECLARE current_avg_price DECIMAL(15,4) DEFAULT 0;
    DECLARE new_quantity INT;
    DECLARE new_avg_price DECIMAL(15,4);
    
    -- Get current position
    SELECT quantity, avg_price INTO current_quantity, current_avg_price
    FROM positions 
    WHERE portfolio_id = p_portfolio_id AND symbol = p_symbol;
    
    -- Calculate new position
    IF p_side = 'buy' THEN
        SET new_quantity = current_quantity + p_fill_quantity;
        IF new_quantity > 0 THEN
            SET new_avg_price = ((current_quantity * current_avg_price) + (p_fill_quantity * p_fill_price)) / new_quantity;
        ELSE
            SET new_avg_price = p_fill_price;
        END IF;
    ELSE
        SET new_quantity = current_quantity - p_fill_quantity;
        IF new_quantity = 0 THEN
            -- Close position
            DELETE FROM positions WHERE portfolio_id = p_portfolio_id AND symbol = p_symbol;
        ELSE
            -- Keep average price for partial close
            SET new_avg_price = current_avg_price;
        END IF;
    END IF;
    
    -- Update or insert position
    IF new_quantity != 0 THEN
        INSERT INTO positions (portfolio_id, symbol, quantity, avg_price)
        VALUES (p_portfolio_id, p_symbol, new_quantity, new_avg_price)
        ON DUPLICATE KEY UPDATE
            quantity = new_quantity,
            avg_price = new_avg_price,
            last_updated = CURRENT_TIMESTAMP;
    END IF;
END //

-- Procedure to calculate portfolio value
CREATE PROCEDURE CalculatePortfolioValue(
    IN p_portfolio_id VARCHAR(100),
    OUT p_total_value DECIMAL(20,4)
)
BEGIN
    DECLARE total_positions_value DECIMAL(20,4) DEFAULT 0;
    DECLARE cash_amount DECIMAL(20,4) DEFAULT 0;
    
    -- Get cash amount
    SELECT cash INTO cash_amount FROM portfolios WHERE portfolio_id = p_portfolio_id;
    
    -- Calculate total positions value using latest market data
    SELECT COALESCE(SUM(p.quantity * md.close_price), 0) INTO total_positions_value
    FROM positions p
    INNER JOIN (
        SELECT symbol, close_price,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY timestamp DESC) as rn
        FROM market_data
        WHERE close_price IS NOT NULL
    ) md ON p.symbol = md.symbol AND md.rn = 1
    WHERE p.portfolio_id = p_portfolio_id;
    
    SET p_total_value = COALESCE(cash_amount, 0) + COALESCE(total_positions_value, 0);
    
    -- Update portfolio total value
    UPDATE portfolios 
    SET total_value = p_total_value, updated_at = CURRENT_TIMESTAMP
    WHERE portfolio_id = p_portfolio_id;
END //

DELIMITER ;

-- Create views for common queries

-- Latest market data view
CREATE OR REPLACE VIEW latest_market_data AS
SELECT 
    symbol,
    timestamp,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    bid_price,
    ask_price,
    (bid_price + ask_price) / 2 as mid_price,
    ask_price - bid_price as spread
FROM market_data md1
WHERE md1.timestamp = (
    SELECT MAX(md2.timestamp)
    FROM market_data md2
    WHERE md2.symbol = md1.symbol
);

-- Portfolio summary view
CREATE OR REPLACE VIEW portfolio_summary AS
SELECT 
    p.portfolio_id,
    p.name,
    p.cash,
    p.total_value,
    COUNT(pos.symbol) as num_positions,
    SUM(pos.quantity * lmd.close_price) as positions_value,
    p.total_value - p.cash as calculated_positions_value
FROM portfolios p
LEFT JOIN positions pos ON p.portfolio_id = pos.portfolio_id
LEFT JOIN latest_market_data lmd ON pos.symbol = lmd.symbol
WHERE p.is_active = TRUE
GROUP BY p.portfolio_id, p.name, p.cash, p.total_value;

-- Active orders view
CREATE OR REPLACE VIEW active_orders AS
SELECT 
    o.order_id,
    o.strategy_id,
    o.symbol,
    o.side,
    o.order_type,
    o.quantity,
    o.price,
    o.status,
    o.filled_quantity,
    o.quantity - o.filled_quantity as remaining_quantity,
    o.avg_fill_price,
    o.venue,
    o.submitted_at,
    TIMESTAMPDIFF(MINUTE, o.submitted_at, NOW()) as minutes_since_submission
FROM orders o
WHERE o.status IN ('submitted', 'partially_filled')
ORDER BY o.submitted_at DESC;