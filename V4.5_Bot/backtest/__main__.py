"""Package entry point for ``python -m backtest``."""

import sys

from backtest.main import main

if __name__ == "__main__":
    sys.exit(main())
