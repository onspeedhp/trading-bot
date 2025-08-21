#!/usr/bin/env python3
"""
Paper trading launcher script.

This script launches the trading bot in paper trading mode using the paper.yaml configuration.
Paper trading simulates trades without using real money, making it safe for strategy testing.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from bot.runner.pipeline import main


if __name__ == "__main__":
    # Set up arguments for paper trading
    sys.argv = ["solbot", "--config", "configs/paper.yaml", "--profile", "paper"]

    try:
        # Run the main pipeline
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nPaper trading stopped by user.")
        sys.exit(0)
    except Exception as e:
        print(f"Error running paper trading: {e}")
        sys.exit(1)
