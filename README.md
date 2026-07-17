# Freshdesk → BigQuery ETL Pipeline

A production-style data pipeline that extracts customer support data
(tickets, agents, and CSAT survey results) from the **Freshdesk REST API**
and loads it into **Google BigQuery**, ready for analytics and BI
dashboards.

This project was built to solve a real operational problem: support data
lived only inside Freshdesk's UI, which made trend analysis, SLA
reporting, and cross-team dashboards (e.g. Looker Studio, Tableau) slow
and manual. This pipeline turns that raw ticketing data into clean,
query-ready tables in a cloud data warehouse.

---

## Engineering approach

Support teams generate constant operational data — ticket volume, SLA
performance, customer sentiment — but that data is only useful if it's
reliable, current, and easy to build reporting on top of. The design
choices in this pipeline are built around that:

- **Correctness over speed** — full-refresh vs. incremental loading is
  chosen deliberately per table based on how the underlying data actually
  changes, not applied uniformly.
- **No hardcoded secrets** — every credential is environment-driven,
  which is table stakes for anything meant to run outside a personal
  laptop.
- **Resilience by default** — API pagination, rate limits, and retries
  are handled once, correctly, at the client level rather than per script.
- **Documentation as a deliverable** — schema references and architecture
  diagrams exist so another engineer, or a non-technical stakeholder
  building a dashboard, can pick this up without asking questions.

---

## Features

- **Three independent pipelines** — tickets, agents, and CSAT ratings —
  each runnable on its own or together.
- **Resilient API client** — cursor-based pagination, automatic retry
  with exponential backoff, and rate-limit handling that respects
  Freshdesk's `Retry-After` header.
- **Two loading strategies, chosen deliberately per dataset:**
  - `WRITE_TRUNCATE` (full refresh) for tickets, since ticket state can
    change at any time.
  - Staging table + `MERGE` (incremental upsert) for agents and CSAT
    data, which are append-mostly.
- **Derived analytics fields** computed at transform time: first-response
  time, resolution time, closing time (all in hours), and a rolling
  "new customer" flag.
- **Environment-based configuration** — zero secrets in source code.
- **Structured logging** instead of scattered `print()` statements.
- **Modular, testable code** — shared HTTP and BigQuery logic lives in
  `src/`, so each pipeline file only contains its own transform logic.

---

## Architecture

```
                ┌───────────────────┐
                │   Freshdesk API    │
                │  (tickets, agents, │
                │   CSAT surveys)    │
                └─────────┬──────────┘
                          │  REST (paginated, rate-limited)
                          ▼
                ┌───────────────────┐
                │  FreshdeskClient   │  src/freshdesk_client.py
                │  (extract layer)   │
                └─────────┬──────────┘
                          │  raw JSON
                          ▼
                ┌───────────────────┐
                │  Pipeline modules  │  src/pipelines/*.py
                │ (transform layer): │
                │  clean, flatten,   │
                │  decode, derive    │
                └─────────┬──────────┘
                          │  pandas DataFrame
                          ▼
                ┌───────────────────┐
                │   BigQueryLoader   │  src/bigquery_loader.py
                │   (load layer):    │
                │  truncate or merge │
                └─────────┬──────────┘
                          │
                          ▼
                ┌───────────────────┐
                │  Google BigQuery   │
                │  freshdesk dataset │
                └────────────────────┘
```

This is a classic **ELT-leaning ETL** pattern: lightweight transformation
happens in Python (cleaning, decoding, deriving metrics) before load,
while heavier aggregation is left to BigQuery SQL / the BI layer, which is
where it belongs at scale.

---

## Technologies Used

| Layer | Tool |
|---|---|
| Language | Python 3.10+ |
| Data manipulation | pandas |
| Data warehouse | Google BigQuery |
| Source API | Freshdesk REST API v2 |
| HTTP client | requests (with custom retry/backoff logic) |
| Configuration | python-dotenv + environment variables |
| Auth | GCP Service Account (BigQuery), Freshdesk API key |

---

## Data Pipeline

| Pipeline | Source Endpoint | Load Strategy | Frequency Suggestion |
|---|---|---|---|
| `tickets` | `GET /tickets?include=stats` | Full refresh | Every few hours |
| `agents` | `GET /agents` | Incremental merge | Daily |
| `csat` | `GET /surveys/satisfaction_ratings` | Incremental merge | Daily |

See [`docs/schema.md`](docs/schema.md) for the full column-level schema of
each BigQuery table.

### Why BigQuery?

BigQuery was chosen as the warehouse because it's:
- **Serverless** — no infrastructure to manage, which matters for a
  small support-data pipeline like this one.
- **Cheap at this scale** — pay-per-query pricing with a generous free
  tier fits a project of this size.
- **BI-tool friendly** — connects natively to Looker Studio, Tableau, and
  most other dashboarding tools support desk teams already use.

### How the Freshdesk API works in this project

Freshdesk paginates list endpoints (tickets, agents, CSAT ratings) using
the standard `Link` HTTP header (`rel="next"`) rather than an offset or
page-number parameter. `FreshdeskClient.fetch_paginated()` follows that
header until it's no longer present, which is the pattern Freshdesk's own
docs recommend. Authentication uses HTTP Basic Auth with the API key as
the username and the literal string `"X"` as the password, per
[Freshdesk's authentication docs](https://developers.freshdesk.com/api/#authentication).

---

## Installation

```bash
git clone https://github.com/<your-username>/freshdesk-bigquery-pipeline.git
cd freshdesk-bigquery-pipeline

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

## Configuration

1. Copy the example environment file and fill in your own values:

   ```bash
   cp .env.example .env
   ```

2. Populate `.env`:

   | Variable | Description |
   |---|---|
   | `FRESHDESK_DOMAIN` | Your Freshdesk subdomain (e.g. `acme` for `acme.freshdesk.com`) |
   | `FRESHDESK_API_KEY` | Freshdesk API key (Profile Settings → API Key) |
   | `BQ_PROJECT_ID` | Your GCP project ID |
   | `BQ_DATASET_ID` | BigQuery dataset name (defaults to `freshdesk`) |
   | `BQ_TICKETS_TABLE` / `BQ_AGENTS_TABLE` / `BQ_CSAT_TABLE` | Table name overrides (optional) |
   | `GOOGLE_APPLICATION_CREDENTIALS` | Path to a GCP service account JSON key with BigQuery Data Editor + Job User roles |

3. Create the target BigQuery dataset if it doesn't exist yet:

   ```bash
   bq mk --dataset "$BQ_PROJECT_ID:$BQ_DATASET_ID"
   ```

   The pipeline creates tables automatically on first load, since
   `load_table_from_dataframe` infers a schema from the DataFrame.

## Running the Project

```bash
# Run every pipeline
python main.py

# Run a single pipeline
python main.py tickets
python main.py agents
python main.py csat

# Run a subset
python main.py agents csat
```

### Example workflow

A typical production setup schedules this with cron, Cloud Scheduler, or
GitHub Actions:

```bash
# crontab: refresh tickets every 4 hours, agents/CSAT once a day
0 */4 * * * cd /path/to/project && venv/bin/python main.py tickets   >> logs/tickets.log 2>&1
0 3   * * * cd /path/to/project && venv/bin/python main.py agents csat >> logs/daily.log 2>&1
```

---

## Project Structure

```
.
├── main.py                     # CLI entrypoint - run all or specific pipelines
├── config.py                   # Environment-driven configuration & static lookup maps
├── requirements.txt
├── .env.example
├── src/
│   ├── freshdesk_client.py     # Extract layer: pagination, retries, rate limiting
│   ├── bigquery_loader.py      # Load layer: truncate & merge strategies
│   ├── pipelines/
│   │   ├── tickets_pipeline.py
│   │   ├── agents_pipeline.py
│   │   └── csat_pipeline.py
│   └── utils/
│       └── logger.py
└── docs/
    └── schema.md                # Column-level BigQuery schema reference
```

---

## Future Improvements

- **Data validation layer** (e.g. [`pandera`](https://pandera.readthedocs.io/) or
  [Great Expectations](https://greatexpectations.io/)) to catch schema
  drift or malformed API responses before they hit BigQuery.
- **Orchestration** with Airflow or Dagster for dependency-aware
  scheduling, retries, and alerting across the three pipelines.
- **dbt models** on top of the raw tables for SLA and CSAT trend
  reporting, separating transformation logic from extraction.
- **Unit tests** around the transform functions (`transform()` in each
  pipeline is already isolated from I/O specifically to make this easy).
- **True incremental extraction** for tickets using Freshdesk's
  `updated_since` filter, once ticket volume grows large enough that a
  full refresh becomes costly.
- **Containerization** (Dockerfile + Cloud Run job) for portable,
  infrastructure-agnostic scheduling.

---

## License

Released under the [MIT License](LICENSE).
