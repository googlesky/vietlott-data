#!/usr/bin/env python3
"""Update Vietlott lottery data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from src.crawler import update_data
from src.config import PRODUCTS

# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    level="INFO",
)


def main():
    """Update all lottery products."""
    products = ["655", "645", "3d", "3dpro", "535"]

    for product in products:
        config = PRODUCTS.get(product)
        if not config:
            continue

        logger.info(f"Updating {config.name}...")
        try:
            new_records = update_data(product, pages=5)
            if new_records > 0:
                logger.info(f"Added {new_records} new records for {config.name}")
            else:
                logger.info(f"{config.name} is already up to date")
        except Exception as e:
            logger.error(f"Failed to update {config.name}: {e}")


if __name__ == "__main__":
    main()
