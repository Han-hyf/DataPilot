from __future__ import annotations

import pytest

from scripts.ensure_seeded import _positive_env


def test_positive_seed_environment(monkeypatch) -> None:
    monkeypatch.setenv("SEED_TEST_VALUE", "25")
    assert _positive_env("SEED_TEST_VALUE", 1) == 25


def test_seed_environment_rejects_non_positive_values(monkeypatch) -> None:
    monkeypatch.setenv("SEED_TEST_VALUE", "0")
    with pytest.raises(ValueError, match="必须大于 0"):
        _positive_env("SEED_TEST_VALUE", 1)
