"""
Entry point — run this file to start the trading bot.

    python main.py

Make sure you have filled in config/settings.json with your Alpaca API keys first.
"""
import sys
import os

# Allow `from src.xxx import ...` from anywhere
sys.path.insert(0, os.path.dirname(__file__))

from src.config_manager import load_config
from src.logger_setup import setup_logger
from src.bot import TradingBot

logger = setup_logger("main")


def main():
    logger.info("Loading configuration...")
    try:
        cfg = load_config()
    except (FileNotFoundError, ValueError) as e:
        logger.critical(f"Config error: {e}")
        sys.exit(1)

    bot = TradingBot(cfg)
    bot.run()


if __name__ == "__main__":
    main()
