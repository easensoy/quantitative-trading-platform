{{ config(materialized='view') }}

with source_data as (
    select 
        instrument,
        date,
        tr_openprice as open_price,
        tr_highprice as high_price,
        tr_lowprice as low_price,
        tr_closeprice as close_price,
        tr_volume as volume,
        tr_pctchg as daily_return_pct,
        tr_volatility30d as volatility_30d,
        created_at,
        updated_at
    from {{ source('refinitiv', 'equity_data') }}
),

cleaned_data as (
    select 
        -- Extract symbol from RIC (e.g., 'AAPL.O' -> 'AAPL')
        case 
            when instrument like '%.O' then left(instrument, position('.O' in instrument) - 1)
            when instrument like '%.N' then left(instrument, position('.N' in instrument) - 1)  
            when instrument like '%.K' then left(instrument, position('.K' in instrument) - 1)
            else instrument
        end as symbol,
        
        date::date as trade_date,
        
        -- Clean price data
        case when open_price > 0 then open_price else null end as open_price,
        case when high_price > 0 then high_price else null end as high_price,
        case when low_price > 0 then low_price else null end as low_price,
        case when close_price > 0 then close_price else null end as close_price,
        
        -- Clean volume data
        case when volume >= 0 then volume else null end as volume,
        
        -- Convert percentage to decimal
        daily_return_pct / 100.0 as daily_return,
        volatility_30d / 100.0 as volatility_30d,
        
        'refinitiv' as data_source,
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
        -- Basic validation rules
        and (high_price is null or low_price is null or high_price >= low_price)
        and (daily_return is null or abs(daily_return) <= 0.5)
)

select * from validated_data