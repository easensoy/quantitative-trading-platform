{{ config(materialized='table') }}

with daily_returns as (
    select 
        symbol,
        trade_date,
        close_price,
        daily_return,
        volume,
        data_source
    from {{ ref('equity_prices') }}
    where daily_return is not null
      and trade_date >= current_date - interval '2 years'
),

volatility_metrics as (
    select 
        symbol,
        trade_date,
        close_price,
        daily_return,
        stddev(daily_return) over (
            partition by symbol 
            order by trade_date 
            rows between 29 preceding and current row
        ) * sqrt(252) as volatility_30d,
        stddev(daily_return) over (
            partition by symbol 
            order by trade_date 
            rows between 89 preceding and current row
        ) * sqrt(252) as volatility_90d,
        stddev(daily_return) over (
            partition by symbol 
            order by trade_date 
            rows between 251 preceding and current row
        ) * sqrt(252) as volatility_1y,
        avg(daily_return) over (
            partition by symbol 
            order by trade_date 
            rows between 29 preceding and current row
        ) * 252 as avg_return_30d_annualized,
        
        avg(daily_return) over (
            partition by symbol 
            order by trade_date 
            rows between 251 preceding and current row
        ) * 252 as avg_return_1y_annualized
        
    from daily_returns
),

drawdown_metrics as (
    select 
        symbol,
        trade_date,
        close_price,
        daily_return,
        max(close_price) over (
            partition by symbol 
            order by trade_date 
            rows unbounded preceding
        ) as running_max_price,
        (close_price - max(close_price) over (
            partition by symbol 
            order by trade_date 
            rows unbounded preceding
        )) / max(close_price) over (
            partition by symbol 
            order by trade_date 
            rows unbounded preceding
        ) as current_drawdown
        
    from daily_returns
),

var_metrics as (
    select 
        symbol,
        trade_date,
        percentile_cont(0.05) within group (order by daily_return) over (
            partition by symbol 
            order by trade_date 
            rows between 251 preceding and current row
        ) as var_95_1y,
        percentile_cont(0.01) within group (order by daily_return) over (
            partition by symbol 
            order by trade_date 
            rows between 251 preceding and current row
        ) as var_99_1y,
        avg(case when daily_return <= percentile_cont(0.05) within group (order by daily_return) over (
            partition by symbol 
            order by trade_date 
            rows between 251 preceding and current row
        ) then daily_return else null end) over (
            partition by symbol 
            order by trade_date 
            rows between 251 preceding and current row
        ) as expected_shortfall_95
        
    from daily_returns
),

market_data as (
    select 
        trade_date,
        daily_return as market_return
    from daily_returns
    where symbol = 'SPY'
),

beta_calculations as (
    select 
        dr.symbol,
        dr.trade_date,
        dr.daily_return,
        md.market_return,
        case 
            when var(md.market_return) over (
                partition by dr.symbol
                order by dr.trade_date
                rows between 251 preceding and current row
            ) > 0 then
                covar_samp(dr.daily_return, md.market_return) over (
                    partition by dr.symbol
                    order by dr.trade_date
                    rows between 251 preceding and current row
                ) / var(md.market_return) over (
                    partition by dr.symbol
                    order by dr.trade_date
                    rows between 251 preceding and current row
                )
            else null
        end as beta_1y,
        power(corr(dr.daily_return, md.market_return) over (
            partition by dr.symbol
            order by dr.trade_date
            rows between 251 preceding and current row
        ), 2) as r_squared_1y
        
    from daily_returns dr
    left join market_data md on dr.trade_date = md.trade_date
    where dr.symbol != 'SPY'
),

combined_risk_metrics as (
    select 
        vm.symbol,
        vm.trade_date,
        vm.close_price,
        vm.daily_return,
        vm.volatility_30d,
        vm.volatility_90d,
        vm.volatility_1y,
        vm.avg_return_30d_annualized,
        vm.avg_return_1y_annualized,
        case 
            when vm.volatility_1y > 0 then (vm.avg_return_1y_annualized - 0.02) / vm.volatility_1y
            else null
        end as sharpe_ratio_1y,
        dm.current_drawdown,
        min(dm.current_drawdown) over (
            partition by dm.symbol
            order by dm.trade_date
            rows between 251 preceding and current row
        ) as max_drawdown_1y,
        vr.var_95_1y,
        vr.var_99_1y,
        vr.expected_shortfall_95,
        bc.beta_1y,
        bc.r_squared_1y,
        case 
            when stddev(vm.daily_return - coalesce(bc.market_return, 0)) over (
                partition by vm.symbol
                order by vm.trade_date
                rows between 251 preceding and current row
            ) > 0 then
                (vm.avg_return_1y_annualized - avg(coalesce(bc.market_return, 0) * 252) over (
                    partition by vm.symbol
                    order by vm.trade_date
                    rows between 251 preceding and current row
                )) / (stddev(vm.daily_return - coalesce(bc.market_return, 0)) over (
                    partition by vm.symbol
                    order by vm.trade_date
                    rows between 251 preceding and current row
                ) * sqrt(252))
            else null
        end as information_ratio_1y
        
    from volatility_metrics vm
    left join drawdown_metrics dm on vm.symbol = dm.symbol and vm.trade_date = dm.trade_date
    left join var_metrics vr on vm.symbol = vr.symbol and vm.trade_date = vr.trade_date
    left join beta_calculations bc on vm.symbol = bc.symbol and vm.trade_date = bc.trade_date
),

final_risk_metrics as (
    select 
        *,
        case
            when volatility_1y <= 0.15 then 'low'
            when volatility_1y <= 0.25 then 'medium'
            when volatility_1y <= 0.40 then 'high'
            when volatility_1y > 0.40 then 'very_high'
            else 'unknown'
        end as volatility_category,
        case
            when beta_1y < 0.8 then 'defensive'
            when beta_1y <= 1.2 then 'market'
            when beta_1y > 1.2 then 'aggressive'
            else 'unknown'
        end as beta_category,
        case
            when sharpe_ratio_1y >= 1.0 then 'excellent'
            when sharpe_ratio_1y >= 0.5 then 'good'
            when sharpe_ratio_1y >= 0.0 then 'fair'
            when sharpe_ratio_1y < 0.0 then 'poor'
            else 'unknown'
        end as sharpe_category,
        least(100, greatest(0,
            coalesce(volatility_1y * 100, 0) * 0.3 +
            coalesce(abs(max_drawdown_1y) * 100, 0) * 0.3 +
            coalesce(abs(var_95_1y) * 100, 0) * 0.2 +
            coalesce(case when beta_1y > 1 then (beta_1y - 1) * 50 else 0 end, 0) * 0.2
        )) as risk_score,
        
        current_timestamp() as calculated_at
        
    from combined_risk_metrics
)

select * from final_risk_metrics
where trade_date = (select max(trade_date) from final_risk_metrics)