# Load the Celery app whenever Django starts so @shared_task binds to it (and to the
# CELERY_* settings) rather than to a default app with an AMQP broker.
from .celery import app as celery_app

__all__ = ('celery_app',)
