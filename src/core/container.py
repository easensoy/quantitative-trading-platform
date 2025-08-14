from typing import Dict, Type, Any, Optional, Callable
from abc import ABC, abstractmethod
import inspect


class ServiceContainer:
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._singletons: Dict[str, Any] = {}
        self._factories: Dict[str, Callable] = {}
        self._bindings: Dict[Type, Type] = {}
    
    def register_singleton(self, service_name: str, instance: Any) -> None:
        self._singletons[service_name] = instance
    
    def register_factory(self, service_name: str, factory: Callable) -> None:
        self._factories[service_name] = factory
    
    def bind(self, interface: Type, implementation: Type) -> None:
        self._bindings[interface] = implementation
    
    def register(self, service_name: str, service_class: Type, *args, **kwargs) -> None:
        self._services[service_name] = (service_class, args, kwargs)
    
    def get(self, service_name: str) -> Any:
        if service_name in self._singletons:
            return self._singletons[service_name]
        
        if service_name in self._factories:
            return self._factories[service_name]()
        
        if service_name in self._services:
            service_class, args, kwargs = self._services[service_name]
            resolved_kwargs = self._resolve_dependencies(service_class, kwargs)
            return service_class(*args, **resolved_kwargs)
        
        raise ValueError(f"Service {service_name} not registered")
    
    def get_instance(self, service_class: Type) -> Any:
        if service_class in self._bindings:
            service_class = self._bindings[service_class]
        
        resolved_kwargs = self._resolve_dependencies(service_class, {})
        return service_class(**resolved_kwargs)
    
    def _resolve_dependencies(self, service_class: Type, provided_kwargs: Dict) -> Dict:
        signature = inspect.signature(service_class.__init__)
        resolved = provided_kwargs.copy()
        
        for param_name, param in signature.parameters.items():
            if param_name == 'self' or param_name in resolved:
                continue
            
            param_type = param.annotation
            
            if param_type in self._bindings:
                resolved[param_name] = self.get_instance(param_type)
            elif hasattr(param_type, '__name__') and param_type.__name__.lower() in self._services:
                resolved[param_name] = self.get(param_type.__name__.lower())
        
        return resolved


class ServiceRegistry:
    _container: Optional[ServiceContainer] = None
    
    @classmethod
    def get_container(cls) -> ServiceContainer:
        if cls._container is None:
            cls._container = ServiceContainer()
        return cls._container
    
    @classmethod
    def reset(cls) -> None:
        cls._container = None


class Injectable(ABC):
    pass


def service(name: str):
    def decorator(cls):
        container = ServiceRegistry.get_container()
        container.register(name, cls)
        return cls
    return decorator


def singleton(name: str):
    def decorator(cls):
        container = ServiceRegistry.get_container()
        instance = cls()
        container.register_singleton(name, instance)
        return cls
    return decorator