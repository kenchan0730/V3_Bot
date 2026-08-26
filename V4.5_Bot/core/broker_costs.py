"""Single source of truth for per-order cost, shared by backtest and sizing.

Commission is the dominant variable at small account size, so it lives in one
place rather than being duplicated in ``backtest`` and ``retail_mind``. A
5-year replay of the same 40 symbols and the same signals:

    ibkr_pro ($1 order minimum)          +39%
    zero commission (lite/alpaca/schwab) +155%

The strategy is identical in both rows. The gap is the fixed fee.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

BUILTIN_PROFILES = {
    "ibkr_pro": {"commission_per_share": 0.005, "commission_minimum": 1.0},
    "ibkr_lite": {"commission_per_share": 0.0, "commission_minimum": 0.0},
    "alpaca": {"commission_per_share": 0.0, "commission_minimum": 0.0},
    "schwab": {"commission_per_share": 0.0, "commission_minimum": 0.0},
    "custom": {"commission_per_share": 0.0, "commission_minimum": 0.0},
}

DEFAULT_PROFILE = "ibkr_pro"


@dataclass(frozen=True)
class BrokerCosts:
    name: str = DEFAULT_PROFILE
    commission_per_share: float = 0.005
    commission_minimum: float = 1.0

    @property
    def is_commission_free(self) -> bool:
        return self.commission_per_share <= 0 and self.commission_minimum <= 0

    def commission(self, shares: int) -> float:
        if shares <= 0:
            return 0.0
        return max(self.commission_minimum, shares * self.commission_per_share)

    def round_trip(self, shares: int) -> float:
        return self.commission(shares) * 2

    def describe(self) -> str:
        if self.is_commission_free:
            return f"{self.name}: 零佣金"
        return (
            f"{self.name}: ${self.commission_per_share}/股, "
            f"每單最低 ${self.commission_minimum}"
        )


def resolve(config=None) -> BrokerCosts:
    """Build the active cost model from ``config.broker`` (or legacy backtest keys)."""
    cfg = config or {}
    broker_cfg = cfg.get("broker") or {}
    name = str(broker_cfg.get("profile") or DEFAULT_PROFILE).lower()

    profiles = {**BUILTIN_PROFILES}
    for key, value in (broker_cfg.get("profiles") or {}).items():
        profiles[str(key).lower()] = {**profiles.get(str(key).lower(), {}), **(value or {})}

    if name not in profiles:
        logger.warning("未知的券商設定 '%s'，改用 %s", name, DEFAULT_PROFILE)
        name = DEFAULT_PROFILE
    values = profiles[name]

    # Legacy configs put the fee model under `backtest`; honour it so an older
    # config file keeps charging what it used to.
    legacy = cfg.get("backtest") or {}
    per_share = legacy.get("commission_per_share", values.get("commission_per_share", 0.005))
    minimum = legacy.get("commission_minimum", values.get("commission_minimum", 1.0))

    return BrokerCosts(
        name=name,
        commission_per_share=float(per_share),
        commission_minimum=float(minimum),
    )
