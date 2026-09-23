"""Pytest collection policy for the generic platform test suite."""

import os

import pytest

from tests.week_manifest import DEPRECATED_TEST_MODULES


def pytest_collection_modifyitems(config, items):
    """Keep historical industry tests out of the default active suite."""
    if os.environ.get("INCLUDE_DEPRECATED_TESTS") == "1":
        return

    skip_deprecated = pytest.mark.skip(
        reason=(
            "historical point-weld compatibility test; "
            "set INCLUDE_DEPRECATED_TESTS=1 to run explicitly"
        )
    )
    for item in items:
        module_name = item.module.__name__.rsplit(".", 1)[-1]
        if module_name in DEPRECATED_TEST_MODULES:
            item.add_marker(skip_deprecated)
