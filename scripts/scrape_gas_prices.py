"""
Scrape national average gas prices from AAA and save to MySQL.

Intended to run daily via cron at 7:30 AM:
  30 7 * * * cd /home/tony/cfp/warship-v2 && .venv/bin/python scripts/scrape_gas_prices.py >> /tmp/gas_scrape.log 2>&1
"""

import sys
import logging
from datetime import datetime
from decimal import Decimal

import httpx
from bs4 import BeautifulSoup
import mysql.connector

# Same credentials as database.py
DB_CONFIG = {
    "host": "172.17.15.228",
    "port": 3306,
    "user": "root",
    "password": "n1cenclean",
    "database": "warship",
}

AAA_URL = "https://gasprices.aaa.com/"
FUEL_TYPES = ["Regular", "Mid-Grade", "Premium", "Diesel", "E85"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def ensure_table(cursor):
    """Create gas_prices table if it doesn't exist."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gas_prices (
            id INT AUTO_INCREMENT PRIMARY KEY,
            fuel_type VARCHAR(20) NOT NULL,
            price DECIMAL(5,3) NOT NULL,
            scraped_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


def scrape_prices() -> list[dict]:
    """Fetch AAA page and parse Current Avg. + Yesterday Avg. prices for all 5 fuel types."""
    log.info("Fetching %s", AAA_URL)
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }
    resp = httpx.get(AAA_URL, timeout=30, follow_redirects=True, headers=headers)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find the table containing gas prices — look for a table with "Current" text
    tables = soup.find_all("table")
    for table in tables:
        text = table.get_text()
        if "Current" in text and "Regular" in text:
            break
    else:
        raise ValueError("Could not find the gas prices table on the page")

    # Parse the header row to map column positions to fuel types
    tbl_headers = [th.get_text(strip=True) for th in table.find("thead").find_all("th")]
    log.info("Table headers: %s", tbl_headers)

    # Find the "Current Avg." row only — history is kept in MySQL
    for row in table.find("tbody").find_all("tr"):
        cells = row.find_all("td")
        label = cells[0].get_text(strip=True)
        if "Current" in label:
            prices = []
            for i, fuel in enumerate(FUEL_TYPES):
                raw = cells[i + 1].get_text(strip=True)
                price = Decimal(raw.replace("$", ""))
                prices.append({"fuel_type": fuel, "price": price})
                log.info("  %s: $%s", fuel, price)
            return prices

    raise ValueError("Could not find 'Current Avg.' row in the table")


def save_to_db(prices: list[dict]):
    """Insert today's scraped prices — history is preserved, never deleted."""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    try:
        ensure_table(cursor)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for p in prices:
            cursor.execute(
                "INSERT INTO gas_prices (fuel_type, price, scraped_at) VALUES (%s, %s, %s)",
                (p["fuel_type"], float(p["price"]), now),
            )
        conn.commit()
        log.info("Saved %d rows to gas_prices", len(prices))
    finally:
        cursor.close()
        conn.close()


def main():
    try:
        prices = scrape_prices()
        save_to_db(prices)
        log.info("Done.")
    except Exception:
        log.exception("Gas price scrape failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
