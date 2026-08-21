"""NYSE trading calendar: holidays, early closes and trading-day arithmetic.

Implemented without extra dependencies. Weekend-only logic wrongly treats a
market holiday as a missing bar, which made the data-freshness gate reject good
data around holidays; this module removes that false positive.
"""

import logging
from datetime import date, time, timedelta
from functools import lru_cache

logger = logging.getLogger(__name__)

REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
MARKET_OPEN = time(9, 30)

JUNETEENTH_FIRST_YEAR = 2022


def _nth_weekday(year, month, weekday, n):
    """Date of the nth given weekday (Monday=0) in a month."""
    cursor = date(year, month, 1)
    offset = (weekday - cursor.weekday()) % 7
    return cursor + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year, month, weekday):
    """Date of the last given weekday in a month."""
    next_month = date(year + (month == 12), (month % 12) + 1, 1)
    cursor = next_month - timedelta(days=1)
    while cursor.weekday() != weekday:
        cursor -= timedelta(days=1)
    return cursor


def easter_sunday(year):
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(holiday):
    """NYSE observance: Saturday -> preceding Friday, Sunday -> following Monday."""
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


class MarketCalendar:
    """US equity market (NYSE/NASDAQ) session calendar."""

    @staticmethod
    @lru_cache(maxsize=64)
    def holidays(year):
        """Full-day market closures for a calendar year."""
        days = set()

        # New Year's Day: NYSE does not close early for a Saturday Jan 1.
        new_year = date(year, 1, 1)
        if new_year.weekday() == 6:
            days.add(date(year, 1, 2))
        elif new_year.weekday() != 5:
            days.add(new_year)

        days.add(_nth_weekday(year, 1, 0, 3))          # MLK Day
        days.add(_nth_weekday(year, 2, 0, 3))          # Washington's Birthday
        days.add(easter_sunday(year) - timedelta(days=2))  # Good Friday
        days.add(_last_weekday(year, 5, 0))            # Memorial Day

        if year >= JUNETEENTH_FIRST_YEAR:
            days.add(_observed(date(year, 6, 19)))

        days.add(_observed(date(year, 7, 4)))          # Independence Day
        days.add(_nth_weekday(year, 9, 0, 1))          # Labor Day
        days.add(_nth_weekday(year, 11, 3, 4))         # Thanksgiving
        days.add(_observed(date(year, 12, 25)))        # Christmas

        return frozenset(days)

    @staticmethod
    @lru_cache(maxsize=64)
    def early_closes(year):
        """Half sessions closing at 13:00 ET."""
        days = set()

        july_3 = date(year, 7, 3)
        if july_3.weekday() < 5 and july_3 not in MarketCalendar.holidays(year):
            days.add(july_3)

        # Day after Thanksgiving.
        days.add(_nth_weekday(year, 11, 3, 4) + timedelta(days=1))

        christmas_eve = date(year, 12, 24)
        if christmas_eve.weekday() < 5 and christmas_eve not in MarketCalendar.holidays(year):
            days.add(christmas_eve)

        return frozenset(days)

    @classmethod
    def is_holiday(cls, day):
        return day in cls.holidays(day.year)

    @classmethod
    def is_trading_day(cls, day):
        """Weekday that is not a full-day holiday."""
        return day.weekday() < 5 and not cls.is_holiday(day)

    @classmethod
    def is_early_close(cls, day):
        return day in cls.early_closes(day.year)

    @classmethod
    def session_close(cls, day):
        return EARLY_CLOSE if cls.is_early_close(day) else REGULAR_CLOSE

    @classmethod
    def is_session_open(cls, moment):
        """True when `moment` (tz-aware or naive US/Eastern) is inside a session."""
        day = moment.date()
        if not cls.is_trading_day(day):
            return False
        current = moment.time()
        return MARKET_OPEN <= current < cls.session_close(day)

    @classmethod
    def previous_trading_day(cls, reference=None):
        cursor = (reference or date.today()) - timedelta(days=1)
        while not cls.is_trading_day(cursor):
            cursor -= timedelta(days=1)
        return cursor

    @classmethod
    def next_trading_day(cls, reference=None):
        cursor = (reference or date.today()) + timedelta(days=1)
        while not cls.is_trading_day(cursor):
            cursor += timedelta(days=1)
        return cursor

    @classmethod
    def trading_days_between(cls, older, newer):
        """Trading sessions strictly after `older` up to and including `newer`."""
        if older is None or newer is None or newer <= older:
            return 0
        count, cursor = 0, older + timedelta(days=1)
        while cursor <= newer:
            if cls.is_trading_day(cursor):
                count += 1
            cursor += timedelta(days=1)
        return count
