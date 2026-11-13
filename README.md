# Quantitative Trading Platform

This repository contains two Python applications and some older infrastructure:

- **Trading engine** (`src/`, `main.py`, `run.py`): an asyncio application that streams
  market data, runs strategies, checks risk, simulates execution and keeps a portfolio.
  It also has a bar-by-bar backtesting engine. **Execution is always simulated.** No
  code path connects to a broker, and the `live` mode name does not change that.
- **Django project** (`quantcore/`, `apps/`): PostgreSQL models, a REST API, admin,
  Celery tasks and management commands for accounts, orders, positions and market data.
- **Legacy stack** (`airflow/`, `dbt/`, `config/*.sql`, `src/data/*_connector.py`,
  `src/ml/`): the original Airflow/dbt/warehouse pipeline that the Django project was
  meant to replace (see `README_DJANGO_MIGRATION.md`). It is not part of the verified setup.

The engine and the Django project are independent. Neither imports the other, they keep
separate configuration, and they share no runtime state. Use the engine for simulation
and backtests, and Django for persistence and the HTTP API.

## Component status

Status as of the November 2026 audit, on Windows 11 with Python 3.11.14.
"Verified" means the component was run and its behaviour checked; "implemented" means
the code exists but was not exercised, usually because it needs an external service.

| Component | Status | Evidence / notes |
| --- | --- | --- |
| Engine core: models, config, DI container, in-memory event bus | Verified | `tests/unit` |
| Simulated market data, order execution, portfolio and risk services | Verified | Tests, plus bounded `live` and `service` runs |
| Pre-trade risk check (orchestrator and strategy orders) | Verified | `tests/unit/test_trading_flow.py` |
| Backtest engine and synthetic example (`MODE=backtest`) | Verified | `tests/unit/test_backtest_engine.py` |
| Fixed-income / commodity models, multi-asset risk | Verified | Existing unit tests |
| Django settings, URLs, admin, REST API, token and session auth | Verified | System checks, 45 Django tests, dev-server smoke test |
| Migrations for `market_data` and `trading` | Verified | Applied on SQLite and on a PostgreSQL 15 instance |
| `calculate_risk_metrics`, `data_quality_check` commands | Verified | Run on synthetic bars stored in the database |
| Celery task bodies | Verified (eager mode) | Tests run them without a broker |
| Celery beat | Starts | Loads the schedule; sending tasks needs Redis |
| Celery worker | Blocked: needs Redis | Starts, then `Cannot connect to redis://localhost:6379/0` |
| `load_market_data`, `fetch_market_data_task`, engine `yahoo` provider | Implemented, not verified | Need internet access and yfinance |
| `EVENT_BUS_TYPE=redis` (engine) | Incomplete | Events are not JSON serializable, and subscribers would get dicts, not objects |
| `daily_market_data_pipeline`, `weekly_comprehensive_analysis` tasks | Incomplete | Call `.get()` on subtasks inside a task; a real worker forbids this by default |
| Engine VaR, beta and daily-loss checks | Placeholder | Random numbers / always pass (`BasicRiskManager`, `RiskService`) |
| Channels / WebSockets | Configured only | No consumers or routes |
| Django apps `portfolio`, `risk`, `strategies`, `backtesting`, `ml`, `monitoring` | Not implemented | Never existed; removed from `INSTALLED_APPS` |
| Airflow DAGs, dbt models, vendor connectors, `src/ml` | Not verified | See [Legacy stack](#legacy-stack) |

## Architecture

### Trading engine

`TradingApplicationService` (`src/services/application_service.py`) builds one event
bus and five services, registers them in `ServiceRegistry` and wires them together.
`TradingOrchestrator` (`src/core/orchestrator.py`) is the facade used by `main.py`.

```text
MarketDataService ──"market_data"──► StrategyService ──orders──► OrderExecutionService
  polls the provider,                 runs the active             │ 1. pre-trade check:
  caches latest quotes                strategy handlers           │    RiskService.validate_order
                                                                  ▼ 2. submit
                                              BasicOrderExecutionEngine (simulated fill)
                                                                  │ "order_filled"
                                                                  ▼
                                 OrderExecutionService ──fill──► PortfolioService
                                                                  │ positions + cash
                                                                  ▼ "position_updated"
                                                    RiskService.monitor_risk_limits
```

- **Market data.** `MarketDataService` is the only publisher of `market_data` events.
  Providers (`SimulatedMarketDataProvider`, `YahooFinanceDataProvider`) are pull-only.
- **Risk before submission.** Every order goes through
  `OrderExecutionService.submit_order`, which runs the registered pre-trade checks
  first. A rejected order is marked `REJECTED`, never reaches the engine and creates a
  risk alert. This applies equally to strategy orders and `TradingOrchestrator.submit_order`.
- **Fills.**
  - Market and stop orders fill at the latest quote, moved by the configured slippage.
  - Limit orders fill at the limit price or better.
  - Resting orders and partial fills are not modelled.
- **Accounting.** `Portfolio.apply_fill` is used by both the live services and the
  backtester:
  - Buys spend notional plus commission; sells receive notional minus commission.
  - A partial close keeps the position's average cost.
- **Lifecycle.** `initialize()` creates the services and subscribes them to the bus.
  `start()` begins streaming and blocks until `stop()` is called. Default instruments
  and strategies are installed only when none were configured.

### Backtesting

`BacktestEngine` (`src/backtesting/engine.py`) replays daily bars. Orders that a
strategy returns on bar *t* fill on bar *t+1* for the same symbol, at the close plus
slippage. Fills move cash and positions, commissions included. There are no margin or
risk checks in backtests. `src/backtesting/synthetic.py` generates deterministic,
internally consistent OHLCV data for the example and the tests.

### Django project

- `apps.market_data`: providers, instruments, OHLCV bars, technical indicators,
  fundamentals, risk metrics and data-quality checks. It also holds the Celery tasks
  and three management commands.
- `apps.trading`: user-owned trading accounts, strategies, orders, trades, positions,
  portfolio snapshots and backtest results.
- REST API under `/api/v1/`, OpenAPI schema under `/api/schema/`.
- Every endpoint requires authentication (session or `Authorization: Token <key>`).
- Users only see and write their own accounts, strategies and orders.

## Prerequisites

- Windows 10/11 with PowerShell. Keep the checkout, `.venv` and generated files outside
  OneDrive (this repository lives in `C:\Users\alper\Documents`, which is not synced).
- **Python 3.11.** The pinned packages (for example numpy 1.24.3 and scikit-learn
  1.3.0) have no wheels for Python 3.12 or later.
- For the full Django stack:
  - PostgreSQL 12 or later (verified with 15).
  - Redis 6 or later, for the cache, the Celery broker and result backend, and Channels.

  Without them, Django still runs on SQLite with a local-memory cache.

## Setup (Windows PowerShell)

```powershell
Set-Location C:\Users\alper\Documents\quantitative-trading-platform

# Create a Python 3.11 virtual environment in .venv (uv downloads 3.11 if needed).
uv venv --python 3.11 --seed .venv
# Alternative with a python.org 3.11 install:  py -3.11 -m venv .venv

.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements_dev.txt
```

If PowerShell refuses to run `Activate.ps1`, call `.\.venv\Scripts\python.exe` instead
of `python` in the commands below.

Management commands print emoji. That works in an interactive console, but if you
redirect or pipe their output, set `$env:PYTHONUTF8 = "1"` first. Otherwise Windows uses
the cp1252 encoding and the command fails with `UnicodeEncodeError`.

## Configuration

- **Django** reads `.env` in the repository root. Create it from the template
  (`Copy-Item .env.example .env`) and edit it; `.env` is ignored by Git. The variables
  that matter most:
  - `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: PostgreSQL connection.
  - `DATABASE_URL`: optional; replaces the `DB_*` settings, e.g. `sqlite:///db.sqlite3`.
  - `CACHE_BACKEND`: `redis` (default) or `locmem`. DRF throttling reads the cache on
    every API request, so use `locmem` when Redis is not running.
  - `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `REDIS_URL`: Redis locations.
  - `LOG_DIR`: where `quantcore.log` is written; defaults to `logs/`, created on startup.
- **The engine does not read `.env`.** It reads process environment variables in
  `src/core/config.py` each time a config is created:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MODE` | `live` | `live`, `service` or `backtest` |
| `MARKET_DATA_PROVIDER` | `simulated` | `simulated` or `yahoo` |
| `EVENT_BUS_TYPE` | `memory` | `memory`; `redis` is incomplete |
| `INITIAL_CAPITAL` | `1000000` | Starting cash for the portfolio |
| `MAX_POSITION_SIZE` | `1000000` | Largest absolute share quantity per symbol allowed by the pre-trade check |
| `DEFAULT_COMMISSION` | `0.001` | Commission rate on simulated fills |
| `SIMULATION_SEED` | unset | Fixes the simulated price sequence |
| `MARKET_DATA_POLL_INTERVAL` | `1.0` | Seconds between quote polls |
| `RUN_DURATION_SECONDS` | unset | Stop `live`/`service` mode after this many seconds |

## Run the trading engine

All runs below use synthetic data and simulated execution.

```powershell
# Backtest: one year of seeded synthetic AAPL bars.
$env:MODE = "backtest"
python run.py
```

The backtest output is deterministic:

```text
Backtest Results:
Total Return: -0.06%
Sharpe Ratio: -40.03
Max Drawdown: -0.09%
Total Trades: 2
Final Capital: $999,397.42
```

The example strategy only ever holds 100 shares of a $1M portfolio, which explains
the large negative Sharpe ratio: equity barely moves, so volatility is close to zero.

```powershell
# Live mode: main.py's two strategies on AAPL, GOOGL, MSFT; stops after 30 seconds.
$env:MODE = "live"; $env:SIMULATION_SEED = "7"; $env:RUN_DURATION_SECONDS = "30"
python run.py

# Service mode: built-in default instruments and strategies; Ctrl+C to stop.
Remove-Item Env:RUN_DURATION_SECONDS -ErrorAction SilentlyContinue
$env:MODE = "service"
python run.py
```

`live` and `service` print a session summary when they stop. It shows portfolio value,
cash, positions, and how many orders were submitted, filled and rejected. Set
`MAX_POSITION_SIZE` low (for example `15` in service mode) to watch the risk check
reject orders.

## Run the Django project

### Quick start without PostgreSQL or Redis

In `.env`, set `DATABASE_URL=sqlite:///db.sqlite3` and `CACHE_BACKEND=locmem`, then:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### With PostgreSQL and Redis

1. Create the database. Use your PostgreSQL superuser, or a role allowed to create
   databases; `createdb` prompts for its password:

   ```powershell
   & "C:\Program Files\PostgreSQL\15\bin\createdb.exe" -h localhost -U postgres quantcore
   ```

2. Put the same credentials in `.env` (`DB_USER`, `DB_PASSWORD`). Leave `DATABASE_URL`
   unset.
3. Start Redis. It has no native Windows build; one option is Docker Desktop:

   ```powershell
   docker run -d --name quantcore-redis -p 6379:6379 redis:7
   ```

   WSL (`sudo apt install redis-server`) or Memurai also work.
4. Migrate and start the services, each in its own terminal with the venv activated:

   ```powershell
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver
   ```

   ```powershell
   celery -A quantcore worker --loglevel=info --pool=solo
   ```

   ```powershell
   celery -A quantcore beat --loglevel=info
   ```

   Celery's default process pool does not work on Windows, hence `--pool=solo`. Beat
   writes `celerybeat-schedule*` files to the current directory; they are git-ignored.

Endpoints (after `runserver`):

- Admin: <http://127.0.0.1:8000/admin/>
- Swagger UI: <http://127.0.0.1:8000/api/docs/>; ReDoc: `/api/redoc/`; schema: `/api/schema/`
- Trading: `/api/v1/accounts/`, `/strategies/`, `/orders/` (plus `orders/create_order/`
  and `orders/{id}/cancel/`), `/positions/`, `/trades/`, `/backtests/`
- Market data: `/api/v1/market-data/instruments/`, `/market-data/`, `/risk-metrics/`, `/providers/`

For API tokens, create one in the admin (*Auth Token > Tokens*). Then send
`Authorization: Token <key>` with each request.

Management commands:

```powershell
python manage.py calculate_risk_metrics [--symbols AAPL,MSFT] [--force-recalculate]
python manage.py data_quality_check [--provider yfinance] [--fail-on-error]
python manage.py load_market_data --symbols AAPL,MSFT --days-back 30   # needs internet (yfinance)
```

The data-quality *timeliness* check passes only when the newest bar is less than about
5 hours old, so it fails on data that is a day old.

## Tests

```powershell
python -m pytest                      # 110 tests: engine + Django, no external services
python -m pytest tests/unit           # engine only (works with requirements_engine.txt)
python -m pytest tests/django_tests   # Django only
```

The Django tests use `quantcore/settings_test.py`, which sets up in-memory SQLite, a
local-memory cache and eager Celery. To run them on PostgreSQL instead, use a role that
may create databases:

```powershell
$env:TEST_DATABASE_URL = "postgres://USER:PASSWORD@localhost:5432/quantcore"
python -m pytest tests/django_tests
```

The tests are deterministic. They use seeded synthetic prices, publish quotes directly
on the event bus and fill orders without delay. Nothing touches live market data or the
network.

## Dependency manifests

| File | Stack | Status |
| --- | --- | --- |
| `requirements_dev.txt` | Engine + Django + test tools; the complete local environment | Installs cleanly on Python 3.11; `pip check` passes |
| `requirements_engine.txt` | Engine runtime and pytest only | Subset of the above |
| `requirements_django.txt` | Django, DRF, Celery, Channels, data libraries | Installs; fixed `QuantLib` name; added `django-redis` and a `kombu` pin |
| `requirements.txt` | Legacy stack: Airflow, MySQL/ClickHouse, OpenAI/LangChain/FAISS, ... | Does not resolve as pinned (see below) |
| `pyproject.toml` | Version ranges: engine runtime as `dependencies`; `django`, `dev`, `legacy` extras; pytest settings | Not a lock: install from the requirements files |

Only top-level packages are pinned; transitive versions float. That bit this audit once:
pip picked kombu 5.7, which refuses the pinned redis 4.6. For fully reproducible
installs, generate a constraints file from a known-good environment with `pip freeze`.

## Legacy stack

These parts were not verified and are not installed by `requirements_dev.txt`:

- `requirements.txt` cannot be installed as pinned. pip reports `ResolutionImpossible`:
  `apache-airflow==2.7.0` requires `opentelemetry-api==1.15.0`, but the file pins
  `1.19.0`. Airflow should be installed with its official constraints file.
- `airflow/dags/` and `dbt/` are the original pipeline definitions. Their Django
  replacements are the Celery tasks and management commands in `apps/market_data`.
- Engine modules that still fail to import:
  - `src/data/loaders.py`, `bloomberg_connector.py`, `factset_connector.py`: need
    `mysql-connector-python`.
  - `snowflake_connector.py`, `refinitiv_connector.py`: need their vendor SDKs.
  - `databricks_connector.py`: has an f-string that is a SyntaxError before Python 3.12.
  - `src/ml/alpha_research.py`: imports `sklearn.metrics.information_score`, which does
    not exist.

## Known limitations

- `EVENT_BUS_TYPE=redis` cannot publish engine events. `json.dumps` fails on enums and
  datetimes, and subscribers would receive plain dicts instead of the objects they expect.
- In engine risk, `BasicRiskManager.calculate_risk_metrics` VaR and `RiskService` beta use
  random numbers, the daily-loss check always passes, and the periodic monitoring loop
  only sleeps. The pre-trade limits are real: position quantity and leverage, with
  market orders priced at the latest quote.
- `MAX_POSITION_SIZE` is an absolute share quantity in the engine. Django's
  `TradingAccount.max_position_size` is a separate, unused money field.
- `ParameterOptimizer` runs its backtests concurrently on one engine, which is not safe;
  it is untested.
- `daily_market_data_pipeline` and `weekly_comprehensive_analysis` wait on subtask
  results inside a task, which a real Celery worker rejects. They need rewriting as
  chains.
