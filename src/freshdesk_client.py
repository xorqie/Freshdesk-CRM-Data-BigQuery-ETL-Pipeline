"""
freshdesk_client.py
--------------------
A thin, reusable client around the Freshdesk REST API (v2).

Responsibilities:
- Handle HTTP basic auth (Freshdesk uses the API key as the username).
- Follow cursor-based pagination via the RFC 5988 `Link` header, which is
  how Freshdesk exposes the "next page" URL.
- Respect Freshdesk's rate limits: on a 429 response, back off using the
  `Retry-After` header instead of guessing a sleep time.
- Retry transient network/server errors with exponential backoff.

Freshdesk API docs: https://developers.freshdesk.com/api/
"""

import time
from typing import Any, Dict, List, Optional

import requests

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2


class FreshdeskClient:
    def __init__(self, api_key: str, request_delay: float = 0.5):
        self.auth = (api_key, "X")  # Freshdesk convention: API key as username, 'X' as password
        self.headers = {"Content-Type": "application/json"}
        self.request_delay = request_delay  # gentle pacing between paginated requests

    def _get(self, url: str) -> requests.Response:
        """GET with retry/backoff for transient errors and rate limiting."""
        for attempt in range(1, MAX_RETRIES + 1):
            response = requests.get(url, auth=self.auth, headers=self.headers, timeout=DEFAULT_TIMEOUT)

            if response.status_code == 200:
                return response

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", BACKOFF_BASE_SECONDS * attempt))
                logger.warning(f"Rate limited by Freshdesk. Sleeping {retry_after}s before retrying...")
                time.sleep(retry_after)
                continue

            if response.status_code >= 500 and attempt < MAX_RETRIES:
                sleep_time = BACKOFF_BASE_SECONDS ** attempt
                logger.warning(
                    f"Freshdesk returned {response.status_code}. "
                    f"Retrying in {sleep_time}s (attempt {attempt}/{MAX_RETRIES})..."
                )
                time.sleep(sleep_time)
                continue

            # Non-retryable error (4xx other than 429), or retries exhausted
            logger.error(f"Freshdesk request failed [{response.status_code}]: {url}")
            response.raise_for_status()

        raise RuntimeError(f"Exceeded max retries fetching {url}")

    def fetch_paginated(self, url: str) -> List[Dict[str, Any]]:
        """Fetch all pages of a paginated Freshdesk endpoint."""
        results: List[Dict[str, Any]] = []
        next_url: Optional[str] = url

        while next_url:
            response = self._get(next_url)
            page_data = response.json()
            results.extend(page_data)
            logger.info(f"Fetched {len(page_data)} records ({len(results)} total so far)")

            next_url = response.links.get("next", {}).get("url")
            if next_url:
                time.sleep(self.request_delay)  # be a polite API citizen

        return results

    def fetch_single(self, url: str) -> Any:
        """Fetch a single (non-paginated) endpoint response."""
        return self._get(url).json()
