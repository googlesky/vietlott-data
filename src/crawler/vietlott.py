"""Vietlott data crawler and loader using HTML scraping."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import polars as pl
from bs4 import BeautifulSoup
from loguru import logger

from src.config import LotteryConfig, PRODUCTS, DATA_DIR


class VietlottCrawler:
    """Crawler for Vietlott lottery results using HTML scraping."""

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "text/plain; charset=utf-8",
        "Accept": "*/*",
        "Origin": "https://vietlott.vn",
        "Referer": "https://vietlott.vn/",
    }

    # API endpoints for each product (fallback, prefer config.url)
    ENDPOINTS = {
        "645": "https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.Game645ResultDetailWebPart,Vietlott.PlugIn.WebParts.ashx",
        "655": "https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.Game655ResultDetailWebPart,Vietlott.PlugIn.WebParts.ashx",
        "3D": "https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.GameMax3DResultDetailWebPart,Vietlott.PlugIn.WebParts.ashx",
        "3DPRO": "https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.GameMax3DProResultDetailWebPart,Vietlott.PlugIn.WebParts.ashx",
        "535": "https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.Game535ResultDetailWebPart,Vietlott.PlugIn.WebParts.ashx",
        "KENO": "https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.GameKenoResultDetailWebPart,Vietlott.PlugIn.WebParts.ashx",
    }

    def __init__(self, config: LotteryConfig):
        self.config = config
        self.client = httpx.Client(
            headers=self.HEADERS,
            timeout=60.0,
            follow_redirects=True,
        )
        # Use config.url if it's a ResultDetail endpoint, otherwise use ENDPOINTS
        if "ResultDetail" in config.url:
            self.endpoint = config.url
        else:
            self.endpoint = self.ENDPOINTS.get(config.sms_code, self.ENDPOINTS["645"])
        self.key = "23bbd667"  # Common key for all products

    def _build_request_body(self, draw_id: str = "") -> dict[str, Any]:
        """Build request body for API call."""
        orender_info = {
            "SiteId": "main.frontend.vi",
            "SiteAlias": "main.vi",
            "UserSessionId": "",
            "SiteLang": "vi",
            "IsPageDesign": False,
            "ExtraParam1": "",
            "ExtraParam2": "",
            "ExtraParam3": "",
            "SiteURL": "",
            "WebPage": None,
            "SiteName": "Vietlott",
            "OrgPageAlias": None,
            "PageAlias": None,
            "RefKey": None,
            "FullPageAlias": None,
        }

        return {
            "ORenderInfo": orender_info,
            "Key": self.key,
            "DrawId": draw_id,
        }

    def _parse_response(self, html_content: str) -> dict[str, Any] | None:
        """Parse HTML response to extract lottery result.

        Dispatches to specific parser based on product_type.

        Returns:
            Dict with keys: date, id, result, prev_draw_id
            Or None if parsing fails
        """
        if self.config.product_type == "max3d":
            return self._parse_max3d_response(html_content)
        else:
            return self._parse_power_response(html_content)

    def _parse_power_response(self, html_content: str) -> dict[str, Any] | None:
        """Parse Power 645/655 HTML response.

        Returns:
            Dict with keys: date, id, result, prev_draw_id
            Or None if parsing fails
        """
        soup = BeautifulSoup(html_content, "lxml")

        try:
            # Extract draw ID and date from header
            # Pattern: "Kỳ quay thưởng <b>#01458</b> ngày <b>14/01/2026</b>"
            h5 = soup.select_one("h5")
            if not h5:
                logger.warning("No H5 element found")
                return None

            h5_text = h5.get_text()

            # Extract draw ID
            id_match = re.search(r"#(\d+)", h5_text)
            if not id_match:
                logger.warning(f"No draw ID found in: {h5_text}")
                return None
            draw_id = id_match.group(1)

            # Extract date
            date_match = re.search(r"(\d{2}/\d{2}/\d{4})", h5_text)
            if not date_match:
                logger.warning(f"No date found in: {h5_text}")
                return None
            date_str = date_match.group(1)
            date_formatted = datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y-%m-%d")

            # Extract result numbers from first result div only
            result_div = soup.select_one(".day_so_ket_qua_v2")
            if not result_div:
                result_div = soup.select_one(".day_so_ket_qua")

            if not result_div:
                logger.warning("No result div found")
                return None

            spans = result_div.select("span")
            numbers = []
            for span in spans:
                text = span.get_text().strip()
                if text.isdigit():
                    numbers.append(int(text))

            if len(numbers) < self.config.numbers_to_pick:
                logger.warning(f"Not enough numbers found: {numbers}")
                return None

            # Get only main numbers (first 6)
            result_numbers = numbers[:self.config.numbers_to_pick]

            # Find previous draw ID from navigation link
            prev_draw_id = None
            prev_link = soup.select_one("a.btn_chuyendulieu_left")
            if prev_link:
                href = prev_link.get("href", "")
                prev_match = re.search(r"ClientDrawResult\(['\"](\d+)['\"]\)", href)
                if prev_match:
                    prev_draw_id = prev_match.group(1)

            return {
                "date": date_formatted,
                "id": draw_id,
                "result": result_numbers,
                "process_time": datetime.now().isoformat(),
                "prev_draw_id": prev_draw_id,
            }

        except Exception as e:
            logger.error(f"Failed to parse Power response: {e}")
            return None

    def _parse_max3d_response(self, html_content: str) -> dict[str, Any] | None:
        """Parse Max 3D / Max 3D Pro HTML response.

        Max 3D has 20 numbers per draw:
        - Giải Đặc biệt: 2 numbers
        - Giải Nhất: 4 numbers
        - Giải Nhì: 6 numbers
        - Giải Ba: 8 numbers

        Each number is 3 digits (000-999).

        Returns:
            Dict with keys: date, id, result (list of 3-digit strings), prev_draw_id
            Or None if parsing fails
        """
        soup = BeautifulSoup(html_content, "lxml")

        try:
            # Extract draw ID and date from header
            h5 = soup.select_one("h5")
            if not h5:
                logger.warning("No H5 element found in Max 3D response")
                return None

            h5_text = h5.get_text()

            # Extract draw ID
            id_match = re.search(r"#(\d+)", h5_text)
            if not id_match:
                logger.warning(f"No draw ID found in: {h5_text}")
                return None
            draw_id = id_match.group(1)

            # Extract date
            date_match = re.search(r"(\d{2}/\d{2}/\d{4})", h5_text)
            if not date_match:
                logger.warning(f"No date found in: {h5_text}")
                return None
            date_str = date_match.group(1)
            date_formatted = datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y-%m-%d")

            # Extract all 3D numbers
            # Each number is in a div.day_so_ket_qua_v2 with span.bong_tron for each digit
            result_divs = soup.select(".day_so_ket_qua_v2")
            numbers = []

            for div in result_divs:
                spans = div.select("span.bong_tron")
                if spans:
                    digits = [span.get_text().strip() for span in spans]
                    if all(d.isdigit() for d in digits) and len(digits) == 3:
                        # Format as 3-digit string (e.g., "007", "123")
                        number_str = "".join(digits)
                        numbers.append(number_str)

            if len(numbers) < 2:
                logger.warning(f"Not enough 3D numbers found: {numbers}")
                return None

            # Find previous draw ID from navigation link
            prev_draw_id = None
            prev_link = soup.select_one("a.btn_chuyendulieu_left")
            if prev_link:
                href = prev_link.get("href", "")
                prev_match = re.search(r"ClientDrawResult\(['\"](\d+)['\"]\)", href)
                if prev_match:
                    prev_draw_id = prev_match.group(1)

            return {
                "date": date_formatted,
                "id": draw_id,
                "result": numbers,  # List of 3-digit strings
                "process_time": datetime.now().isoformat(),
                "prev_draw_id": prev_draw_id,
            }

        except Exception as e:
            logger.error(f"Failed to parse Max 3D response: {e}")
            return None

    def fetch_draw(self, draw_id: str = "") -> dict[str, Any] | None:
        """Fetch a single draw result.

        Args:
            draw_id: Draw ID to fetch. Empty string for latest draw.

        Returns:
            Dict with draw data, or None if failed
        """
        headers = dict(self.HEADERS)
        headers["X-AjaxPro-Method"] = "ServerSideDrawResult"

        body = self._build_request_body(draw_id)

        try:
            response = self.client.post(
                self.endpoint,
                content=json.dumps(body),
                headers=headers,
            )
            response.raise_for_status()

            res_json = response.json()

            # HTML is in RetExtraParam1
            html_content = res_json.get("value", {}).get("RetExtraParam1", "")
            if not html_content:
                logger.warning(f"No HTML content for draw {draw_id}")
                return None

            return self._parse_response(html_content)

        except Exception as e:
            logger.error(f"Failed to fetch draw {draw_id}: {e}")
            return None

    def crawl(self, max_records: int = 50, existing_ids: set[str] | None = None) -> list[dict[str, Any]]:
        """Crawl lottery results by following prev_draw_id links.

        Args:
            max_records: Maximum number of records to crawl
            existing_ids: Set of draw IDs already in database (to stop early)

        Returns:
            List of draw records (newest first)
        """
        if existing_ids is None:
            existing_ids = set()

        all_data = []
        draw_id = ""  # Start with latest

        for i in range(max_records):
            logger.info(f"Crawling {self.config.name} draw {draw_id or 'latest'}...")

            result = self.fetch_draw(draw_id)
            if not result:
                logger.warning(f"Failed to fetch draw {draw_id}, stopping")
                break

            current_id = result["id"]

            # Check if we already have this draw
            if current_id in existing_ids:
                logger.info(f"Draw {current_id} already exists, stopping")
                break

            # Remove prev_draw_id from result before storing
            prev_draw_id = result.pop("prev_draw_id", None)
            all_data.append(result)

            logger.info(f"  -> Draw #{current_id} on {result['date']}: {result['result']}")

            # Move to previous draw
            if prev_draw_id:
                draw_id = prev_draw_id
            else:
                logger.info("No previous draw link, stopping")
                break

        logger.info(f"Crawled {len(all_data)} records for {self.config.name}")
        return all_data

    def close(self):
        """Close the HTTP client."""
        self.client.close()


def load_data(product: str) -> pl.DataFrame:
    """Load lottery data from local file.

    Args:
        product: "655" or "645"

    Returns:
        DataFrame with columns: date, id, result, process_time
    """
    config = PRODUCTS.get(product)
    if not config:
        raise ValueError(f"Unknown product: {product}. Use '655' or '645'.")

    if not config.data_file.exists():
        raise FileNotFoundError(f"Data file not found: {config.data_file}")

    df = pl.read_ndjson(config.data_file)

    # Ensure date is proper type
    if df["date"].dtype != pl.Date:
        df = df.with_columns(pl.col("date").str.to_date("%Y-%m-%d"))

    # Sort by date
    df = df.sort("date")

    logger.info(
        f"Loaded {len(df)} records for {product}: "
        f"{df['date'].min()} to {df['date'].max()}"
    )

    return df


def update_data(product: str, pages: int = 3) -> int:
    """Update lottery data by crawling latest results.

    Args:
        product: "655" or "645"
        pages: Maximum number of new draws to fetch (not pages anymore)

    Returns:
        Number of new records added
    """
    config = PRODUCTS.get(product)
    if not config:
        raise ValueError(f"Unknown product: {product}. Use '655' or '645'.")

    # Load existing IDs
    existing_ids = set()
    existing_data = []
    if config.data_file.exists():
        existing_df = pl.read_ndjson(config.data_file)
        existing_ids = set(existing_df["id"].to_list())
        existing_data = existing_df.to_dicts()
        logger.info(f"Existing data: {len(existing_data)} records, latest ID in set")

    crawler = VietlottCrawler(config)

    try:
        # Crawl new data (will stop when hitting existing ID)
        new_data = crawler.crawl(max_records=pages * 10, existing_ids=existing_ids)
    finally:
        crawler.close()

    if not new_data:
        logger.info("No new data crawled.")
        return 0

    # Filter to ensure no duplicates (should already be filtered by crawler)
    new_records = [r for r in new_data if r["id"] not in existing_ids]

    if not new_records:
        logger.info("No new records to add (all already exist).")
        return 0

    # Combine and save
    all_data = existing_data + new_records

    # Sort by date
    all_data.sort(key=lambda x: x["date"])

    # Write to file
    config.data_file.parent.mkdir(parents=True, exist_ok=True)

    with open(config.data_file, "w") as f:
        for record in all_data:
            f.write(json.dumps(record) + "\n")

    logger.info(f"Added {len(new_records)} new records to {config.data_file}")
    return len(new_records)
