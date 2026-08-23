"""M.E.T.A. conviction grading: more converging edges -> larger position."""

import pytest

from core.professional_mind import ProfessionalMind


@pytest.fixture
def mind():
    return ProfessionalMind({"enabled": True, "log_every_deliberation": False})


@pytest.mark.parametrize("score,expected", [
    (10, 1.0),
    (9, 1.0),
    (8, 0.75),
    (7, 0.75),
    (6, 0.5),
    (5, 0.35),
    (4, 0.35),
    (3, 0.0),
    (1, 0.0),
])
def test_conviction_tiers(mind, score, expected):
    assert mind.conviction_factor(score) == pytest.approx(expected)


def test_conviction_is_monotonic(mind):
    factors = [mind.conviction_factor(s) for s in range(1, 11)]
    assert factors == sorted(factors)


def test_conviction_disabled_returns_full_size():
    mind = ProfessionalMind({
        "log_every_deliberation": False,
        "conviction_sizing": {"enabled": False},
    })
    assert mind.conviction_factor(1) == 1.0
    assert mind.conviction_factor(10) == 1.0


def test_conviction_handles_bad_input(mind):
    assert mind.conviction_factor(None) == 1.0
    assert mind.conviction_factor("abc") == 1.0


def test_conviction_thresholds_are_configurable():
    mind = ProfessionalMind({
        "log_every_deliberation": False,
        "conviction_sizing": {"full_size_score": 7, "reduced_score": 5},
    })
    assert mind.conviction_factor(7) == 1.0
    assert mind.conviction_factor(5) == 0.75
