"""
config.py
---------
Centralized, environment-driven configuration for the pipeline.

All secrets (API keys, project IDs, credential paths) are read from
environment variables so that no sensitive values ever live in source
control. Copy `.env.example` to `.env` and fill in your own values,
or export the variables directly in your shell / CI system.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load variables from a local .env file if present (no-op in production
# environments where variables are injected directly, e.g. Airflow, GitHub
# Actions, Cloud Run, etc.)
load_dotenv()


def _require_env(name: str) -> str:
    """Fetch a required environment variable or raise a clear error."""
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: '{name}'. "
            f"See .env.example for the full list of required variables."
        )
    return value


@dataclass(frozen=True)
class BigQueryConfig:
    project_id: str = field(default_factory=lambda: _require_env("BQ_PROJECT_ID"))
    dataset_id: str = field(default_factory=lambda: os.getenv("BQ_DATASET_ID", "freshdesk"))
    credentials_path: str = field(default_factory=lambda: _require_env("GOOGLE_APPLICATION_CREDENTIALS"))

    tickets_table: str = field(default_factory=lambda: os.getenv("BQ_TICKETS_TABLE", "tickets"))
    agents_table: str = field(default_factory=lambda: os.getenv("BQ_AGENTS_TABLE", "agents"))
    csat_table: str = field(default_factory=lambda: os.getenv("BQ_CSAT_TABLE", "csat"))


@dataclass(frozen=True)
class FreshdeskConfig:
    domain: str = field(default_factory=lambda: _require_env("FRESHDESK_DOMAIN"))
    api_key: str = field(default_factory=lambda: _require_env("FRESHDESK_API_KEY"))

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}.freshdesk.com/api/v2"

    @property
    def tickets_url(self) -> str:
        return f"{self.base_url}/tickets?include=stats"

    @property
    def agents_url(self) -> str:
        return f"{self.base_url}/agents"

    @property
    def satisfaction_ratings_url(self) -> str:
        return f"{self.base_url}/surveys/satisfaction_ratings"

    def ticket_url(self, ticket_id) -> str:
        """Public-facing URL for a single ticket (used for row enrichment)."""
        return f"https://{self.domain}.freshdesk.com/a/tickets/{ticket_id}"


# Freshdesk group_id -> human-readable product/team name.
# This mapping is specific to this Freshdesk account's group configuration
# and contains no sensitive information, so it is safe to keep in source
# control. Update it if groups are added/renamed in Freshdesk.
GROUP_ID_MAP = {
    "GROUP_ID_1": "Product Line 1",
    "GROUP_ID_2": "Product Line 2",
    "GROUP_ID_3": "Product Line 3",
    "GROUP_ID_4": "Product Code Claims",
    "GROUP_ID_5": "General",
    "GROUP_ID_6": "Product Line 4",
    "GROUP_ID_7": "Product Line 5",
    "GROUP_ID_8": "Live Support",
    "GROUP_ID_9": "Board Games",
    "GROUP_ID_10": "Product Line 6",
}

SOURCE_MAP = {1: "Email", 2: "Portal", 3: "Phone", 7: "Chat", 9: "Feedback Widget", 10: "Outbound Email"}
STATUS_MAP = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed", 8: "In Progress", 9: "Awaiting Response", 10: "On Hold"}
PRIORITY_MAP = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}

RATING_DESCRIPTIONS = {
    103: "Extremely Happy",
    102: "Very Happy",
    101: "Happy",
    100: "Neutral",
    -101: "Unhappy",
    -102: "Very Unhappy",
    -103: "Extremely Unhappy",
}

bigquery_config = BigQueryConfig
freshdesk_config = FreshdeskConfig
