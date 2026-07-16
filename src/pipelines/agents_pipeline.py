"""
agents_pipeline.py
--------------------
Extracts agent (support staff) records from Freshdesk and incrementally
upserts them into BigQuery.

Why incremental merge instead of full refresh?
The agent roster is small and changes rarely (a handful of adds/removals
per month), so a MERGE keeps history-friendly semantics (stable row
identity) and avoids unnecessary full-table rewrites.
"""

import pandas as pd

from config import FreshdeskConfig, BigQueryConfig
from src.freshdesk_client import FreshdeskClient
from src.bigquery_loader import BigQueryLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)

REQUIRED_COLUMNS = [
    "available", "occasional", "id", "ticket_scope", "created_at", "updated_at",
    "last_active_at", "available_since", "type", "active", "email", "job_title",
    "language", "last_login_at", "mobile", "name", "phone", "time_zone", "deactivated",
    "signature", "focus_mode",
]

TIMESTAMP_COLUMNS = ["created_at", "updated_at", "last_active_at", "available_since", "last_login_at"]


def transform(agents: list) -> pd.DataFrame:
    if not agents:
        return pd.DataFrame()

    # The agent's profile fields live under a nested "contact" object; flatten it
    flattened = []
    for agent in agents:
        flat = dict(agent)
        flat.update(flat.pop("contact", {}) or {})
        flattened.append(flat)

    df = pd.DataFrame(flattened)

    for col in ["id", "ticket_scope"]:
        if col in df.columns:
            df[col] = df[col].astype(str)

    for col in TIMESTAMP_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    return df[REQUIRED_COLUMNS]


def run() -> None:
    freshdesk_cfg = FreshdeskConfig()
    bq_cfg = BigQueryConfig()

    client = FreshdeskClient(api_key=freshdesk_cfg.api_key)
    loader = BigQueryLoader(bq_cfg.credentials_path, bq_cfg.project_id, bq_cfg.dataset_id)

    logger.info("Fetching agents from Freshdesk...")
    agents = client.fetch_single(freshdesk_cfg.agents_url)

    if not agents:
        logger.info("No agent data returned from Freshdesk. Nothing to load.")
        return

    df = transform(agents)
    rows_loaded = loader.load_merge(df, bq_cfg.agents_table, merge_key="id")
    logger.info(f"Agents pipeline complete. {rows_loaded} rows merged into {bq_cfg.agents_table}.")


if __name__ == "__main__":
    run()
