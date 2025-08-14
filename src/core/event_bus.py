import asyncio
from typing import Dict, List, Callable, Any
from collections import defaultdict
import json
import redis.asyncio as redis
from dataclasses import asdict

from src.core.models import EventBus
from src.core.config import get_config


class InMemoryEventBus(EventBus):
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        
    async def publish(self, event_type: str, data: Dict) -> None:
        for callback in self._subscribers[event_type]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                print(f"Event handler error: {e}")
    
    async def subscribe(self, event_type: str, callback: Callable) -> None:
        self._subscribers[event_type].append(callback)


class RedisEventBus(EventBus):
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis_url = redis_url
        self._redis = None
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._listening = False
        
    async def _get_redis(self):
        if self._redis is None:
            self._redis = redis.from_url(self._redis_url)
        return self._redis
        
    async def publish(self, event_type: str, data: Dict) -> None:
        redis_client = await self._get_redis()
        message = json.dumps({
            "event_type": event_type,
            "data": self._serialize_data(data),
            "timestamp": asyncio.get_event_loop().time()
        })
        await redis_client.publish(f"trading:{event_type}", message)
        
    async def subscribe(self, event_type: str, callback: Callable) -> None:
        self._subscribers[event_type].append(callback)
        if not self._listening:
            asyncio.create_task(self._listen_for_events())
            self._listening = True
            
    async def _listen_for_events(self):
        redis_client = await self._get_redis()
        pubsub = redis_client.pubsub()
        
        for event_type in self._subscribers.keys():
            await pubsub.subscribe(f"trading:{event_type}")
            
        async for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    event_type = data['event_type']
                    event_data = data['data']
                    
                    for callback in self._subscribers[event_type]:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(event_data)
                            else:
                                callback(event_data)
                        except Exception as e:
                            print(f"Event handler error: {e}")
                except Exception as e:
                    print(f"Event parsing error: {e}")
                    
    def _serialize_data(self, data: Dict) -> Dict:
        serialized = {}
        for key, value in data.items():
            if hasattr(value, '__dict__'):
                if hasattr(value, '__dataclass_fields__'):
                    serialized[key] = asdict(value)
                else:
                    serialized[key] = value.__dict__
            else:
                serialized[key] = value
        return serialized


def create_event_bus() -> EventBus:
    config = get_config()
    if config.get("event_bus", {}).get("type") == "redis":
        redis_url = config.get("event_bus", {}).get("url", "redis://localhost:6379")
        return RedisEventBus(redis_url)
    return InMemoryEventBus()