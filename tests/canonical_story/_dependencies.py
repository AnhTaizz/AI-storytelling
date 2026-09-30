"""Fail loudly (never skip) when Canonical Story tooling dependencies are missing."""
import importlib

REQUIRED = {"jsonschema": "jsonschema", "yaml": "PyYAML"}
INSTALL_HINT = "python -m pip install -r requirements-canonical-story.txt"


def require_dependencies() -> None:
    missing = []
    for module, package in REQUIRED.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    if missing:
        raise ImportError(
            f"Canonical Story tests require {', '.join(missing)}. Install with: {INSTALL_HINT}"
        )


require_dependencies()
