import environ
from pathlib import Path

env = environ.Env(
    DEBUG=(bool, False)
)

BASE_DIR = Path(__file__).resolve().parent.parent

environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-me-in-production')

DEBUG = env('DEBUG')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    # Token model and migrations for TokenAuthentication (enabled in REST_FRAMEWORK below).
    'rest_framework.authtoken',
    'corsheaders',
    'channels',
    'drf_spectacular',
    'django_celery_beat',
    'django_celery_results',
]

# Only apps that exist under apps/. The settings previously also listed apps.portfolio,
# apps.risk, apps.strategies, apps.backtesting, apps.ml and apps.monitoring, which have
# no code, so Django could not start. Their logic lives in the trading engine under
# src/ (src/portfolio, src/backtesting, src/ml, src/services/risk_service.py, ...).
LOCAL_APPS = [
    'apps.trading',
    'apps.market_data',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'quantcore.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'quantcore.wsgi.application'
ASGI_APPLICATION = 'quantcore.asgi.application'

# PostgreSQL is the configured database. DATABASE_URL, when set, replaces it entirely,
# e.g. DATABASE_URL=sqlite:///db.sqlite3 for a local run without PostgreSQL.
if env('DATABASE_URL', default=''):
    DATABASES = {'default': env.db('DATABASE_URL')}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DB_NAME', default='quantcore'),
            'USER': env('DB_USER', default='postgres'),
            'PASSWORD': env('DB_PASSWORD', default=''),
            'HOST': env('DB_HOST', default='localhost'),
            'PORT': env('DB_PORT', default='5432'),
            # Django 4.2 has no connection pool; persistent connections are the closest
            # option. The previous OPTIONS={'MAX_CONNS': 20} is not a libpq connection
            # parameter, so psycopg2 rejected every connection attempt.
            'CONN_MAX_AGE': env.int('DB_CONN_MAX_AGE', default=0),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour'
    }
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'QuantCore Trading API',
    'DESCRIPTION': 'Quantitative Trading Platform API',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    "http://localhost:3000",
    "http://127.0.0.1:3000",
])

CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [env('REDIS_URL', default='redis://localhost:6379/1')],
        },
    },
}

# Redis (django-redis) is the configured cache. DRF throttling reads the cache on every
# API request, so the API needs a reachable Redis. CACHE_BACKEND=locmem switches to a
# per-process memory cache for development without Redis.
if env('CACHE_BACKEND', default='redis') == 'locmem':
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': env('REDIS_URL', default='redis://localhost:6379/2'),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            }
        }
    }

# The file handler needs its directory to exist before logging is configured.
LOG_DIR = Path(env('LOG_DIR', default=str(BASE_DIR / 'logs')))
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': LOG_DIR / 'quantcore.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'quantcore': {
            'handlers': ['console', 'file'],
            'level': env('LOG_LEVEL', default='INFO'),
            'propagate': True,
        },
        # Loggers in apps/ (e.g. apps.market_data.tasks) are named after their modules.
        'apps': {
            'handlers': ['console', 'file'],
            'level': env('LOG_LEVEL', default='INFO'),
            'propagate': True,
        },
    },
}

TRADING_CONFIG = {
    'MAX_POSITION_SIZE': env.float('MAX_POSITION_SIZE', default=1000000.0),
    'MAX_PORTFOLIO_RISK': env.float('MAX_PORTFOLIO_RISK', default=0.02),
    'DEFAULT_COMMISSION': env.float('DEFAULT_COMMISSION', default=0.001),
    'RISK_FREE_RATE': env.float('RISK_FREE_RATE', default=0.02),
    'MARKET_DATA_PROVIDERS': env.list('MARKET_DATA_PROVIDERS', default=['yfinance']),
}

FINANCIAL_DATA_CONFIG = {
    'BLOOMBERG_API_KEY': env('BLOOMBERG_API_KEY', default=''),
    'ALPHA_VANTAGE_API_KEY': env('ALPHA_VANTAGE_API_KEY', default=''),
    'QUANDL_API_KEY': env('QUANDL_API_KEY', default=''),
    'DATA_REFRESH_INTERVAL': env.int('DATA_REFRESH_INTERVAL', default=300),  # seconds
}