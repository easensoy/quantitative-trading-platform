from src.core.config import AppConfig, get_config


def test_app_config_instantiates_with_independent_nested_configs():
    first, second = AppConfig(), AppConfig()

    assert first.trading is not second.trading
    assert first.database is not second.database
    first.trading.max_position_size = 1
    assert second.trading.max_position_size != 1


def test_environment_is_read_when_config_is_created(monkeypatch):
    monkeypatch.setenv("MAX_POSITION_SIZE", "250")
    monkeypatch.setenv("REDIS_PORT", "6390")
    monkeypatch.setenv("ENABLE_TELEMETRY", "false")
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)

    config = AppConfig()

    assert config.trading.max_position_size == 250.0
    assert config.database.redis_port == 6390
    assert config.monitoring.enable_telemetry is False
    assert config.database.redis_password is None


def test_initial_capital_comes_from_initial_capital_not_position_limit(monkeypatch):
    monkeypatch.setenv("MAX_POSITION_SIZE", "500")
    monkeypatch.setenv("INITIAL_CAPITAL", "250000")

    config = get_config()

    assert config["initial_capital"] == 250000.0
    assert config["risk"]["max_position_size"] == 500.0


def test_optional_runtime_settings(monkeypatch):
    monkeypatch.delenv("SIMULATION_SEED", raising=False)
    monkeypatch.delenv("RUN_DURATION_SECONDS", raising=False)
    monkeypatch.delenv("MARKET_DATA_POLL_INTERVAL", raising=False)

    config = get_config()
    assert config["market_data"]["seed"] is None
    assert config["market_data"]["poll_interval"] == 1.0
    assert config["run_duration_seconds"] is None

    monkeypatch.setenv("SIMULATION_SEED", "7")
    monkeypatch.setenv("RUN_DURATION_SECONDS", "2.5")
    config = get_config()
    assert config["market_data"]["seed"] == 7
    assert config["run_duration_seconds"] == 2.5
