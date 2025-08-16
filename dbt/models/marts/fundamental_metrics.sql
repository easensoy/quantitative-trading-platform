{{ config(materialized='table') }}

with bloomberg_fundamentals as (
    select 
        case 
            when security like '% Equity' then left(security, position(' Equity' in security) - 1)
            else security
        end as symbol,
        
        sales_rev_turn as revenue,
        net_income,
        tot_debt_to_tot_eqy as debt_to_equity,
        return_on_asset as roa,
        return_on_equity as roe, 
        pe_ratio,
        px_to_book_ratio as price_to_book,
        free_cash_flow,
        ebitda,
        market_cap,
        beta_adj_overridable as beta,
        'bloomberg' as data_source,
        created_at,
        updated_at
        
    from {{ source('bloomberg', 'fundamental_data') }}
    where security is not null
),

factset_fundamentals as (
    select
        case 
            when id like '%-USA' then left(id, position('-USA' in id) - 1)
            else id
        end as symbol,
        
        ff_sales as revenue,
        ff_net_inc as net_income,
        null as debt_to_equity,
        ff_roa as roa,
        ff_roe as roe,
        null as pe_ratio,
        null as price_to_book,
        ff_cf_free as free_cash_flow,
        null as ebitda,
        null as market_cap,
        null as beta,
        'factset' as data_source,
        created_at,
        updated_at
        
    from {{ source('factset', 'fundamentals_data') }}
    where id is not null
),

refinitiv_fundamentals as (
    select
        case 
            when instrument like '%.O' then left(instrument, position('.O' in instrument) - 1)
            when instrument like '%.N' then left(instrument, position('.N' in instrument) - 1)
            else instrument
        end as symbol,
        
        tr_revenue as revenue,
        tr_netincome as net_income,
        tr_debttotoequity as debt_to_equity,
        tr_roa as roa,
        tr_roe as roe,
        tr_peratio as pe_ratio,
        tr_pricetobookvalue as price_to_book,
        null as free_cash_flow,
        null as ebitda,
        tr_marketcap as market_cap,
        tr_beta as beta,
        'refinitiv' as data_source,
        created_at,
        updated_at
        
    from {{ source('refinitiv', 'company_data') }}
    where instrument is not null
),

combined_fundamentals as (
    select * from bloomberg_fundamentals
    union all
    select * from factset_fundamentals
    union all
    select * from refinitiv_fundamentals
),

scored_fundamentals as (
    select 
        *,
        (
            case when revenue is not null then 0.15 else 0 end +
            case when net_income is not null then 0.15 else 0 end +
            case when debt_to_equity is not null then 0.1 else 0 end +
            case when roa is not null then 0.1 else 0 end +
            case when roe is not null then 0.1 else 0 end +
            case when pe_ratio is not null then 0.1 else 0 end +
            case when price_to_book is not null then 0.1 else 0 end +
            case when free_cash_flow is not null then 0.1 else 0 end +
            case when market_cap is not null then 0.1 else 0 end +
            case when beta is not null then 0.05 else 0 end
        ) as completeness_score,
        case data_source
            when 'bloomberg' then 1
            when 'factset' then 2
            when 'refinitiv' then 3
        end as source_priority
        
    from combined_fundamentals
),

deduplicated_fundamentals as (
    select 
        symbol,
        revenue,
        net_income,
        debt_to_equity,
        roa,
        roe,
        pe_ratio,
        price_to_book,
        free_cash_flow,
        ebitda,
        market_cap,
        beta,
        data_source,
        completeness_score,
        created_at,
        updated_at,
        
        row_number() over (
            partition by symbol
            order by completeness_score desc, source_priority asc, updated_at desc
        ) as rank
        
    from scored_fundamentals
),

enriched_fundamentals as (
    select 
        symbol,
        revenue,
        net_income,
        debt_to_equity,
        roa,
        roe,
        pe_ratio,
        price_to_book,
        free_cash_flow,
        ebitda,
        market_cap,
        beta,
        case 
            when revenue > 0 and net_income is not null then net_income / revenue
            else null
        end as net_margin,
        
        case
            when market_cap > 0 and revenue is not null then market_cap / revenue
            else null
        end as price_to_sales,
        
        case
            when free_cash_flow > 0 and market_cap is not null then market_cap / free_cash_flow
            else null
        end as price_to_fcf,
        
        case
            when debt_to_equity is not null then 1 / (1 + debt_to_equity)
            else null
        end as equity_ratio,
        case
            when revenue > 0 and net_income > 0 then 'profitable'
            when revenue > 0 and net_income <= 0 then 'unprofitable'
            else 'insufficient_data'
        end as profitability_status,
        
        case
            when roe is not null and roe >= 0.15 then 'high'
            when roe is not null and roe >= 0.10 then 'medium'
            when roe is not null and roe >= 0.05 then 'low'
            when roe is not null then 'poor'
            else 'unknown'
        end as roe_category,
        
        case
            when debt_to_equity is not null and debt_to_equity <= 0.3 then 'low'
            when debt_to_equity is not null and debt_to_equity <= 0.6 then 'medium'
            when debt_to_equity is not null and debt_to_equity <= 1.0 then 'high'
            when debt_to_equity is not null then 'very_high'
            else 'unknown'
        end as leverage_category,
        
        data_source,
        completeness_score,
        created_at as source_created_at,
        current_timestamp() as processed_at
        
    from deduplicated_fundamentals
    where rank = 1
)

select * from enriched_fundamentals