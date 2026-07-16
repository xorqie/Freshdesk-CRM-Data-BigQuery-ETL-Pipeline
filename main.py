"""
main.py
--------
Single entrypoint for running the Freshdesk -> BigQuery pipelines.

Usage:
    python main.py                # run all pipelines
    python main.py tickets        # run only the tickets pipeline
    python main.py agents csat    # run a specific subset

Designed to be triggered by a scheduler (cron, Airflow, Cloud Scheduler +
Cloud Run, GitHub Actions, etc.) rather than run manually in production.
"""

import sys

from src.pipelines import tickets_pipeline, agents_pipeline, csat_pipeline
from src.utils.logger import get_logger

logger = get_logger(__name__)

PIPELINES = {
    "tickets": tickets_pipeline.run,
    "agents": agents_pipeline.run,
    "csat": csat_pipeline.run,
}


def main() -> None:
    requested = sys.argv[1:] or list(PIPELINES.keys())

    unknown = [name for name in requested if name not in PIPELINES]
    if unknown:
        logger.error(f"Unknown pipeline(s): {unknown}. Available: {list(PIPELINES.keys())}")
        sys.exit(1)

    for name in requested:
        logger.info(f"--- Starting '{name}' pipeline ---")
        try:
            PIPELINES[name]()
        except Exception:
            logger.exception(f"Pipeline '{name}' failed.")
            raise
        logger.info(f"--- Finished '{name}' pipeline ---")


if __name__ == "__main__":
    main()
