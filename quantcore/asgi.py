import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quantcore.settings')

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    # WebSocket support for real-time updates (can be extended later)
    # "websocket": AuthMiddlewareStack(
    #     URLRouter([
    #         # WebSocket URL patterns
    #     ])
    # ),
})