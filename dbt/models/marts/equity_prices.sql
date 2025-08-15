{{ config(materialized='table') }}

with bloomberg_data as (
    select * from {{ ref('stg_bloomberg_equity') }}
),

refinitiv_data as (
    select * from {{ ref('stg_refinitiv_equity') }}
),

factset_data as (
    select * from {{ ref('stg_factset_equity') }}
),

-- Combine all data sources
combined_data as (
    select * from bloomberg_data
    union all
    select * from refinitiv_data  
    union all
    select * from factset_data
),

-- Calculate data quality scores for each record
scored_data as (
    select 
        *,
        -- Calculate completeness score (0-1)
        (
            case when open_price is not null then 0.2 else 0 end +
            case when high_price is not null then 0.2 else 0 end +
            case when low_price is not null then 0.2 else 0 end +
            case when close_price is not null then 0.2 else 0 end +
            case when volume is not null then 0.2 else 0 end
        ) as completeness_score,
        
        -- Calculate consistency score
        case 
            when high_price >= low_price and high_price >= close_price and high_price >= open_price 
                 and low_price <= close_price and low_price <= open_price then 1.0
            else 0.5
        end as consistency_score
        
    from combined_data
),

-- Rank data sources by quality for deduplication
ranked_data as (
    select 
        *,
        row_number() over (
            partition by symbol, trade_date 
            order by 
                (completeness_score + consistency_score) desc,
                case data_source
                    when 'bloomberg' then 1
                    when 'refinitiv' then 2  
                    when 'factset' then 3
                end,
                updated_at desc
        ) as source_rank
    from scored_data
),

-- Select best data source for each symbol-date
deduplicated_data as (
    select 
        symbol,
        trade_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
        daily_return,
        volatility_30d,
        data_source,
        completeness_score,
        consistency_score,
        created_at,
        updated_at
    from ranked_data
    where source_rank = 1
),

-- Calculate technical indicators
enriched_data as (
    select 
        *,
        
        -- Simple moving averages
        avg(close_price) over (
            partition by symbol 
            order by trade_date 
            rows between 19 preceding and current row
        ) as sma_20,
        
        avg(close_price) over (
            partition by symbol 
            order by trade_date 
            rows between 49 preceding and current row
        ) as sma_50,
        
        -- Exponential moving average (approximation)
        -- EMA = (Close - Previous_EMA) * (2/(N+1)) + Previous_EMA
        -- This is a simplified calculation
        avg(close_price) over (
            partition by symbol 
            order by trade_date 
            rows between 19 preceding and current row
        ) as ema_20,
        
        -- Bollinger Bands
        avg(close_price) over (
            partition by symbol 
            order by trade_date 
            rows between 19 preceding and current row
        ) + 2 * stddev(close_price) over (
            partition by symbol 
            order by trade_date 
            rows between 19 preceding and current row
        ) as bollinger_upper,
        
        avg(close_price) over (
            partition by symbol 
            order by trade_date 
            rows between 19 preceding and current row
        ) - 2 * stddev(close_price) over (
            partition by symbol 
            order by trade_date 
            rows between 19 preceding and current row
        ) as bollinger_lower,
        
        -- Volume ratio (current volume vs 20-day average)
        case 
            when avg(volume) over (
                partition by symbol 
                order by trade_date 
                rows between 19 preceding and current row
            ) > 0 then 
                volume / avg(volume) over (
                    partition by symbol 
                    order by trade_date 
                    rows between 19 preceding and current row
                )
            else null
        end as volume_ratio,
        
        -- Price momentum (20-day)
        case 
            when lag(close_price, 20) over (partition by symbol order by trade_date) > 0 then
                (close_price - lag(close_price, 20) over (partition by symbol order by trade_date)) /
                lag(close_price, 20) over (partition by symbol order by trade_date)
            else null
        end as momentum_20d
        
    from deduplicated_data
)

select 
    symbol,
    trade_date,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    daily_return,
    volatility_30d,
    sma_20,
    sma_50,
    ema_20,
    bollinger_upper,
    bollinger_lower,
    volume_ratio,
    momentum_20d,
    data_source,
    completeness_score,
    consistency_score,
    created_at as source_created_at,
    current_timestamp() as processed_at
from enriched_data
where close_price is not null