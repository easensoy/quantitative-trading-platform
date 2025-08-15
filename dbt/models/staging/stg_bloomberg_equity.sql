{{ config(materialized='view') }}

with source_data as (
    select 
        security,
        date,
        px_open as open_price,
        px_high as high_price,
        px_low as low_price,
        px_last as close_price,
        px_volume as volume,
        chg_pct_1d as daily_return_pct,
        volatility_30d,
        created_at,
        updated_at
    from {{ source('bloomberg', 'equity_data') }}
),

cleaned_data as (
    select 
        -- Extract symbol from security field (e.g., 'AAPL Equity' -> 'AAPL')
        case 
            when security like '% Equity' then left(security, position(' Equity' in security) - 1)
            else security
        end as symbol,
        
        date::date as trade_date,
        
        -- Ensure prices are positive and logical
        case when open_price > 0 then open_price else null end as open_price,
        case when high_price > 0 then high_price else null end as high_price,
        case when low_price > 0 then low_price else null end as low_price,
        case when close_price > 0 then close_price else null end as close_price,
        
        -- Ensure volume is non-negative
        case when volume >= 0 then volume else null end as volume,
        
        -- Convert percentage to decimal
        daily_return_pct / 100.0 as daily_return,
        volatility_30d / 100.0 as volatility_30d,
        
        'bloomberg' as data_source,
        created_at,
        updated_at
        
    from source_data
),

validated_data as (
    select *
    from cleaned_data
    where 
        symbol is not null
        and trade_date is not null
        and close_price is not null
        -- Ensure high >= low and other basic validations
        and (high_price is null or low_price is null or high_price >= low_price)
        -- Remove obvious outliers (price changes > 50% in a day)
        and (daily_return is null or abs(daily_return) <= 0.5)
)

select * from validated_data