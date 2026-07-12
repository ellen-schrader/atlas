"""Offline tests for the Teams-PDF importer's filename→date logic."""

from __future__ import annotations

from datetime import UTC, datetime

from api.import_teams_pdfs import window_date


def test_window_date_months_one_to_seven_use_base_year():
    assert window_date("0903_2303.pdf", 2026) == datetime(2026, 3, 9, 12, 0, tzinfo=UTC)
    assert window_date("0107_1107.pdf", 2026) == datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    assert window_date("2601_1102.pdf", 2026) == datetime(2026, 1, 26, 12, 0, tzinfo=UTC)


def test_window_date_autumn_winter_rolls_to_prior_year():
    # A December file belongs to the prior year (avoids future-dating).
    assert window_date("1712_1201.pdf", 2026) == datetime(2025, 12, 17, 12, 0, tzinfo=UTC)


def test_window_date_three_digit_token():
    # "903" -> day 9, month 03.
    assert window_date("903_2303.pdf", 2026) == datetime(2026, 3, 9, 12, 0, tzinfo=UTC)


def test_window_date_rejects_garbage():
    assert window_date("readme.pdf", 2026) is None
    assert window_date("9999_0000.pdf", 2026) is None  # month 99 invalid
    assert window_date("3202_x.pdf", 2026) is None  # day 32 invalid
