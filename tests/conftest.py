import importlib.util

# The Django tests need pytest-django (installed by requirements_dev.txt). Skip collecting
# them in an engine-only environment (requirements_engine.txt) instead of erroring.
collect_ignore = [] if importlib.util.find_spec("pytest_django") else ["django_tests"]
