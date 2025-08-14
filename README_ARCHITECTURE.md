# Trading System OOP Architecture

## Overview
The entire codebase has been refactored to follow proper Object-Oriented Programming (OOP) principles with a service-oriented architecture. Each component is orchestrated through dependency injection and service composition.

## Architecture Layers

### 1. Core Layer (`src/core/`)
- **Models**: Data models and abstract interfaces
- **Container**: Dependency injection container and service registry
- **Event Bus**: Event-driven communication between services
- **Implementations**: Concrete implementations of core interfaces
- **Orchestrator**: High-level orchestration facade

### 2. Service Layer (`src/services/`)
Each service is a standalone class responsible for a specific domain:

- **MarketDataService**: Real-time market data streaming and management
- **OrderExecutionService**: Order lifecycle management and execution
- **PortfolioService**: Portfolio state management and position tracking
- **RiskService**: Risk monitoring, validation, and alerting
- **StrategyService**: Strategy registration, execution, and performance tracking
- **ApplicationService**: Main application coordination and lifecycle management

### 3. Domain Layers
- **Portfolio** (`src/portfolio/`): Portfolio optimization algorithms
- **Backtesting** (`src/backtesting/`): Historical simulation engine
- **Execution** (`src/execution/`): Smart order routing
- **P&L** (`src/pnl/`): Performance and attribution analysis
- **Data** (`src/data/`): Data extraction, transformation, and loading

## Service Orchestration

### Dependency Injection Container
```python
from src.core.container import ServiceRegistry

container = ServiceRegistry.get_container()
container.register_singleton("event_bus", event_bus_instance)
container.register("market_data_service", MarketDataService)
```

### Service Communication
Services communicate through:
1. **Constructor Injection**: Services receive dependencies via constructor
2. **Event Bus**: Asynchronous event-driven communication
3. **Direct Method Calls**: Synchronous service-to-service calls
4. **Callbacks**: Reactive programming patterns

### Factory Pattern
Each service domain has a dedicated factory class:
- `MarketDataFactory`
- `OrderExecutionFactory` 
- `PortfolioFactory`
- `RiskFactory`
- `StrategyFactory`
- `ApplicationFactory`

## Service Interactions

### Market Data Flow
```
MarketDataService → EventBus → StrategyService → OrderExecutionService → PortfolioService
```

### Risk Management Flow
```
OrderExecutionService → RiskService → PortfolioService → EventBus → ApplicationService
```

### Strategy Execution Flow
```
MarketDataService → StrategyService → OrderExecutionService → PortfolioService → RiskService
```

## Key OOP Principles Applied

### Single Responsibility
- Each service handles one domain (market data, orders, portfolio, risk, strategies)
- Clear separation of concerns between data, business logic, and orchestration

### Open/Closed Principle
- Services implement abstract interfaces
- Easy to extend with new implementations without modifying existing code
- Factory pattern enables runtime service selection

### Dependency Inversion
- High-level services depend on abstractions, not concrete implementations
- Dependency injection container manages all service dependencies
- Mock implementations for testing

### Composition over Inheritance
- Services are composed together rather than using complex inheritance hierarchies
- ApplicationService orchestrates all domain services
- Clear service boundaries and interfaces

## Usage Examples

### Initialize System
```python
from src.services.application_service import ApplicationFactory

app = ApplicationFactory.create_application()
await app.initialize()
await app.start()
```

### Add Custom Strategy
```python
strategy = Strategy(id="custom_001", name="Custom Strategy")
await app.add_strategy(strategy, custom_handler_function)
```

### Monitor System
```python
status = await app.get_system_status()
portfolio_summary = await app.get_portfolio_summary()
risk_summary = await app.get_risk_summary()
```

### Emergency Controls
```python
await app.emergency_stop()
await app.pause_strategy("strategy_001")
```

## Benefits of This Architecture

1. **Modularity**: Each service can be developed, tested, and deployed independently
2. **Testability**: Easy to mock dependencies and unit test individual services
3. **Scalability**: Services can be distributed across different processes/machines
4. **Maintainability**: Clear service boundaries reduce coupling and complexity
5. **Extensibility**: New services and implementations can be added without breaking existing code
6. **Observability**: Event-driven architecture provides natural audit trail and monitoring points

## Service Lifecycle

1. **Initialization**: ApplicationService initializes all services with proper dependencies
2. **Registration**: Services register with the container and subscribe to events
3. **Orchestration**: ApplicationService coordinates service interactions
4. **Monitoring**: Continuous health checking and error handling
5. **Shutdown**: Graceful service shutdown with resource cleanup

The entire system now operates as a cohesive collection of orchestrated services, where each component has a clear responsibility and communicates through well-defined interfaces.