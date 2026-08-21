#!/usr/bin/env python3
"""Refresh the dynamic watchlist (core + ranked satellite)."""

import argparse
import logging
import sys

from core.config_loader import load_config
from core.fundamental_filter import FundamentalFilter
from core.logging_setup import configure_logging
from core.watchlist_manager import WatchlistManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Refresh V4.5 watchlist")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--force", action="store_true", help="Ignore refresh interval")
    args = parser.parse_args(argv)

    config = load_config(args.config, args.env)
    configure_logging(config.get("logging", {}))

    fundamental = FundamentalFilter(config.get("fundamental", {}))
    mgr = WatchlistManager(config.get("watchlist", {}))
    active = mgr.refresh(fundamental_filter=fundamental, force=args.force)
    print(f"Active watchlist ({len(active)}): {', '.join(active)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
