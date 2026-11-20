# Development guide

Setup, configuration and commands for every part of the repository, plus the full
component status. The [README](../README.md) has the overview; [methodology.md](methodology.md)
defines the research metrics.

## Repository layout

| Path | What it is |
| --- | --- |
| `src/core`, `src/services`, `main.py`, `run.py` | Trading engine: an asyncio application with event bus, market data, strategies, pre-trade risk, simulated execution and portfolio |
| `src/backtesting` | Bar-by-bar backtester with a per-bar ledger, order log and simulated broker |
| `src/research` | Datasets (synthetic generator and loader), the demonstration strategy, isolated experiment runs, walk-forward, benchmarks, the showcase pipeline and its checks |
| `src/analytics` | Pure calculations on pandas objects: performance, drawdowns, distribution, exposure, attribution, trades, bootstrap, capacity |
| `src/reporting` | Figure theme, the eleven figures, Markdown report, manifest and README blocks |
| `scripts/` | `generate_readme_assets.py` (figures and report), `capture_api_screenshots.py` (API screenshot) |
| `quantcore/`, `apps/` | Django project: models, REST API, admin, Celery tasks, management commands |
| `data/demo/` | The synthetic demo dataset with its manifest and checksums |
| `docs/` | This guide, the methodology, figures (`assets/`) and the generated report (`reports/`) |
| `airflow/`, `dbt/`, `config/*.sql`, `src/data/*_connector.py`, `src/ml/` | Legacy stack, not verified (see [Legacy stack](#legacy-stack)) |

The engine and the Django project are independent. Neither imports the other, they keep
separate configuration, and they share no runtime state. The research pipeline runs on the
engine's backtester. Django only stores its published results, through
`import_backtest_report`.

## Component status

Status as of November 2026, on Windows 11 with Python 3.11.14. "Verified" means the
component was run and its behaviour checked. "Implemented" means the code exists but was
not exercised, usually because it needs an external service.

| Component | Status | Evidence / notes |
| --- | --- | --- |
| Engine core: models, config, DI container, in-memory event bus | Verified | `tests/unit` |
| Simulated market data, order execution, portfolio and risk services | Verified | Tests, plus bounded `live` and `service` runs |
| Pre-trade risk check (orchestrator and strategy orders) | Verified | `tests/unit/test_trading_flow.py` |
| Backtest engine: next-bar fills, ledger, order log, carried-forward marks | Verified | `tests/unit/test_backtest_engine.py`, ledger identity check |
| Research pipeline: sweep, walk-forward, bootstrap, capacity, 13 consistency checks | Verified | `tests/unit/test_research_analytics.py`, every generator run |
| Report figures, Markdown report, manifest, README blocks | Verified | Generated headless; every image inspected in both themes |
| Fixed-income / commodity models, multi-asset risk | Verified | Existing unit tests |
| Django settings, URLs, admin, REST API, token and session auth | Verified | System checks, Django tests, dev-server runs |
| `import_backtest_report` and the API screenshot | Verified | `tests/django_tests/test_import_backtest_report.py`; `capture_api_screenshots.py` on Edge |
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

## Prerequisites

- **Python 3.11.** The pinned packages (for example numpy 1.24.3 and scikit-learn 1.3.0)
  have no wheels for Python 3.12 or later.
- **On Windows,** keep the checkout, `.venv` and generated files outside OneDrive. Sync
  locks files while the generator and the tests write them.
- **For the API screenshot:** Microsoft Edge or Google Chrome. `SCREENSHOT_BROWSER` can
  point to another Chromium-based browser.
- **For the full Django stack:**
  - PostgreSQL 12 or later (verified with 15).
  - Redis 6 or later, for the cache, the Celery broker and result backend, and Channels.

  Without them, Django still runs on SQLite with a local-memory cache.

## Setup (Windows PowerShell)

```powershell
Set-Location <path-to-your-checkout>

# Create a Python 3.11 virtual environment in .venv (uv downloads 3.11 if needed).
uv venv --python 3.11 --seed .venv
# Alternative with a python.org 3.11 install:  py -3.11 -m venv .venv

.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements_dev.txt
```

On macOS or Linux, activate with `source .venv/bin/activate`; the other commands are the same.

If PowerShell refuses to run `Activate.ps1`, call `.\.venv\Scripts\python.exe` instead of
`python` in the commands below.

Management commands print emoji. That works in an interactive console. If you redirect or
pipe their output, set `$env:PYTHONUTF8 = "1"` first; otherwise Windows uses the cp1252
encoding and the command fails with `UnicodeEncodeError`.

## Configuration

- **Django** reads `.env` in the repository root. Create it from the template
  (`Copy-Item .env.example .env`) and edit it; `.env` is ignored by Git. The variables that
  matter most:
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

The example strategy only ever holds 100 shares of a $1M portfolio, so equity barely moves
and volatility is close to zero, which explains the large negative Sharpe ratio. These
metrics come from the engine's original `PerformanceAnalyzer` (252 periods, 2% risk-free
rate) and are not comparable with the research reports; see
[methodology.md](methodology.md#the-quick-example-uses-older-conventions).

```powershell
# Live mode: main.py's two strategies on AAPL, GOOGL, MSFT; stops after 30 seconds.
$env:MODE = "live"; $env:SIMULATION_SEED = "7"; $env:RUN_DURATION_SECONDS = "30"
python run.py

# Service mode: built-in default instruments and strategies; Ctrl+C to stop.
Remove-Item Env:RUN_DURATION_SECONDS -ErrorAction SilentlyContinue
$env:MODE = "service"
python run.py
```

`live` and `service` print a session summary when they stop: portfolio value, cash,
positions, and how many orders were submitted, filled and rejected. Set `MAX_POSITION_SIZE`
low (for example `15` in service mode) to watch the risk check reject orders.

## Research reports and figures

```powershell
python scripts/generate_readme_assets.py                      # everything, about 2 minutes
python scripts/generate_readme_assets.py --reuse-engineering  # keep stored benchmarks, about 1 minute
python scripts/generate_readme_assets.py --only tearsheet,walk-forward --themes dark
python scripts/generate_readme_assets.py --regenerate-dataset # rebuild data/demo from its specification
python scripts/generate_readme_assets.py --dataset D:\data\my_universe --assets-dir build\report\assets --reports-dir build\report
python scripts/generate_readme_assets.py --help
```

The generator runs headless (matplotlib's Agg backend). It writes files with stable names:

- `docs/assets/<figure>-dark.png` and `<figure>-light.png`
- `docs/reports/showcase.md`
- `docs/reports/showcase/`: `manifest.json`, CSV tables and `engineering.json`
- the generated blocks in `README.md`, between `<!-- showcase:NAME:start -->` and
  `<!-- showcase:NAME:end -->`, for the default dataset only

It exits with code 1, and writes nothing, if a [consistency check](methodology.md#consistency-checks-srcresearchshowcasepy)
fails. `--jobs N` runs the sweep and walk-forward in N processes; the results do not depend
on it.

The API screenshot runs against a throwaway database:

```powershell
python scripts/capture_api_screenshots.py
```

1. It migrates a temporary SQLite database and creates a `demo` user without a password.
2. It imports `docs/reports/showcase` with `import_backtest_report`.
3. It starts the development server on a free port.
4. It drives headless Edge or Chrome through the DevTools protocol, with a session created
   for the demo user, and saves `docs/assets/screenshots/api-backtest-detail.png`.
5. It fails on an HTTP error or a browser console error. The server, the browser and the
   database are removed afterwards.

## Run the Django project

### Quick start without PostgreSQL or Redis

In `.env`, set `DATABASE_URL=sqlite:///db.sqlite3` and `CACHE_BACKEND=locmem`, then:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py import_backtest_report docs/reports/showcase --username <your-user>
python manage.py runserver
```

`import_backtest_report` stores the published research run as a `BacktestResult`:
- Nothing is recalculated. The row holds the report's numbers, and its metadata keeps the
  run id, dataset checksum, execution model and evidence category.
- Importing the same run again updates the row.

Open `/api/v1/backtests/` to see it.

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
   writes `celerybeat-schedule*` files to the current directory; they are ignored by Git.

Endpoints (after `runserver`):

- Admin: <http://127.0.0.1:8000/admin/>
- Swagger UI: <http://127.0.0.1:8000/api/docs/>; ReDoc: `/api/redoc/`; schema: `/api/schema/`
- Trading: `/api/v1/accounts/`, `/strategies/`, `/orders/` (plus `orders/create_order/` and
  `orders/{id}/cancel/`), `/positions/`, `/trades/`, `/backtests/`
- Market data: `/api/v1/market-data/instruments/`, `/market-data/`, `/risk-metrics/`, `/providers/`

Every endpoint requires authentication (session or `Authorization: Token <key>`), and users
only see their own accounts, strategies, orders and backtests. Create a token in the admin
(*Auth Token > Tokens*).

Management commands:

```powershell
python manage.py import_backtest_report docs/reports/showcase --username <user>
python manage.py calculate_risk_metrics [--symbols AAPL,MSFT] [--force-recalculate]
python manage.py data_quality_check [--provider yfinance] [--fail-on-error]
python manage.py load_market_data --symbols AAPL,MSFT --days-back 30   # needs internet (yfinance)
```

`calculate_risk_metrics` reads the last two years before today, and the data-quality
*timeliness* check passes only when the newest bar is less than about 5 hours old. Both are
meant for a live data feed, not for historical files such as the demo dataset.

## Tests

```powershell
python -m pytest                      # engine, research and Django; no external services
python -m pytest tests/unit           # engine and research only (works with requirements_engine.txt)
python -m pytest tests/django_tests   # Django only
```

The Django tests use `quantcore/settings_test.py`: in-memory SQLite, a local-memory cache
and eager Celery. To run them on PostgreSQL instead, use a role that may create databases:

```powershell
$env:TEST_DATABASE_URL = "postgres://USER:PASSWORD@localhost:5432/quantcore"
python -m pytest tests/django_tests
```

The tests are deterministic. They use seeded synthetic prices, publish quotes directly on
the event bus and fill orders without delay. Nothing touches live market data or the
network.

## Dependency manifests

| File | Stack | Status |
| --- | --- | --- |
| `requirements_dev.txt` | Engine + Django + report figures + test tools; the complete local environment | Installs cleanly on Python 3.11; `pip check` passes |
| `requirements_engine.txt` | Engine runtime and pytest only | Subset of the above |
| `requirements_reports.txt` | Engine + matplotlib, contourpy, pillow for the report generator | Subset of the above; pins keep numpy at 1.24.3 |
| `requirements_django.txt` | Django, DRF, Celery, Channels, data libraries | Installs; fixed `QuantLib` name; added `django-redis` and a `kombu` pin |
| `requirements.txt` | Legacy stack: Airflow, MySQL/ClickHouse, OpenAI/LangChain/FAISS, ... | Does not resolve as pinned (see below) |
| `pyproject.toml` | Version ranges: engine runtime as `dependencies`; `django`, `reports`, `dev`, `legacy` extras; pytest settings | Not a lock: install from the requirements files |

Only top-level packages are pinned; transitive versions float. That caused two problems:
- pip once picked kombu 5.7, which refuses the pinned redis 4.6.
- An unpinned matplotlib pulled numpy 2.x, which the pinned pandas cannot import.

For fully reproducible installs, generate a constraints file from a known-good environment
with `pip freeze`.

## Architecture notes

### Trading engine

`TradingApplicationService` (`src/services/application_service.py`) builds one event bus
and five services, registers them in `ServiceRegistry` and wires them together.
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
- **Risk before submission.** Every order goes through `OrderExecutionService.submit_order`,
  which runs the registered pre-trade checks first. A rejected order is marked `REJECTED`,
  never reaches the engine and creates a risk alert. This applies equally to strategy orders
  and `TradingOrchestrator.submit_order`.
- **Fills.**
  - Market and stop orders fill at the latest quote, moved by the configured slippage.
  - Limit orders fill at the limit price or better.
  - Resting orders and partial fills are not modelled.
- **Accounting.** `Portfolio.apply_fill` is shared by the live services and the backtester:
  - Buys spend notional plus commission; sells receive notional minus commission.
  - A partial close keeps the position's average cost.
- **Lifecycle.** `initialize()` creates the services and subscribes them to the bus.
  `start()` begins streaming and blocks until `stop()` is called. Default instruments and
  strategies are installed only when none were configured.

### Backtesting

`BacktestEngine` (`src/backtesting/engine.py`) replays daily bars:
- Orders that a strategy returns on bar *t* fill on the next bar of the same symbol, at the
  close plus slippage.
- Fills move cash and positions, commissions included.
- Every bar is recorded in a ledger (cash, equity, quantities, marks, stale marks), and
  every order in an order log with its rejection reason.
- A symbol without a bar keeps its last close as the mark.
- There are no margin or risk checks in backtests.

`src/backtesting/synthetic.py` generates the small deterministic OHLCV series used by the
quick example and the tests; the research universe comes from `src/research/datasets.py`.

### Django project

- `apps.market_data`: providers, instruments, OHLCV bars, technical indicators,
  fundamentals, risk metrics and data-quality checks. It also holds the Celery tasks and
  three management commands.
- `apps.trading`: user-owned trading accounts, strategies, orders, trades, positions,
  portfolio snapshots and backtest results, plus `import_backtest_report`.
- REST API under `/api/v1/`, OpenAPI schema under `/api/schema/`.

[README_ARCHITECTURE.md](../README_ARCHITECTURE.md) contains the original object-oriented
design notes. They describe intentions as well as code; this guide and the code are
authoritative where they differ.

## Legacy stack

These parts were not verified and are not installed by `requirements_dev.txt`:

- `requirements.txt` cannot be installed as pinned. pip reports `ResolutionImpossible`:
  `apache-airflow==2.7.0` requires `opentelemetry-api==1.15.0`, but the file pins `1.19.0`.
  Airflow should be installed with its official constraints file.
- `airflow/dags/` and `dbt/` are the original pipeline definitions. Their Django
  replacements are the Celery tasks and management commands in `apps/market_data` (see
  [README_DJANGO_MIGRATION.md](../README_DJANGO_MIGRATION.md)).
- Engine modules that still fail to import:
  - `src/data/loaders.py`, `bloomberg_connector.py`, `factset_connector.py`: need
    `mysql-connector-python`.
  - `snowflake_connector.py`, `refinitiv_connector.py`: need their vendor SDKs.
  - `databricks_connector.py`: has an f-string that is a SyntaxError before Python 3.12.
  - `src/ml/alpha_research.py`: imports `sklearn.metrics.information_score`, which does not
    exist.

## Known limitations

- `EVENT_BUS_TYPE=redis` cannot publish engine events. `json.dumps` fails on enums and
  datetimes, and subscribers would receive plain dicts instead of the objects they expect.
- **Engine risk.**
  - `BasicRiskManager.calculate_risk_metrics` VaR and `RiskService` beta use random
    numbers.
  - The daily-loss check always passes, and the periodic monitoring loop only sleeps.
  - The pre-trade limits are real: position quantity and leverage, with market orders
    priced at the latest quote.
- `MAX_POSITION_SIZE` is an absolute share quantity in the engine. Django's
  `TradingAccount.max_position_size` is a separate money field that only the research
  import sets.
- `ParameterOptimizer` (`src/backtesting/engine.py`) runs its backtests concurrently on one
  engine, which is not safe, and it is untested. The research pipeline does not use it; it
  gives every run its own engine.
- `daily_market_data_pipeline` and `weekly_comprehensive_analysis` wait on subtask results
  inside a task, which a real Celery worker rejects. They need rewriting as chains.
