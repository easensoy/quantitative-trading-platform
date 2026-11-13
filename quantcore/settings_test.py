"""Settings for the automated test suite.

Everything external is replaced with an in-process equivalent, so the tests need no
PostgreSQL, Redis or Celery broker. Selected in pyproject.toml through
DJANGO_SETTINGS_MODULE.

Set TEST_DATABASE_URL (e.g. postgres://user:password@localhost:5432/quantcore) to run
the same tests on PostgreSQL; pytest-django then creates and drops test_<NAME>.
"""
from .settings import *  # noqa: F401,F403
from .settings import env

SECRET_KEY = 'test-only-insecure-secret-key'
DEBUG = False

if env('TEST_DATABASE_URL', default=''):
    DATABASES = {'default': env.db('TEST_DATABASE_URL')}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}

CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
