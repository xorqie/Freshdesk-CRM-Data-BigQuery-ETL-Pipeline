"""
csat_pipeline.py
--------------------
Extracts Customer Satisfaction (CSAT) survey ratings from Freshdesk and
incrementally upserts them into BigQuery.

Why incremental merge instead of full refresh?
CSAT ratings are immutable once submitted (a customer doesn't retroactively
change a survey response), so new rows only ever get appended. A MERGE on
`id` is a cheap way to make repeated runs idempotent without re-fetching or
re-writing the entire ratings history each time.
"""

import json

import pandas as pd

from config import FreshdeskConfig, BigQueryConfig, RATING_DESCRIPTIONS
from src.freshdesk_client import FreshdeskClient
from src.bigquery_loader import BigQueryLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)

ID_COLUMNS = ["id", "survey_id", "user_id", "agent_id", "ticket_id", "group_id"]
TIMESTAMP_COLUMNS = ["created_at", "updated_at"]


def _rating_description(rating_json) -> str:
    """Translate Freshdesk's numeric CSAT score into a human-readable label."""
    if not isinstance(rating_json, str):
        return "Not JSON"
    try:
        rating_dict = json.loads(rating_json)
    except json.JSONDecodeError:
        return "Invalid JSON"

    default_score = rating_dict.get("default_question")
    return RATING_DESCRIPTIONS.get(default_score, "Unknown")


def transform(ratings: list, freshdesk_cfg: FreshdeskConfig) -> pd.DataFrame:
    if not ratings:
        return pd.DataFrame()

    df = pd.DataFrame(ratings)

    # Freshdesk sometimes includes a denormalized agent_name; we derive
    # agent identity from `agent_id` (joined against the agents table)
    # instead, to keep a single source of truth.
    df.drop(columns=["agent_name"], errors="ignore", inplace=True)

    for col in ID_COLUMNS:
        df[col] = df[col].astype(str)

    df["ticket_id"] = df["ticket_id"].apply(freshdesk_cfg.ticket_url)

    for col in TIMESTAMP_COLUMNS:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    df["ratings"] = df["ratings"].apply(lambda x: json.dumps(x) if isinstance(x, dict) else x)
    df["default_rating_description"] = df["ratings"].apply(_rating_description)

    return df


def run() -> None:
    freshdesk_cfg = FreshdeskConfig()
    bq_cfg = BigQueryConfig()

    client = FreshdeskClient(api_key=freshdesk_cfg.api_key)
    loader = BigQueryLoader(bq_cfg.credentials_path, bq_cfg.project_id, bq_cfg.dataset_id)

    logger.info("Fetching CSAT ratings from Freshdesk...")
    ratings = client.fetch_paginated(freshdesk_cfg.satisfaction_ratings_url)

    if not ratings:
        logger.info("No CSAT data returned from Freshdesk. Nothing to load.")
        return

    df = transform(ratings, freshdesk_cfg)
    rows_loaded = loader.load_merge(df, bq_cfg.csat_table, merge_key="id")
    logger.info(f"CSAT pipeline complete. {rows_loaded} rows merged into {bq_cfg.csat_table}.")


if __name__ == "__main__":
    run()
