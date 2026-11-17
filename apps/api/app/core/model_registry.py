"""Imports every modules/<name>/models.py so SQLAlchemy metadata (and Alembic
autogenerate) sees every table, without each module importing the others."""

import importlib
import pkgutil

import app.modules as modules_pkg


def import_all_models() -> None:
    for _, module_name, is_pkg in pkgutil.iter_modules(modules_pkg.__path__):
        if not is_pkg:
            continue
        try:
            importlib.import_module(f"app.modules.{module_name}.models")
        except ModuleNotFoundError:
            continue
