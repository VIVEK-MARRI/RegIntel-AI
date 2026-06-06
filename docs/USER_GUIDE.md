# User Guide

> How to use RegIntel AI v1.0.0 as a researcher, analyst, or auditor.

## What is RegIntel AI?

RegIntel AI is a regulatory intelligence platform. You ask questions in
natural language, and the system answers with grounded citations to
the underlying regulatory documents.

## Quick start

1. **Open the app** — navigate to `https://<host>/` in your browser.
2. **Sign in** — use your organisation's identity provider (SSO), or
   enter your API key.
3. **Ask a question** — type into the chat box and press Enter.
4. **Read the answer** — every claim is paired with a citation. Click
   the citation to see the source document, page, and surrounding
   context.
5. **Verify** — open the "Evidence" panel to see the chunks the system
   used to answer.

## Roles

RegIntel AI ships with six roles. Your role determines what you can
do.

| Role | Can | Cannot |
|------|-----|--------|
| **Viewer** | Read public documents, ask questions | Change settings, ingest documents |
| **Analyst** | Viewer + create governance decisions | Approve decisions, manage users |
| **Operator** | Analyst + run workflows, ingest documents | Approve decisions, manage users |
| **Auditor** | Review governance decisions, export audit log | Ingest documents, manage users |
| **Admin** | Everything | — |
| **Service** | API-only, used by other systems | Read the web UI |

To change your role, ask your administrator.

## Common tasks

### Ask a question

1. Click **New conversation**.
2. Type your question, e.g. *"What does MiFID II say about best
   execution for retail clients?"*.
3. Press **Enter** (or click **Send**).
4. The system shows the answer with citations.

Tips:

* Be specific — names, dates, jurisdictions.
* Use follow-up questions to drill into a specific citation.
* Use the **Filter** menu to limit the search to a jurisdiction, a
  regulator, or a time window.

### Export a conversation

1. Open the conversation.
2. Click **⋯** → **Export**.
3. Choose **PDF** (with citations) or **Markdown**.

### Create a governance decision

1. Open **Governance** → **New decision**.
2. Fill in:
   * **Title** — short, descriptive.
   * **Body** — the decision text (markdown supported).
   * **Entities** — tags for the regulators / instruments / articles
     involved.
3. Click **Save as draft** (only you can see it) or **Submit for
   review** (an auditor will be notified).

### Review a decision (auditor)

1. Open **Governance** → **Review queue**.
2. Click a decision to read it.
3. Click **Approve** or **Reject**, add a note, and confirm.

### Ingest a document (operator / admin)

1. Open **Documents** → **Upload**.
2. Drag a PDF, DOCX, or HTML file.
3. Add metadata (source, published date, jurisdiction).
4. Click **Upload**.

The system parses, chunks, embeds, and extracts entities. The
document appears in the search results within seconds; the entity
extraction completes in the background.

### Search the knowledge graph

1. Open **Knowledge graph**.
2. Type an entity name (e.g. *"MiFID II"*) and press Enter.
3. The system shows the entity card and its 1-hop neighbourhood.
4. Click a relation to see the connected entity.

### View your usage

1. Open **Account** → **Usage**.
2. See your queries, tokens, and cost for the current month.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send a message |
| `Shift+Enter` | Newline in a message |
| `Ctrl+K` (or `Cmd+K`) | Quick search |
| `Ctrl+/` (or `Cmd+/`) | Show keyboard shortcuts |
| `Esc` | Close a panel |

## Tips and tricks

* **Cite the source** — when you quote the answer in an email or a
  document, click **Copy citation** to copy a formatted citation that
  links back to the evidence.
* **Drill down** — click any citation to see the full source
  document. The system highlights the cited chunk.
* **Refine** — the **Filter** menu on the chat lets you restrict the
  search by date, jurisdiction, and source. Use it to cut through
  noise.
* **Save** — click **⭐** on a message to save it to your bookmarks.
  Bookmarks are searchable from the sidebar.
* **Compare** — open two conversations side by side with
  **View** → **Split view** (paid plans only).

## Privacy

* Your conversations are not used to train the underlying LLM.
* Your conversations are visible to your organisation's auditors; the
  audit log records every query, answer, and citation.
* To delete a conversation, click **⋯** → **Delete**. To export all
  your data, open **Account** → **Privacy** → **Export**.

## Support

* In-app: click **?** in the top-right to open the help centre.
* Email: `support@regintel.ai`.
* Status: <https://status.regintel.ai>.

## Next steps

* Read the [Admin Guide](./ADMIN_GUIDE.md) to learn how to manage
  users, quotas, and integrations.
* Read the [Troubleshooting Guide](./TROUBLESHOOTING.md) for common
  issues.
* Read the [Operations Guide](./OPERATIONS.md) for the on-call
  runbooks (operators only).
