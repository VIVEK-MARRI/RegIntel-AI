# Admin Guide

> How to manage a RegIntel AI v1.0.0 deployment. Assumes the **Admin**
> role.

## Users and roles

### Add a user

1. Open **Admin** → **Users** → **Add user**.
2. Enter:
   * **Email** — used for SSO and notifications.
   * **Display name** — shown in the UI.
   * **Role** — one of `Viewer`, `Analyst`, `Operator`, `Auditor`,
     `Admin`. See `docs/USER_GUIDE.md#roles` for the permission matrix.
   * **API key** (optional) — for service-to-service access.
3. Click **Create**. The user receives an invitation email.

### Change a role

1. Open **Admin** → **Users**.
2. Click the user.
3. Change **Role** and click **Save**.

The change takes effect on the user's next request; active JWTs are
not revoked (use **Force re-auth** to invalidate them).

### Disable a user

1. Open **Admin** → **Users**.
2. Click the user.
3. Click **Disable**.

Disabled users cannot sign in; existing JWTs are revoked at the next
refresh.

### Delete a user

> Destructive. Cannot be undone.

1. Open **Admin** → **Users**.
2. Click the user.
3. Click **Delete**.
4. Type the user's email to confirm.

The user, their conversations, and their API keys are permanently
removed. Their audit log entries are anonymised but retained for
compliance.

## API keys

### Issue an API key

1. Open **Admin** → **API keys** → **New key**.
2. Enter:
   * **Label** — a human-readable name.
   * **Owner** — the user or service that will use the key.
   * **Allowed paths** (optional) — restrict the key to specific
     paths.
   * **Quota per minute** (optional) — default 60.
3. Click **Create**. The key is shown **once** — copy it now.

### Rotate an API key

1. Open **Admin** → **API keys**.
2. Click the key.
3. Click **Rotate**. A new key is generated; the old key is
   deactivated after a 24-hour grace period.

### Revoke an API key

1. Open **Admin** → **API keys**.
2. Click the key.
3. Click **Revoke**. The key is immediately disabled.

## Quotas

### Set a per-user quota

1. Open **Admin** → **Users** → click a user → **Quota**.
2. Set **Tokens per day** and **Queries per hour**.
3. Click **Save**.

### Set a global budget

Set `REGINTEL_LLM_DAILY_BUDGET_USD` in `.env.production` and restart
the backend. When the daily budget is exhausted, the agent falls back
to a cached response and logs a warning.

## Knowledge graph

### Trigger a re-extraction

1. Open **Admin** → **Knowledge graph** → **Re-extract**.
2. Select the documents (or **All**).
3. Click **Start**.

The re-extraction runs in the background. Progress is shown in the
**Jobs** panel.

### Roll back to a previous version

1. Open **Admin** → **Knowledge graph** → **Versions**.
2. Click the version to roll back to.
3. Click **Set as default**. The new default applies to all queries
   within 60 seconds.

## Governance

### Review queue

The **Governance** → **Review queue** shows pending decisions. Click
a decision to see the body, the entities, and the audit trail.
Approve or reject with a note.

### Workflow settings

1. Open **Admin** → **Governance** → **Workflow**.
2. Configure:
   * **Required reviewers** (number).
   * **Auto-approve after** (hours).
   * **Notify on** (`created`, `reviewed`, `rejected`).

## Documents

### Bulk ingest

1. Open **Admin** → **Documents** → **Bulk upload**.
2. Drop a folder of files.
3. Click **Upload**.

The system ingests in parallel, capped at 4 concurrent jobs per node.

### Purge a document

> Destructive. Cannot be undone (the document is removed from the
> vector store and the knowledge graph).

1. Open **Admin** → **Documents** → click the document.
2. Click **Delete**.
3. Type the document ID to confirm.

## Security

### View threats

Open **Admin** → **Security** → **Threats**. The dashboard shows
threat events grouped by type and level. Click an event to see the
source IP, the request, and the audit-log correlation.

### Block an IP

1. Open **Admin** → **Security** → **IP allow list**.
2. Add the IP or CIDR to the **Denied** list.
3. Click **Save**. The change is pushed to the edge within 60 seconds.

### Rotate the JWT secret

> Affects every user. Plan a maintenance window.

1. Generate a new secret: `openssl rand -base64 48`.
2. Update the secret in your secret manager.
3. Restart the backend.
4. All existing JWTs are invalidated; users must re-authenticate.

### Review the audit log

1. Open **Admin** → **Security** → **Audit log**.
2. Filter by date, path, status, identity, or review status.
3. Click **Export** → **JSONL** to download.

## Observability

### Metrics

* The Prometheus endpoint is at `/metrics`.
* See `docs/OPERATIONS.md#monitoring-stack` for the recommended
  dashboard and alert configuration.

### Logs

* Logs are structured JSON to stdout.
* Recommended log retention: 30 days hot, 1 year cold.

### Traces

* Set `REGINTEL_OTEL_EXPORTER_OTLP_ENDPOINT` to enable OTLP export.
* Set `REGINTEL_OTEL_SAMPLING_RATIO` (default 0.1) to control
  sampling.

## Maintenance

### Apply a migration

```bash
docker compose -f docker-compose.production.yml run --rm backend \
  alembic upgrade head
```

### Back up the database

```bash
docker compose -f docker-compose.production.yml exec postgres \
  pg_dump -U regintel regintel | gzip > backup-$(date -I).sql.gz
```

### Restore the database

```bash
gunzip -c backup-2026-06-06.sql.gz | \
  docker compose -f docker-compose.production.yml exec -T postgres \
  psql -U regintel regintel
```

## Compliance

### GDPR data export

For a user's data export:

```bash
curl -H "Authorization: Bearer $ADMIN_JWT" \
  https://<host>/api/v1/admin/users/<user_id>/export
```

The response is a JSON archive with the user's conversations,
bookmarks, and feedback.

### GDPR data deletion

```bash
curl -X DELETE -H "Authorization: Bearer $ADMIN_JWT" \
  https://<host>/api/v1/admin/users/<user_id>
```

The user and their content are removed; audit entries are
anonymised.

## Support escalation

* In-app: **?** → **Contact support**.
* Email: `support@regintel.ai`.
* Phone (paid plans only): see your account manager.

## See also

* `docs/USER_GUIDE.md` — for end users.
* `docs/OPERATIONS.md` — for operators.
* `docs/TROUBLESHOOTING.md` — for common issues.
* `docs/architecture/09-operations-guide.md` — for runbooks.
