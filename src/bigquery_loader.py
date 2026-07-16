"""
bigquery_loader.py
--------------------
Reusable BigQuery load helpers shared by every pipeline.

Two loading strategies are supported, matching how each Freshdesk resource
naturally behaves:

1. `load_truncate` — full refresh (WRITE_TRUNCATE). Used for the tickets
   table, where tickets can change state at any time (reopened, re-priced,
   re-assigned), so a full snapshot on every run is the simplest way to
   guarantee correctness.

2. `load_merge` — incremental upsert via a staging table + a `MERGE`
   statement. Used for agents and CSAT data, where existing rows are
   updated in place and new rows are appended, avoiding a full-table
   rewrite on every run.
"""

from typing import List

import pandas as pd
from google.cloud import bigquery

from src.utils.logger import get_logger

logger = get_logger(__name__)


class BigQueryLoader:
    def __init__(self, credentials_path: str, project_id: str, dataset_id: str):
        self.client = bigquery.Client.from_service_account_json(credentials_path)
        self.project_id = project_id
        self.dataset_id = dataset_id

    def _table_ref(self, table_id: str) -> str:
        return f"{self.project_id}.{self.dataset_id}.{table_id}"

    def load_truncate(self, df: pd.DataFrame, table_id: str) -> int:
        """Full-refresh load: replaces all existing rows in the table."""
        if df.empty:
            logger.info("No data to upload; skipping load.")
            return 0

        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        job = self.client.load_table_from_dataframe(df, self._table_ref(table_id), job_config=job_config)
        job.result()
        logger.info(f"Loaded {len(df)} rows into {self._table_ref(table_id)} (full refresh).")
        return len(df)

    def load_merge(self, df: pd.DataFrame, table_id: str, merge_key: str = "id") -> int:
        """
        Incremental upsert: loads `df` into a temporary staging table, then
        MERGEs it into the target table on `merge_key`, updating existing
        rows and inserting new ones.
        """
        if df.empty:
            logger.info("No data to upload; skipping load.")
            return 0

        staging_table_id = f"staging_{table_id}"
        staging_ref = self._table_ref(staging_table_id)
        target_ref = self._table_ref(table_id)

        try:
            # Stage the new data
            job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
            job = self.client.load_table_from_dataframe(df, staging_ref, job_config=job_config)
            job.result()
            logger.info(f"Staged {len(df)} rows into {staging_ref}.")

            columns: List[str] = list(df.columns)
            update_clause = ", ".join(f"target.{c} = source.{c}" for c in columns if c != merge_key)
            insert_columns = ", ".join(columns)
            insert_values = ", ".join(f"source.{c}" for c in columns)

            merge_query = f"""
                MERGE `{target_ref}` AS target
                USING `{staging_ref}` AS source
                ON target.{merge_key} = source.{merge_key}
                WHEN MATCHED THEN
                    UPDATE SET {update_clause}
                WHEN NOT MATCHED THEN
                    INSERT ({insert_columns})
                    VALUES ({insert_values})
            """
            self.client.query(merge_query).result()
            logger.info(f"Merged {len(df)} rows into {target_ref}.")

            return len(df)
        finally:
            # Staging table is transient - always clean it up, even on failure
            self.client.delete_table(staging_ref, not_found_ok=True)
            logger.info(f"Cleaned up staging table {staging_ref}.")

    def get_row_count(self, table_id: str) -> int:
        table = self.client.get_table(self._table_ref(table_id))
        return table.num_rows
