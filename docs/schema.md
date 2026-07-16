# BigQuery Schema

All tables live in a single dataset (default name: `freshdesk`). Column
names mirror the Freshdesk API field names where possible, so the mapping
between source and warehouse stays easy to reason about.

## `tickets`

Full snapshot, refreshed on every run (`WRITE_TRUNCATE`).

| Column | Type | Description |
|---|---|---|
| `id` | STRING | Deep link to the ticket in Freshdesk (`.../a/tickets/{id}`) |
| `subject` | STRING | Ticket subject line |
| `status` | STRING | Decoded status (`Open`, `Pending`, `Resolved`, `Closed`, ...) |
| `priority` | STRING | Decoded priority (`Low`, `Medium`, `High`, `Urgent`) |
| `source` | STRING | Decoded channel the ticket came in on (`Email`, `Portal`, `Chat`, ...) |
| `group_id` | STRING | Decoded team/product group the ticket is routed to |
| `requester_id` | STRING | Freshdesk contact ID of the requester |
| `responder_id` | STRING | Resolved agent name (joined from the agents endpoint) |
| `type` | STRING | Freshdesk ticket type field |
| `tags` | STRING | Comma-separated tag list |
| `cf_platform` / `cf_game` / `cf_issue_type` | STRING | Custom fields specific to this Freshdesk account |
| `created_at` / `updated_at` / `due_by` / `fr_due_by` | STRING (ISO timestamp) | Lifecycle timestamps |
| `first_responded_at` / `resolved_at` / `closed_at` | STRING (ISO timestamp) | SLA milestone timestamps |
| `is_new_customer` | BOOLEAN | `True` if the ticket was created in the last 30 days |
| `first_response_hr` | FLOAT | Hours between creation and first response |
| `resolution_time_hr` | FLOAT | Hours between creation and resolution |
| `closing_time_hr` | FLOAT | Hours between creation and closing |

## `agents`

Incrementally upserted (`MERGE` on `id`).

| Column | Type | Description |
|---|---|---|
| `id` | STRING | Freshdesk agent ID (merge key) |
| `name` | STRING | Agent display name |
| `email` | STRING | Agent email |
| `job_title` | STRING | Agent job title |
| `active` / `deactivated` | BOOLEAN | Account status flags |
| `available` / `occasional` | BOOLEAN | Availability flags |
| `ticket_scope` | STRING | Freshdesk ticket visibility scope |
| `time_zone` | STRING | Agent's configured time zone |
| `created_at` / `updated_at` / `last_login_at` / `last_active_at` / `available_since` | TIMESTAMP | Account lifecycle timestamps |

## `csat`

Incrementally upserted (`MERGE` on `id`).

| Column | Type | Description |
|---|---|---|
| `id` | STRING | CSAT rating ID (merge key) |
| `survey_id` | STRING | Freshdesk survey ID |
| `ticket_id` | STRING | Deep link to the related ticket |
| `agent_id` | STRING | Agent the rating was left for (joins to `agents.id`) |
| `user_id` | STRING | Customer who submitted the rating |
| `group_id` | STRING | Group the related ticket belonged to |
| `ratings` | STRING (JSON) | Raw Freshdesk ratings payload |
| `default_rating_description` | STRING | Human-readable label for the default CSAT question (e.g. "Very Happy") |
| `created_at` / `updated_at` | TIMESTAMP | Survey response timestamps |

## Entity relationships

```
tickets.responder_id  --> agents.name   (resolved during transform, not a live FK)
csat.agent_id          --> agents.id
csat.ticket_id          --> tickets.id  (via embedded ticket URL)
```

> Note: `tickets.responder_id` is resolved to an agent **name** at
> transform time for readability in BI tools. If you need a strict foreign
> key relationship, join `csat.agent_id` to `agents.id` instead, or extend
> the ticket transform to keep the raw `responder_id` alongside the
> resolved name.
