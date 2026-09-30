# Warden API

Permission-aware knowledge retrieval for a fictional B2B support team.

## Architecture

- **data/ground/ingestion.py** (Rishi's own script) owns bulk ingestion:
  chunks the fake seed documents, embeds them with OpenAI
  `text-embedding-3-small`, and stores them into three Chroma collections
  (`policy_docs`, `slack_messages`, `support_tickets`) under
  `data/chroma_store`, each chunk tagged with `access_level` metadata
  ("public" or "manager"). Access level is detected from a marker already
  written into each document's own text ("(Confidential...)",
  "(Restricted...)", "Manager Access"), not a hand-maintained filename
  list - see "Known gap" history below.
- **python-retrieval/retrieval_service.py** (Flask) queries those same
  collections - same embedding model, same persist directory, same
  chunking - and exposes two endpoints:
  - `/search` applies the access-level filter as a Chroma metadata
    `where` clause before returning anything.
  - `/ingest` adds a single document straight into the `policy_docs`
    collection, additively (`add_texts`, never a delete+rebuild), tagged
    with whatever `accessLevel` the caller passed in. This is what
    powers document upload from the UI.
- **warden-api** (Spring Boot) is the REST API: checks the caller's
  access level, calls the Python service for authorized chunks only, then
  calls Ollama chat to generate a cited answer. It also fronts `/ingest`
  as `POST /api/documents`, so the UI only ever talks to one backend.
  Every request gets a short `traceId` (see `TraceIdFilter`), logged with
  timing/retrieval/model details and echoed back as an `X-Trace-Id`
  response header.
- **warden-ui** (React + Vite) is the browser UI: a document upload panel
  (pick a file, pick public/manager, upload) and a chat window (pick a
  user, ask a question, see the cited answer). See `warden-ui/README.md`.

Restricted chunks are excluded inside the Chroma query itself, before any
chunk is returned - not after, and never by asking the model to keep a
secret. Java's `OllamaChatService` only ever receives what the Python
service already filtered. The same rule applies on the write side: the
access level chosen at upload time is the access level stored on the
chunk, permanently - there's no "upload now, classify later" step for an
attacker (or a mistake) to slip through.

## Run it

1. Run ingestion (only needed once, or again after adding/changing the
   seed docs on disk - uploads through the UI don't need this):
   ```
   cd data/ground
   python ingestion.py
   ```

2. Start the retrieval service:
   ```
   cd warden-api/python-retrieval
   pip install -r requirements.txt
   python retrieval_service.py
   ```
   Runs on port 8011. Reads `OPENAI_API_KEY` from `data/ground/.env` -
   same key ingestion.py uses, so nothing to configure separately.

3. Make sure Ollama is running locally with the chat model pulled:
   ```
   ollama pull llama3.2
   ```

4. Start the Java app:
   ```
   mvn spring-boot:run
   ```
   Runs on port 8082.

5. Start the UI:
   ```
   cd warden-ui
   npm install
   npm run dev
   ```
   Runs on port 5173 (`http://localhost:5173`) and talks to warden-api on
   port 8082 - CORS for that origin is already open in `CorsConfig.java`.

6. Or skip the UI and import `Warden.postman_collection.json` - try
   requests 1-4 (list users, User A vs User B on the same churn/discount
   question, then a public FAQ question both should be able to answer),
   plus request 7 to upload a document directly.

## Known gap (fixed 2026-09-25)

`ingestion.py` originally tagged access level from a hand-maintained
`access_map` dict that only listed 4 policy-doc filenames; every support
ticket and every Slack message silently defaulted to `"public"`,
including ones explicitly marked manager-only in their own text
(`manager-churn-risk-thread.md`, `manager-comp-decision-thread.md`,
`eng-oncall-incident-thread.md`, `TCK-105-enterprise-churn-escalation.md`).
Fixed by switching to content-marker detection (`detect_access_level()`
in `ingestion.py`) plus making the script idempotent
(`delete_collection()` before repopulating), so re-running it never
leaves stale, incorrectly-tagged chunks behind. Left here as a record of
the bug, not a live warning - the current script and the `/ingest`
endpoint both go through the same content-marker-driven correctness.

## Known MVP simplifications

- Two-tier access level (public / manager), not the fuller role+ACL
  layering discussed for later.
- No real auth - `userId` in the request body (or the dropdown in the UI)
  stands in for login, and the access level on an upload is
  self-declared, not verified against who's actually uploading.
- Document upload accepts `.txt` / `.md` only, up to 2 MB - no PDF/DOCX
  extraction yet.
- Errors (Ollama down, retrieval service down, bad userId aside) surface
  as plain 500s.

## Cleanup

`_to_delete/` holds the earlier Postgres/pgvector version of this project,
superseded twice now (first by Chroma+Ollama-embeddings, now by
Chroma+OpenAI-embeddings to match ingestion.py). Safe to delete yourself.
