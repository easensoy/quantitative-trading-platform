{{ config(materialized='view') }}

with source_data as (
    select 
        id as factset_id,
        date,
        price_open as open_price,
        price_high as high_price,
        price_low as low_price,
        price_close as close_price,
        volume,
        total_return,
        created_at,
        updated_at
    from {{ source('factset', 'prices_data') }}
),

cleaned_data as (
    select 
        -- Extract symbol from FactSet ID (e.g., 'AAPL-USA' -> 'AAPL')
        case 
            when factset_id like '%-USA' then left(factset_id, position('-USA' in factset_id) - 1)
            else factset_id
        end as symbol,
        
        date::date as trade_date,
        
        -- Clean price data
        case when open_price > 0 then open_price else null end as open_price,
        case when high_price > 0 then high_price else null end as high_price,
        case when low_price > 0 then low_price else null end as low_price,
        case when close_price > 0 then close_price else null end as close_price,
        
        -- Clean volume data
        case when volume >= 0 then volume else null end as volume,
        
        -- Calculate daily return from total return if not provided
        total_return as daily_return,
        
        'factset' as data_source,
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