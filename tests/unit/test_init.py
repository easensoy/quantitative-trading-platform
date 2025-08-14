import pytest
from src.core.container import ServiceRegistry

def test_container_singleton():
    container1 = ServiceRegistry.get_container()
    container2 = ServiceRegistry.get_container()
    assert container1 is container2