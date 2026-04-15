"""Vietlott data crawler and loader using HTML scraping."""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import polars as pl
from bs4 import BeautifulSoup
from loguru import logger

from src.config import LotteryConfig, PRODUCTS, DATA_DIR


UPSTREAM_BASE_URL = "https://raw.githubusercontent.com/vietvudanh/vietlott-data/main/data"
UPSTREAM_FILES = {
    "655": "power655.jsonl",
    "645": "power645.jsonl",
    "3d": "3d.jsonl",
    "3dpro": "3d_pro.jsonl",
    "535": "power535.jsonl",
    "keno": "keno.jsonl",
}
KETQUADIENTOAN_BASE_URL = "https://www.ketquadientoan.com"
KETQUADIENTOAN_SLUGS = {
    "655": "power-655",
    "645": "mega-6-45",
    "3d": "max-3d",
    "3dpro": "max3d-pro",
    "535": "lotto-535",
}
KETQUADIENTOAN_WEEKDAYS = {
    "655": {1, 3, 5},   # Tue, Thu, Sat
    "645": {2, 4, 6},   # Wed, Fri, Sun
    "3d": {0, 2, 4},    # Mon, Wed, Fri
    "3dpro": {1, 3, 5}, # Tue, Thu, Sat
}
KETQUADIENTOAN_LOOKBACK_DAYS = 30
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class VietlottCrawler:
    """Crawler for Vietlott lottery results using HTML scraping."""

    HEADERS = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "text/plain; charset=utf-8",
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
        self._warmed_up = False
        self.last_fetch_failed = False
        if self.config.result_page_url:
            self.client.headers["Referer"] = self.config.result_page_url

    def _warm_up_session(self) -> None:
        """Prime session cookies by loading the public result page."""
        if not self.config.result_page_url:
            return

        try:
            self.client.get(
                self.config.result_page_url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "https://vietlott.vn/",
                },
            )
        except Exception as e:
            logger.warning(f"Warm-up request failed: {e}")

    def _fetch_latest_from_page(self) -> dict[str, Any] | None:
        """Fetch latest draw by scraping the public result page."""
        if not self.config.result_page_url:
            return None

        response = self.client.get(
            self.config.result_page_url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://vietlott.vn/",
            },
        )
        response.raise_for_status()
        return self._parse_response(response.text)

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
        if draw_id == "" and self.config.result_page_url:
            try:
                latest = self._fetch_latest_from_page()
                if latest:
                    self.last_fetch_failed = False
                    return latest
            except Exception as e:
                logger.warning(f"Result page fetch failed, falling back to Ajax: {e}")

        headers = dict(self.client.headers)
        headers["X-AjaxPro-Method"] = "ServerSideDrawResult"
        headers["X-Requested-With"] = "XMLHttpRequest"
        if self.config.result_page_url:
            headers["Referer"] = self.config.result_page_url

        body = self._build_request_body(draw_id)

        try:
            response = self.client.post(self.endpoint, content=json.dumps(body), headers=headers)
            if response.status_code == 403 and not self._warmed_up:
                logger.warning("403 from Ajax endpoint, refreshing session and retrying")
                self._warm_up_session()
                self._warmed_up = True
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
                self.last_fetch_failed = True
                logger.warning(f"No HTML content for draw {draw_id}")
                return None

            parsed = self._parse_response(html_content)
            self.last_fetch_failed = parsed is None
            return parsed

        except httpx.HTTPStatusError as e:
            if (
                e.response is not None
                and e.response.status_code == 403
                and draw_id == ""
            ):
                logger.warning("Ajax blocked for latest draw, falling back to result page")
                try:
                    latest = self._fetch_latest_from_page()
                    self.last_fetch_failed = latest is None
                    return latest
                except Exception as fallback_error:
                    logger.error(f"Fallback fetch failed: {fallback_error}")
            self.last_fetch_failed = True
            logger.error(f"Failed to fetch draw {draw_id}: {e}")
            return None
        except Exception as e:
            self.last_fetch_failed = True
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


def _normalize_max3d_result(result: Any) -> list[str] | None:
    """Flatten Max 3D/3D Pro prize dict into a list of 20 3-digit strings."""
    if isinstance(result, list):
        return [str(item).zfill(3) for item in result]

    if not isinstance(result, dict):
        return None

    key_map = {str(k).strip().lower(): k for k in result.keys()}
    order = ["giải đặc biệt", "giải nhất", "giải nhì", "giải ba"]
    numbers: list[str] = []

    for key in order:
        original_key = key_map.get(key)
        if not original_key:
            continue
        values = result.get(original_key) or []
        for value in values:
            numbers.append(str(value).zfill(3))

    return numbers or None


def _transform_upstream_record(product: str, record: dict[str, Any]) -> dict[str, Any] | None:
    """Transform upstream record to local schema."""
    if "date" not in record or "id" not in record:
        return None

    result = record.get("result")
    if product in {"3d", "3dpro"}:
        normalized = _normalize_max3d_result(result)
        if not normalized:
            return None
        record = {
            "date": record["date"],
            "id": record["id"],
            "result": normalized,
            "process_time": record.get("process_time", datetime.now().isoformat()),
        }
        return record

    if product == "535" and isinstance(result, list) and len(result) > 5:
        result = result[:5]

    record = {
        "date": record["date"],
        "id": record["id"],
        "result": result,
        "process_time": record.get("process_time", datetime.now().isoformat()),
    }
    return record


def _extract_draw_date(text: str) -> str | None:
    """Extract a YYYY-MM-DD date from Vietnamese page text."""
    match = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")


def _build_record(draw_id: str, draw_date: str, result: list[Any]) -> dict[str, Any]:
    """Build a record in the local JSONL schema."""
    return {
        "date": draw_date,
        "id": draw_id,
        "result": result,
        "process_time": datetime.now().isoformat(),
    }


def _parse_ketquadientoan_power_like_page(product: str, html_content: str) -> list[dict[str, Any]]:
    """Parse Power 6/55, Mega 6/45, and Lotto 5/35 date pages."""
    soup = BeautifulSoup(html_content, "lxml")
    records: list[dict[str, Any]] = []

    for block in soup.select(".box_kqxsdt"):
        title = block.select_one(".title_tt")
        if not title:
            continue

        title_text = title.get_text(" ", strip=True)
        id_match = re.search(r"#(\d+)", title_text)
        draw_date = _extract_draw_date(title_text)
        if not id_match or not draw_date:
            continue

        numbers = [
            int(span.get_text(strip=True))
            for span in block.select(".box_ketqua span")
            if span.get_text(strip=True).isdigit()
        ]
        if not numbers:
            continue

        if product == "645":
            numbers = numbers[:6]
        elif product == "655":
            numbers = numbers[:7]
        elif product == "535":
            numbers = numbers[:5]

        records.append(_build_record(id_match.group(1), draw_date, numbers))

    return records


def _extract_max3d_numbers(result_cell: Any) -> list[str]:
    """Extract ordered 3-digit numbers from a Max 3D result cell."""
    numbers: list[str] = []

    for group in result_cell.select("div"):
        digits = [span.get_text(strip=True) for span in group.select("span")]
        if len(digits) == 3 and all(digit.isdigit() for digit in digits):
            numbers.append("".join(digits))

    return numbers


def _parse_ketquadientoan_max3d_page(product: str, html_content: str) -> list[dict[str, Any]]:
    """Parse Max 3D and Max 3D Pro date pages."""
    soup = BeautifulSoup(html_content, "lxml")
    records: list[dict[str, Any]] = []

    if product == "3d":
        wanted_labels = ("Đặc biệt", "Giải nhất", "Giải nhì", "Giải ba")
    else:
        wanted_labels = ("Đặc Biệt", "Nhất", "Nhì", "Ba")

    for header in soup.select(".boxheader_outner_4d"):
        header_text = header.get_text(" ", strip=True)
        id_match = re.search(r"#(\d+)", header_text)
        draw_date = _extract_draw_date(header_text)
        if not id_match or not draw_date:
            continue

        box = header.find_next_sibling("div", class_="boxkqMax4d")
        if box is None:
            continue

        table = box.select_one("table.tblMax3d")
        if table is None:
            continue

        numbers: list[str] = []
        for row in table.select("tr"):
            cols = row.find_all(["td", "th"])
            if len(cols) < 2:
                continue

            label = cols[0].get_text(" ", strip=True)
            if any(label.startswith(wanted_label) for wanted_label in wanted_labels):
                numbers.extend(_extract_max3d_numbers(cols[1]))

        if numbers:
            records.append(_build_record(id_match.group(1), draw_date, numbers))

    return records


def _parse_ketquadientoan_page(product: str, html_content: str) -> list[dict[str, Any]]:
    """Parse a ketquadientoan.com result page into local records."""
    if product in {"655", "645", "535"}:
        return _parse_ketquadientoan_power_like_page(product, html_content)
    if product in {"3d", "3dpro"}:
        return _parse_ketquadientoan_max3d_page(product, html_content)
    raise ValueError(f"Unsupported ketquadientoan product: {product}")


def sync_from_ketquadientoan(product: str, config: LotteryConfig) -> int:
    """Sync data from ketquadientoan.com pages when Vietlott blocks the runner."""
    slug = KETQUADIENTOAN_SLUGS.get(product)
    if not slug:
        raise ValueError(f"No ketquadientoan mapping for product: {product}")

    existing_ids = set()
    existing_data: list[dict[str, Any]] = []
    if config.data_file.exists():
        existing_df = pl.read_ndjson(config.data_file)
        existing_ids = set(existing_df["id"].to_list())
        existing_data = existing_df.to_dicts()

    new_records: dict[str, dict[str, Any]] = {}
    today = datetime.now().date()
    allowed_weekdays = KETQUADIENTOAN_WEEKDAYS.get(product)

    with httpx.Client(
        timeout=60.0,
        follow_redirects=True,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    ) as client:
        for offset in range(KETQUADIENTOAN_LOOKBACK_DAYS + 1):
            target_date = today - timedelta(days=offset)
            if allowed_weekdays and target_date.weekday() not in allowed_weekdays:
                continue

            url = (
                f"{KETQUADIENTOAN_BASE_URL}/ket-qua-xo-so-dien-toan-"
                f"{slug}/{target_date.strftime('%d-%m-%Y')}.html"
            )

            response = client.get(url)
            response.raise_for_status()

            for record in _parse_ketquadientoan_page(product, response.text):
                record_id = record["id"]
                if record_id in existing_ids or record_id in new_records:
                    continue
                new_records[record_id] = record

    if not new_records:
        logger.info("No new records found in ketquadientoan.com.")
        return 0

    all_data = existing_data + list(new_records.values())
    all_data.sort(key=lambda x: (x["date"], x["id"]))

    config.data_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config.data_file, "w") as f:
        for record in all_data:
            f.write(json.dumps(record) + "\n")

    logger.info(
        f"Added {len(new_records)} new records from ketquadientoan.com to {config.data_file}"
    )
    return len(new_records)


def sync_from_upstream(product: str, config: LotteryConfig) -> int:
    """Sync data from upstream GitHub dataset when direct crawling is blocked."""
    upstream_file = UPSTREAM_FILES.get(product)
    if not upstream_file:
        raise ValueError(f"No upstream mapping for product: {product}")

    url = f"{UPSTREAM_BASE_URL}/{upstream_file}"

    existing_ids = set()
    existing_data: list[dict[str, Any]] = []
    if config.data_file.exists():
        existing_df = pl.read_ndjson(config.data_file)
        existing_ids = set(existing_df["id"].to_list())
        existing_data = existing_df.to_dicts()

    new_records: list[dict[str, Any]] = []
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                record = json.loads(line)
                transformed = _transform_upstream_record(product, record)
                if not transformed:
                    continue
                if transformed["id"] in existing_ids:
                    continue
                new_records.append(transformed)

    if not new_records:
        logger.info("No new records found in upstream dataset.")
        return 0

    all_data = existing_data + new_records
    all_data.sort(key=lambda x: x["date"])

    config.data_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config.data_file, "w") as f:
        for record in all_data:
            f.write(json.dumps(record) + "\n")

    logger.info(f"Added {len(new_records)} new records from upstream to {config.data_file}")
    return len(new_records)


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
        if os.environ.get("GITHUB_ACTIONS") == "true" and crawler.last_fetch_failed:
            logger.info("Live crawl failed in GitHub Actions, trying ketquadientoan.com.")
            try:
                return sync_from_ketquadientoan(product, config)
            except Exception as e:
                logger.warning(f"ketquadientoan sync failed, trying upstream mirror: {e}")
                return sync_from_upstream(product, config)
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
