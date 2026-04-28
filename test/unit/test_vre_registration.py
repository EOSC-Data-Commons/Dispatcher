"""Test that all VRE implementations are registered in __init__.py."""

import inspect
import pkgutil
from importlib import import_module


def test_all_vre_classes_are_imported_in_init():
    """
    Verify that all VRE classes defined in app.vres modules are imported in __init__.py.

    This test ensures that when new VRE implementations are added, they are properly
    exported from the package's __init__.py file, which also triggers their factory
    registration (since each VRE module calls vre_factory.register() on import).
    """
    # Import the vres package and its __init__
    vres_package = import_module("app.vres")
    vres_init = import_module("app.vres.__init__")
    from app.vres.base_vre import VRE, vre_factory

    # Get all VRE classes defined in the vres package (excluding base_vre)
    expected_vre_classes = {}  # name -> class

    # Walk through all modules in the vres package
    vres_path = vres_package.__path__
    for _, module_name, _ in pkgutil.iter_modules(vres_path):
        # Skip base_vre as it contains the abstract base class
        if module_name == "base_vre":
            continue

        # Import the module
        module = import_module(f"app.vres.{module_name}")

        # Find all classes that inherit from VRE and are not the base VRE class
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Check if it's defined in this module (not imported)
            if obj.__module__ == f"app.vres.{module_name}":
                if issubclass(obj, VRE) and obj is not VRE:
                    expected_vre_classes[name] = obj

    # Get all VRE classes exported from __init__.py
    actual_exports = {}
    for name, obj in inspect.getmembers(vres_init):
        if not name.startswith("_") and inspect.isclass(obj):
            if issubclass(obj, VRE) and obj is not VRE:
                actual_exports[name] = obj

    # Check that all expected VRE classes are exported
    missing_classes = set(expected_vre_classes.keys()) - set(actual_exports.keys())

    assert not missing_classes, (
        f"The following VRE classes are defined but not imported in app.vres.__init__: "
        f"{sorted(missing_classes)}"
    )

    # Check for unexpected exports
    extra_classes = set(actual_exports.keys()) - set(expected_vre_classes.keys())

    assert not extra_classes, (
        f"The following classes are exported in __init__.py but are not VRE implementations: "
        f"{sorted(extra_classes)}"
    )

    # Verify factory has all expected registrations
    registered_classes = set(vre_factory.table.values())
    unregistered = [
        name
        for name, cls in expected_vre_classes.items()
        if cls not in registered_classes
    ]

    assert not unregistered, (
        f"The following VRE classes are imported in __init__.py but not registered "
        f"in vre_factory: {unregistered}"
    )
