# QuantCore Django Migration Guide

> For the verified setup steps (Windows), configuration and current component status, see [docs/development.md](docs/development.md). This guide describes the migration design.

This document outlines the complete migration of QuantCore from Snowflake + Airflow + DBT to Django + PostgreSQL + Celery.

## 🏗️ Architecture Changes

### Before (Original)
- **Data Warehouse**: Snowflake
- **Orchestration**: Airflow DAGs
- **Transformations**: DBT models
- **Raw SQL**: Extensive use throughout

### After (Django Migration)
- **Database**: PostgreSQL with Django ORM
- **Orchestration**: Celery tasks with Redis
- **Transformations**: Django management commands
- **No Raw SQL**: Everything through Django ORM

## 📁 New Project Structure

```
QuantCore/
├── quantcore/                 # Django project
│   ├── settings.py
│   ├── urls.py
│   ├── celery.py
│   └── wsgi.py/asgi.py
├── apps/
│   ├── market_data/           # Market data management
│   │   ├── models.py          # Replaces Snowflake tables
│   │   ├── services.py        # Data processing logic
│   │   ├── views.py           # REST API endpoints
│   │   ├── admin.py           # Django admin interface
│   │   ├── tasks.py           # Celery tasks (replaces Airflow)
│   │   └── management/commands/ # Django commands (replaces DBT)
│   └── trading/               # Trading operations
│       ├── models.py          # Trading accounts, orders, positions
│       ├── views.py           # Trading API
│       └── admin.py
├── requirements_django.txt    # New dependencies
├── manage.py                  # Django management
└── .env.example              # Configuration template
```

## 🔄 Migration Mapping

### Data Models (Snowflake → Django)

| Original Snowflake Table | New Django Model | Location |
|--------------------------|------------------|----------|
| `market_data_raw` | `MarketData` | `apps.market_data.models.MarketData` |
| `bloomberg_data` | `MarketData` (with provider) | Same |
| `refinitiv_data` | `MarketData` (with provider) | Same |
| `factset_data` | `FundamentalData` | `apps.market_data.models.FundamentalData` |
| `market_analytics` | `TechnicalIndicator` | `apps.market_data.models.TechnicalIndicator` |
| Custom risk tables | `RiskMetrics` | `apps.market_data.models.RiskMetrics` |

### ETL Processes (Airflow → Celery)

| Original Airflow DAG | New Celery Task | Location |
|---------------------|-----------------|----------|
| `market_data_pipeline` | `daily_market_data_pipeline` | `apps.market_data.tasks.daily_market_data_pipeline` |
| `multi_vendor_data_pipeline` | `fetch_market_data_task` | `apps.market_data.tasks.fetch_market_data_task` |
| Data quality checks | `data_quality_check_task` | `apps.market_data.tasks.data_quality_check_task` |

### Data Transformations (DBT → Django Commands)

| Original DBT Model | New Django Command | Location |
|-------------------|-------------------|----------|
| `stg_bloomberg_equity.sql` | `load_market_data` | `apps.market_data.management.commands.load_market_data` |
| `equity_prices.sql` | Built into `MarketDataService` | `apps.market_data.services.MarketDataService` |
| `risk_metrics.sql` | `calculate_risk_metrics` | `apps.market_data.management.commands.calculate_risk_metrics` |

## 🚀 Setup Instructions

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Django dependencies
pip install -r requirements_django.txt
```

### 2. Database Setup

```bash
# Create PostgreSQL database
createdb quantcore

# Copy environment file
cp .env.example .env
# Edit .env with your database credentials

# Run migrations
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

### 3. Redis Setup

```bash
# Install and start Redis
# Ubuntu/Debian:
sudo apt-get install redis-server
sudo systemctl start redis-server

# macOS:
brew install redis
brew services start redis

# Windows: Download from https://redis.io/download
```

### 4. Start Services

```bash
# Terminal 1: Django development server
python manage.py runserver

# Terminal 2: Celery worker
celery -A quantcore worker --loglevel=info

# Terminal 3: Celery beat (scheduler)
celery -A quantcore beat --loglevel=info
```

## 📊 Key Features

### 1. Django Admin Interface
- **URL**: http://localhost:8000/admin/
- **Features**: 
  - Complete data management
  - Market data visualization
  - Trading account management
  - Risk metrics monitoring

### 2. REST API
- **Base URL**: http://localhost:8000/api/v1/
- **Documentation**: http://localhost:8000/api/docs/
- **Endpoints**:
  - `/accounts/` - Trading accounts
  - `/strategies/` - Trading strategies
  - `/orders/` - Order management
  - `/positions/` - Position tracking
  - `/market-data/` - Market data access

### 3. Automated Tasks (Celery)
- **Daily market data pipeline**: Runs at 6 AM UTC
- **Hourly data fetch**: During market hours
- **Risk metrics calculation**: Daily at 7 AM UTC
- **Data quality checks**: Twice daily

## 🔧 Management Commands

### Load Market Data
```bash
# Load data for specific symbols
python manage.py load_market_data --symbols AAPL,GOOGL,MSFT

# Load all active instruments for last 30 days
python manage.py load_market_data --days-back 30

# Calculate technical indicators
python manage.py load_market_data --symbols AAPL --calculate-indicators
```

### Calculate Risk Metrics
```bash
# Calculate for all instruments
python manage.py calculate_risk_metrics

# Calculate for specific symbols
python manage.py calculate_risk_metrics --symbols AAPL,GOOGL

# Force recalculation
python manage.py calculate_risk_metrics --force-recalculate
```

### Data Quality Checks
```bash
# Run all quality checks
python manage.py data_quality_check

# Check specific provider
python manage.py data_quality_check --provider yfinance

# Fail on errors (for CI/CD)
python manage.py data_quality_check --fail-on-error
```

## 🔄 Data Migration Process

### Option 1: Fresh Start
1. Use the new Django models
2. Fetch fresh data using management commands
3. Build up historical data over time

### Option 2: Migrate Existing Data
1. Export data from Snowflake to CSV/JSON
2. Create Django data fixtures
3. Load using Django's `loaddata` command

## 🏃‍♂️ Running the System

### Development Mode
```bash
# Start all services
python manage.py runserver &
celery -A quantcore worker --loglevel=info &
celery -A quantcore beat --loglevel=info &

# Load some test data
python manage.py load_market_data --symbols AAPL,GOOGL,MSFT --days-back 30 --calculate-indicators
```

### Production Deployment
- Use PostgreSQL instead of SQLite
- Use Redis for Celery broker
- Set up proper environment variables
- Use Gunicorn/uWSGI for WSGI
- Configure nginx for static files
- Set up monitoring and logging

## 🔍 Key Benefits

1. **No Raw SQL**: Everything through Django ORM
2. **Better Integration**: Single Python ecosystem
3. **Admin Interface**: Built-in data management
4. **API-First**: REST API for all operations
5. **Simplified Architecture**: Fewer moving parts
6. **Better Testing**: Django's testing framework
7. **Security**: Django's built-in security features

## 🚨 Important Notes

1. **Performance**: For very large datasets, consider database optimization
2. **Scaling**: Use database connection pooling in production
3. **Monitoring**: Set up proper logging and monitoring
4. **Backup**: Implement regular PostgreSQL backups
5. **Security**: Follow Django security best practices

## 📚 Next Steps

1. Test the new system with real data
2. Set up monitoring and alerting
3. Implement additional trading strategies
4. Add real-time WebSocket support
5. Create a frontend interface
6. Set up automated testing
7. Deploy to production environment

This migration provides a more integrated, maintainable, and scalable architecture while eliminating the need for raw SQL and reducing system complexity.