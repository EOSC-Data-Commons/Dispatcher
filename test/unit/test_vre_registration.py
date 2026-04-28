"""Test that all VRE implementations are properly registered in __init__.py."""

from __future__ import annotations

import inspect
from importlib import import_module
from pathlib import Path
from typing import Type

import pytest

from app.vres.base_vre import VRE, vre_factory


def _get_vre_modules_path() -> Path:
    """Return the path to the vres package directory."""
    return Path(import_module("app.vres").__file__).parent


def _discover_vre_classes() -> dict[str, Type[VRE]]:
    """
    Discover all concrete VRE implementations in the vres package.

    Returns:
        A mapping of class name to VRE subclass, excluding the base VRE class.
    """
    vres_classes: dict[str, Type[VRE]] = {}
    vres_path = _get_vre_modules_path()

    for module_file in vres_path.glob("*.py"):
        module_name = module_file.stem

        # Skip base module and private modules
        if module_name in ("base_vre", "__init__"):
            continue

        module = import_module(f"app.vres.{module_name}")

        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Only include classes defined in this specific module
            if obj.__module__ != f"app.vres.{module_name}":
                continue

            # Include only concrete VRE subclasses
            if issubclass(obj, VRE) and obj is not VRE:
                vres_classes[name] = obj

    return vres_classes


def _get_init_exports() -> dict[str, Type[VRE]]:
    """
    Get all VRE classes exported from the vres __init__.py.

    Returns:
        A mapping of exported name to VRE class.
    """
    vres_init = import_module("app.vres.__init__")
    exports: dict[str, Type[VRE]] = {}

    for name, obj in inspect.getmembers(vres_init, inspect.isclass):
        if name.startswith("_"):
            continue
        if issubclass(obj, VRE) and obj is not VRE:
            exports[name] = obj

    return exports


def test_all_vre_implementations_imported_in_init():
    """
    Verify all VRE implementations are imported in app/vres/__init__.py.

    This ensures new VRE classes are properly exposed at the package level
    and automatically registered with the factory (via module-level registration).

    Fails if a VRE implementation exists but isn't imported in __init__.py.
    """
    expected = _discover_vre_classes()
    actual = _get_init_exports()

    missing = expected.keys() - actual.keys()

    assert not missing, (
        f"VRE implementations found but not imported in __init__.py: {sorted(missing)}\n\n"
        "To fix, add import statements like:\n"
        f"    from .<module> import {', '.join(sorted(missing))}"
    )


def test_all_init_exports_are_registered_in_factory():
    """
    Verify all exported VRE classes are registered with vre_factory.

    Each VRE module should call vre_factory.register() at module level.
    This test catches cases where a VRE is imported but not registered.
    """
    exports = _get_init_exports()
    registered = set(vre_factory.table.values())

    unregistered = [name for name, cls in exports.items() if cls not in registered]

    assert not unregistered, f"VRE classes imported but not registered: {unregistered}"
