{{ config(materialized='table') }}

with sector_mapping as (
    select 
        case 
            when instrument like '%.O' then left(instrument, position('.O' in instrument) - 1)
            when instrument like '%.N' then left(instrument, position('.N' in instrument) - 1)
            else instrument
        end as symbol,
        tr_gicssectorname as gics_sector,
        tr_gicsindustrygroupname as gics_industry_group,
        tr_gicsindustryname as gics_industry,
        tr_gicssubindustryname as gics_sub_industry,
        tr_siccode as sic_code,
        tr_naicscode as naics_code
    from {{ source('refinitiv', 'company_data') }}
    where tr_gicssectorname is not null
),

current_prices as (
    select 
        symbol,
        close_price,
        daily_return,
        volatility_30d,
        volume_ratio,
        momentum_20d,
        data_source
    from {{ ref('equity_prices') }}
    where trade_date = (select max(trade_date) from {{ ref('equity_prices') }})
),

fundamentals as (
    select 
        symbol,
        market_cap,
        pe_ratio,
        price_to_book,
        roe,
        debt_to_equity,
        net_margin
    from {{ ref('fundamental_metrics') }}
),

risk_data as (
    select 
        symbol,
        volatility_1y,
        beta_1y,
        sharpe_ratio_1y,
        max_drawdown_1y,
        risk_score
    from {{ ref('risk_metrics') }}
),

sector_stock_data as (
    select 
        sm.symbol,
        sm.gics_sector,
        sm.gics_industry_group,
        sm.gics_industry,
        sm.gics_sub_industry,
        cp.close_price,
        cp.daily_return,
        cp.volatility_30d,
        cp.volume_ratio,
        cp.momentum_20d,
        fm.market_cap,
        fm.pe_ratio,
        fm.price_to_book,
        fm.roe,
        fm.debt_to_equity,
        fm.net_margin,
        rm.volatility_1y,
        rm.beta_1y,
        rm.sharpe_ratio_1y,
        rm.max_drawdown_1y,
        rm.risk_score
    from sector_mapping sm
    left join current_prices cp on sm.symbol = cp.symbol
    left join fundamentals fm on sm.symbol = fm.symbol
    left join risk_data rm on sm.symbol = rm.symbol
    where sm.gics_sector is not null
),

sector_aggregations as (
    select 
        gics_sector,
        count(*) as stock_count,
        sum(market_cap) as total_market_cap,
        avg(market_cap) as avg_market_cap,
        median(market_cap) as median_market_cap,
        avg(daily_return) as avg_daily_return,
        median(daily_return) as median_daily_return,
        stddev(daily_return) as daily_return_volatility,
        avg(momentum_20d) as avg_momentum_20d,
        avg(pe_ratio) as avg_pe_ratio,
        median(pe_ratio) as median_pe_ratio,
        avg(price_to_book) as avg_price_to_book,
        median(price_to_book) as median_price_to_book,
        avg(roe) as avg_roe,
        median(roe) as median_roe,
        avg(debt_to_equity) as avg_debt_to_equity,
        avg(net_margin) as avg_net_margin,
        avg(volatility_1y) as avg_volatility,
        median(volatility_1y) as median_volatility,
        avg(beta_1y) as avg_beta,
        avg(sharpe_ratio_1y) as avg_sharpe_ratio,
        avg(max_drawdown_1y) as avg_max_drawdown,
        avg(risk_score) as avg_risk_score,
        sum(case when daily_return > 0 then 1 else 0 end) as positive_return_count,
        sum(case when daily_return > 0 then 1 else 0 end) * 100.0 / count(*) as positive_return_pct,
        sum(daily_return * market_cap) / nullif(sum(market_cap), 0) as market_cap_weighted_return
        
    from sector_stock_data
    where market_cap is not null
    group by gics_sector
),

sector_rankings as (
    select 
        *,
        rank() over (order by avg_daily_return desc) as return_rank,
        rank() over (order by avg_momentum_20d desc) as momentum_rank,
        rank() over (order by avg_sharpe_ratio desc) as sharpe_rank,
        rank() over (order by avg_pe_ratio asc) as pe_rank,
        rank() over (order by avg_price_to_book asc) as pb_rank,
        rank() over (order by avg_roe desc) as roe_rank,
        rank() over (order by avg_net_margin desc) as margin_rank,
        rank() over (order by avg_debt_to_equity asc) as leverage_rank,
        rank() over (order by avg_volatility asc) as volatility_rank,
        rank() over (order by avg_risk_score asc) as risk_rank,
        rank() over (order by total_market_cap desc) as size_rank
        
    from sector_aggregations
),

sector_scores as (
    select 
        *,
        (100 - return_rank * 10) + (100 - momentum_rank * 10) + (100 - sharpe_rank * 10) as performance_score,
        (100 - pe_rank * 10) + (100 - pb_rank * 10) as value_score,
        (100 - roe_rank * 10) + (100 - margin_rank * 10) + (100 - leverage_rank * 10) as quality_score,
        (100 - volatility_rank * 10) + (100 - risk_rank * 10) as safety_score
        
    from sector_rankings
),

industry_aggregations as (
    select 
        gics_sector,
        gics_industry_group,
        
        count(*) as stock_count,
        sum(market_cap) as total_market_cap,
        avg(daily_return) as avg_daily_return,
        avg(pe_ratio) as avg_pe_ratio,
        avg(roe) as avg_roe,
        avg(volatility_1y) as avg_volatility,
        avg(risk_score) as avg_risk_score
        
    from sector_stock_data
    where market_cap is not null
    group by gics_sector, gics_industry_group
),

final_sector_analysis as (
    select 
        ss.*,
        case
            when ss.performance_score >= 250 then 'outperforming'
            when ss.performance_score >= 200 then 'market_performing' 
            when ss.performance_score >= 150 then 'underperforming'
            else 'lagging'
        end as performance_category,
        
        case
            when ss.value_score >= 180 then 'attractive'
            when ss.value_score >= 150 then 'fair'
            when ss.value_score >= 120 then 'expensive'
            else 'very_expensive'
        end as valuation_category,
        
        case
            when ss.quality_score >= 240 then 'high_quality'
            when ss.quality_score >= 200 then 'good_quality'
            when ss.quality_score >= 160 then 'average_quality'
            else 'low_quality'
        end as quality_category,
        
        case
            when ss.safety_score >= 180 then 'low_risk'
            when ss.safety_score >= 150 then 'moderate_risk'
            when ss.safety_score >= 120 then 'high_risk'
            else 'very_high_risk'
        end as risk_category,
        (ss.performance_score * 0.25 + ss.value_score * 0.25 + ss.quality_score * 0.25 + ss.safety_score * 0.25) as overall_score,
        
        current_timestamp() as analysis_date
        
    from sector_scores ss
)

select 
    gics_sector,
    stock_count,
    total_market_cap / 1e9 as total_market_cap_billions,
    avg_market_cap / 1e6 as avg_market_cap_millions,
    round(avg_daily_return * 100, 2) as avg_daily_return_pct,
    round(avg_momentum_20d * 100, 2) as avg_momentum_20d_pct,
    round(market_cap_weighted_return * 100, 2) as market_cap_weighted_return_pct,
    round(positive_return_pct, 1) as positive_return_pct,
    round(avg_pe_ratio, 1) as avg_pe_ratio,
    round(median_pe_ratio, 1) as median_pe_ratio,
    round(avg_price_to_book, 1) as avg_price_to_book,
    round(avg_roe * 100, 1) as avg_roe_pct,
    round(avg_debt_to_equity, 1) as avg_debt_to_equity,
    round(avg_net_margin * 100, 1) as avg_net_margin_pct,
    round(avg_volatility * 100, 1) as avg_volatility_pct,
    round(avg_beta, 2) as avg_beta,
    round(avg_sharpe_ratio, 2) as avg_sharpe_ratio,
    round(avg_max_drawdown * 100, 1) as avg_max_drawdown_pct,
    round(avg_risk_score, 0) as avg_risk_score,
    return_rank,
    momentum_rank, 
    pe_rank,
    roe_rank,
    volatility_rank,
    risk_rank,
    round(performance_score, 0) as performance_score,
    performance_category,
    round(value_score, 0) as value_score,
    valuation_category,
    round(quality_score, 0) as quality_score,
    quality_category,
    round(safety_score, 0) as safety_score,
    risk_category,
    round(overall_score, 0) as overall_score,
    
    analysis_date
    
from final_sector_analysis
order by overall_score desc