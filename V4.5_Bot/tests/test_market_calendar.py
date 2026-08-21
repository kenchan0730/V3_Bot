from datetime import date, datetime, time

import pytest

from core.market_calendar import (
    EARLY_CLOSE,
    REGULAR_CLOSE,
    MarketCalendar,
    easter_sunday,
)


# ----- Easter / Good Friday -----

@pytest.mark.parametrize("year,expected", [
    (2024, date(2024, 3, 31)),
    (2025, date(2025, 4, 20)),
    (2026, date(2026, 4, 5)),
])
def test_easter_sunday(year, expected):
    assert easter_sunday(year) == expected


def test_good_friday_is_a_holiday():
    assert MarketCalendar.is_holiday(date(2024, 3, 29))
    assert MarketCalendar.is_holiday(date(2026, 4, 3))


# ----- fixed and floating holidays -----

@pytest.mark.parametrize("day", [
    date(2024, 1, 1),    # New Year's Day
    date(2024, 1, 15),   # MLK Day
    date(2024, 2, 19),   # Washington's Birthday
    date(2024, 5, 27),   # Memorial Day
    date(2024, 6, 19),   # Juneteenth
    date(2024, 7, 4),    # Independence Day
    date(2024, 9, 2),    # Labor Day
    date(2024, 11, 28),  # Thanksgiving
    date(2024, 12, 25),  # Christmas
])
def test_known_2024_holidays(day):
    assert MarketCalendar.is_holiday(day)


def test_regular_weekday_is_not_a_holiday():
    assert not MarketCalendar.is_holiday(date(2024, 3, 5))


def test_juneteenth_not_observed_before_2022():
    assert not MarketCalendar.is_holiday(date(2021, 6, 18))
    assert MarketCalendar.is_holiday(date(2022, 6, 20))  # Jun 19 was a Sunday


# ----- observance rules -----

def test_saturday_holiday_observed_on_friday():
    # Independence Day 2020 fell on a Saturday -> observed Friday Jul 3.
    assert MarketCalendar.is_holiday(date(2020, 7, 3))


def test_sunday_holiday_observed_on_monday():
    # Christmas 2022 fell on a Sunday -> observed Monday Dec 26.
    assert MarketCalendar.is_holiday(date(2022, 12, 26))


def test_new_year_on_saturday_is_not_observed():
    # NYSE does not close on Dec 31 when Jan 1 falls on a Saturday.
    assert not MarketCalendar.is_holiday(date(2021, 12, 31))
    assert not MarketCalendar.is_holiday(date(2022, 1, 1))


def test_new_year_on_sunday_observed_monday():
    assert MarketCalendar.is_holiday(date(2023, 1, 2))


# ----- trading days -----

def test_weekend_is_not_a_trading_day():
    assert not MarketCalendar.is_trading_day(date(2024, 3, 2))  # Saturday
    assert not MarketCalendar.is_trading_day(date(2024, 3, 3))  # Sunday


def test_holiday_is_not_a_trading_day():
    assert not MarketCalendar.is_trading_day(date(2024, 12, 25))


def test_normal_weekday_is_a_trading_day():
    assert MarketCalendar.is_trading_day(date(2024, 3, 5))


def test_previous_trading_day_skips_holiday():
    # Dec 26 2024 back to Dec 24 (Dec 25 is Christmas).
    assert MarketCalendar.previous_trading_day(date(2024, 12, 26)) == date(2024, 12, 24)


def test_previous_trading_day_skips_weekend():
    assert MarketCalendar.previous_trading_day(date(2024, 3, 4)) == date(2024, 3, 1)


def test_next_trading_day_skips_holiday():
    assert MarketCalendar.next_trading_day(date(2024, 12, 24)) == date(2024, 12, 26)


def test_trading_days_between_excludes_holiday():
    # Dec 24 -> Dec 27 2024: Dec 26 and Dec 27 count, Dec 25 does not.
    assert MarketCalendar.trading_days_between(date(2024, 12, 24), date(2024, 12, 27)) == 2


def test_trading_days_between_excludes_weekend():
    assert MarketCalendar.trading_days_between(date(2024, 3, 1), date(2024, 3, 5)) == 2


def test_trading_days_between_handles_bad_input():
    assert MarketCalendar.trading_days_between(None, date(2024, 3, 1)) == 0
    assert MarketCalendar.trading_days_between(date(2024, 3, 5), date(2024, 3, 1)) == 0


# ----- session hours -----

def test_early_close_day_after_thanksgiving():
    assert MarketCalendar.is_early_close(date(2024, 11, 29))
    assert MarketCalendar.session_close(date(2024, 11, 29)) == EARLY_CLOSE


def test_early_close_christmas_eve():
    assert MarketCalendar.is_early_close(date(2024, 12, 24))


def test_regular_close_on_normal_day():
    assert MarketCalendar.session_close(date(2024, 3, 5)) == REGULAR_CLOSE


def test_session_open_during_regular_hours():
    assert MarketCalendar.is_session_open(datetime(2024, 3, 5, 10, 30)) is True


def test_session_closed_before_open():
    assert MarketCalendar.is_session_open(datetime(2024, 3, 5, 9, 0)) is False


def test_session_closed_after_close():
    assert MarketCalendar.is_session_open(datetime(2024, 3, 5, 16, 30)) is False


def test_session_closed_on_holiday():
    assert MarketCalendar.is_session_open(datetime(2024, 12, 25, 11, 0)) is False


def test_session_closed_on_weekend():
    assert MarketCalendar.is_session_open(datetime(2024, 3, 2, 11, 0)) is False


def test_early_close_afternoon_is_closed():
    assert MarketCalendar.is_session_open(datetime(2024, 11, 29, 14, 0)) is False
    assert MarketCalendar.is_session_open(datetime(2024, 11, 29, 12, 0)) is True


def test_open_exactly_at_bell():
    assert MarketCalendar.is_session_open(datetime(2024, 3, 5, 9, 30)) is True


def test_closed_exactly_at_bell():
    assert MarketCalendar.is_session_open(datetime(2024, 3, 5, 16, 0)) is False


# ----- integration with RiskManager -----

def test_risk_manager_respects_calendar():
    from core.risk_manager import RiskManager

    assert RiskManager.is_market_open(datetime(2024, 12, 25, 11, 0)) is False
    assert RiskManager.is_market_open(datetime(2024, 3, 5, 11, 0)) is True


# ----- freshness integration -----

def test_freshness_tolerates_holiday_gap():
    """A bar from Dec 24 read on Dec 26 is 1 session old, not 2 calendar days."""
    import pandas as pd

    from core.data_utils import validate_freshness

    df = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]},
        index=[pd.Timestamp("2024-12-24")],
    )
    is_fresh, age, _ = validate_freshness(df, max_age_trading_days=1, reference=date(2024, 12, 26))
    assert is_fresh is True
    assert age == 1
