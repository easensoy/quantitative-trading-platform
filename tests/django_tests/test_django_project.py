import pytest
from celery.beat import ScheduleEntry
from django.apps import apps
from django.conf import settings
from django.core.management import call_command

from quantcore import celery_app


def test_system_checks_pass():
    call_command("check", fail_level="WARNING")


@pytest.mark.django_db
def test_every_model_change_has_a_migration():
    # Exits with status 1 if makemigrations would create a migration.
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)


def test_only_existing_local_apps_are_installed():
    local_apps = [name for name in settings.INSTALLED_APPS if name.startswith("apps.")]

    assert local_apps == ["apps.trading", "apps.market_data"]
    for label in ("trading", "market_data"):
        assert apps.get_app_config(label).models_module is not None


def test_token_authentication_app_is_installed():
    assert "rest_framework.authtoken" in settings.INSTALLED_APPS


def test_log_directory_exists():
    assert settings.LOG_DIR.is_dir()


def test_beat_schedule_entries_are_valid_and_reference_registered_tasks():
    celery_app.loader.import_default_modules()  # runs task autodiscovery

    for name, entry in celery_app.conf.beat_schedule.items():
        schedule_entry = ScheduleEntry(name=name, app=celery_app, **entry)
        is_due, next_check_seconds = schedule_entry.is_due()
        assert next_check_seconds > 0, name
        assert entry["task"] in celery_app.tasks, entry["task"]


def test_shared_tasks_bind_to_the_project_celery_app():
    from apps.market_data import tasks

    assert tasks.fetch_market_data_task.app is celery_app
