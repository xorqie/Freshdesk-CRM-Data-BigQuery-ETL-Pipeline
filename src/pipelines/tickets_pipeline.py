"""
tickets_pipeline.py
--------------------
Extracts tickets (with stats) from Freshdesk, transforms them into an
analytics-friendly shape, and loads a full snapshot into BigQuery.

Why full refresh (WRITE_TRUNCATE) instead of incremental?
Tickets can change status, priority, or assignment at any point in their
lifecycle, and Freshdesk does not expose a reliable "changed since" filter
that covers every field we care about. Re-pulling the full ticket set on
each run is simple, correct, and - for a support desk of this size - cheap
enough that the added complexity of change-data-capture isn't justified.
"""

import pandas as pd

from config import FreshdeskConfig, BigQueryConfig, GROUP_ID_MAP, SOURCE_MAP, STATUS_MAP, PRIORITY_MAP
from src.freshdesk_client import FreshdeskClient
from src.bigquery_loader import BigQueryLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Columns that carry no analytical value or duplicate other fields
COLUMNS_TO_DROP = [
    "company_id", "association_type", "product_id", "associated_tickets_count", "nr_due_by",
    "cc_emails", "fwd_emails", "reply_cc_emails", "ticket_cc_emails", "ticket_bcc_emails",
]

REQUIRED_COLUMNS = [
    "fr_escalated", "spam", "group_id", "priority", "requester_id", "responder_id",
    "source", "status", "subject", "id", "due_by", "fr_due_by", "created_at", "updated_at",
    "cf_platform", "cf_game", "cf_issue_type", "type", "closed_at", "resolved_at", "first_responded_at",
    "tags", "to_emails", "is_new_customer", "first_response_hr", "resolution_time_hr", "closing_time_hr",
]

TIMESTAMP_COLUMNS = ["due_by", "fr_due_by", "created_at", "updated_at"]
ID_COLUMNS = ["group_id", "requester_id", "responder_id", "id"]


def _build_agent_mapping(agents: list) -> dict:
    """Map agent_id -> agent display name, tolerating missing/malformed records."""
    mapping = {}
    for agent in agents:
        contact = agent.get("contact") or {}
        if agent.get("id") and contact.get("name"):
            mapping[str(agent["id"])] = contact["name"]
    return mapping


def _hours_between(end_series: pd.Series, start_series: pd.Series) -> pd.Series:
    end = pd.to_datetime(end_series, errors="coerce")
    start = pd.to_datetime(start_series, errors="coerce")
    return (end - start).dt.total_seconds() / 3600


def transform(tickets: list, agents: list, freshdesk_cfg: FreshdeskConfig) -> pd.DataFrame:
    df = pd.DataFrame(tickets)
    if df.empty:
        return df

    df.drop(columns=[c for c in COLUMNS_TO_DROP if c in df.columns], inplace=True)

    # Custom fields are nested; flatten the ones we track
    df["cf_platform"] = df["custom_fields"].apply(lambda x: x.get("cf_platform") if isinstance(x, dict) else None)
    df["cf_game"] = df["custom_fields"].apply(lambda x: x.get("cf_game") if isinstance(x, dict) else None)
    df["cf_issue_type"] = df["custom_fields"].apply(lambda x: x.get("cf_issue_type") if isinstance(x, dict) else None)
    df.drop(columns=["custom_fields"], inplace=True)

    # SLA/stats are also nested (only present because we requested `include=stats`)
    df["closed_at"] = df["stats"].apply(lambda x: x.get("closed_at") if isinstance(x, dict) else None)
    df["resolved_at"] = df["stats"].apply(lambda x: x.get("resolved_at") if isinstance(x, dict) else None)
    df["first_responded_at"] = df["stats"].apply(lambda x: x.get("first_responded_at") if isinstance(x, dict) else None)
    df.drop(columns=["stats"], inplace=True)

    for col in TIMESTAMP_COLUMNS:
        df[col] = df[col].apply(lambda x: str(x) if pd.notnull(x) else None)

    # New-customer flag: ticket created within the last 30 days
    today = pd.to_datetime("today").tz_localize("UTC")
    df["is_new_customer"] = pd.to_datetime(df["created_at"], errors="coerce") >= today - pd.Timedelta(days=30)

    # SLA metrics, derived rather than pulled from the API directly
    df["first_response_hr"] = _hours_between(df["first_responded_at"], df["created_at"])
    df["resolution_time_hr"] = _hours_between(df["resolved_at"], df["created_at"])
    df["closing_time_hr"] = _hours_between(df["closed_at"], df["created_at"])

    for column in REQUIRED_COLUMNS:
        if column not in df.columns:
            df[column] = None

    # Normalize IDs to strings (BigQuery-safe, avoids float ".0" artifacts)
    for col in ID_COLUMNS:
        df[col] = df[col].astype("Int64").astype(str).where(df[col].notnull(), None)

    # Human-readable lookups
    df["group_id"] = df["group_id"].map(GROUP_ID_MAP).fillna(df["group_id"])
    agent_mapping = _build_agent_mapping(agents)
    df["responder_id"] = df["responder_id"].map(agent_mapping).fillna("Unknown")
    df["source"] = df["source"].map(SOURCE_MAP).fillna(df["source"])
    df["status"] = df["status"].map(STATUS_MAP).fillna(df["status"]).astype(str)
    df["priority"] = df["priority"].map(PRIORITY_MAP).fillna(df["priority"])

    # Tags arrive as a list; store as a comma-separated string, NULL if empty
    df["tags"] = df["tags"].apply(lambda x: ", ".join(x) if isinstance(x, list) and x else None)

    # Convenience deep-link back to the ticket in Freshdesk
    df["id"] = df["id"].apply(lambda x: freshdesk_cfg.ticket_url(x))

    return df


def run() -> None:
    freshdesk_cfg = FreshdeskConfig()
    bq_cfg = BigQueryConfig()

    client = FreshdeskClient(api_key=freshdesk_cfg.api_key)
    loader = BigQueryLoader(bq_cfg.credentials_path, bq_cfg.project_id, bq_cfg.dataset_id)

    logger.info("Fetching tickets from Freshdesk...")
    tickets = client.fetch_paginated(freshdesk_cfg.tickets_url)

    logger.info("Fetching agents from Freshdesk (for name lookups)...")
    agents = client.fetch_single(freshdesk_cfg.agents_url)

    if not tickets:
        logger.info("No ticket data returned from Freshdesk. Nothing to load.")
        return

    df = transform(tickets, agents, freshdesk_cfg)
    rows_loaded = loader.load_truncate(df, bq_cfg.tickets_table)
    logger.info(f"Tickets pipeline complete. {rows_loaded} rows loaded into {bq_cfg.tickets_table}.")


if __name__ == "__main__":
    run()
