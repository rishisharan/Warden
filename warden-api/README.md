# Warden API

Permission-aware knowledge retrieval for a fictional B2B support team.

## Architecture

- **warden-search/ingestion.py** owns bulk ingestion:
  chunks the fake seed documents, embeds them with OpenAI
  `text-embedding-3-small`, and stores them into three Chroma collections
  (`policy_docs`, `slack_messages`, `support_tickets`) under
  `data/chroma_store`, each chunk tagged with `access_level` metadata
  ("public" or "manager"). Access level is detected from a marker already
  written into each document's own text ("(Confidential...)",
  "(Restricted...)", "Manager Access"), not a hand-maintained filename
  list - see "Known gap" history below.
- **warden-search/retrieval_service.py** (Flask) queries those same
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

## Local security setup

Configure these values outside source control before starting the services.

| Variable | Process | Value |
|---|---|---|
| WARDEN_REP_PASSWORD_HASH | Java | BCrypt hash for user-a |
| WARDEN_MANAGER_PASSWORD_HASH | Java | BCrypt hash for user-b |
| WARDEN_RETRIEVAL_SERVICE_TOKEN | Java and Flask | The same high-entropy service token |
| WARDEN_EVAL_REP_PASSWORD | Live evaluator only | Demo rep password |
| WARDEN_EVAL_MANAGER_PASSWORD | Live evaluator only | Demo manager password |

Use different passwords for the two accounts. An account without a configured
hash cannot sign in. If your local Python environment already includes bcrypt,
this PowerShell example prompts for each password without putting it in the
command history. Launch Java and Flask from shells that inherit their required
variables.

~~~powershell
$env:WARDEN_REP_PASSWORD_HASH = python -c "import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass('Rep password: ').encode(), bcrypt.gensalt()).decode())"
$env:WARDEN_MANAGER_PASSWORD_HASH = python -c "import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass('Manager password: ').encode(), bcrypt.gensalt()).decode())"
$env:WARDEN_RETRIEVAL_SERVICE_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
~~~

Use localhost consistently for the browser and Java so the browser sends the
session cookie. Use HTTPS for any environment outside the local demo.

To verify the boundaries, sign in as user-a and send a query body containing
userId set to user-b. The response still identifies user-a. With the rep session
and a valid CSRF token, a document upload returns 403. Sign in as user-b to
verify a valid upload succeeds. A direct request to Flask search or ingest
without the service token returns 401, including requests with a user session
cookie. A synthetic integration test makes Flask return a manager chunk to a
rep and asserts 502, a recorded retrieval violation, and no Ollama request.

## Run it

Run each command block from the repository root. Set OPENAI_API_KEY in `warden-search/.env` or in your shell. Both Python entry points support `WARDEN_ENV_FILE` to select a different dotenv file and `WARDEN_DATA_DIR` to select a different data directory.

1. Run ingestion (only needed once, or again after adding/changing the
   seed docs on disk - uploads through the UI don't need this):
   ```
   python -m pip install -r warden-search/requirements.txt
   python warden-search/ingestion.py
   ```

2. Start the retrieval service:
   ```
   python warden-search/retrieval_service.py
   ```
   Runs on port 8011.

3. Make sure Ollama is running locally with the chat model pulled:
   ```
   ollama pull llama3.2
   ```

4. Start the Java app:
   ```
   mvn -f warden-api/pom.xml spring-boot:run
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

6. Sign in at http://localhost:5173 as user-a (support rep) or user-b (manager).
   Managers can publish documents. For Postman, import the collection from
   warden-api. In a local Postman environment, set warden_username and
   warden_password. Run Get CSRF token, then Sign in, then Get CSRF token again.
   Keep Postman's cookie jar enabled. To switch roles,
   sign out and repeat the sign-in sequence.


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
the bug, not a live warning - bulk ingestion uses content markers. Manager-authenticated uploads use the publisher-selected access label.

## Known MVP simplifications

- Two-tier access level (public / manager), not the fuller role+ACL
  layering discussed for later.
- The demo uses two locally configured accounts and server-side sessions.
  Manager accounts are trusted publishers and choose the document access label.
- Document upload accepts `.txt` / `.md` only, up to 2 MB - no PDF/DOCX
  extraction yet.
- Provider and connectivity errors generally surface
  as plain 500s.

## Cleanup

`_to_delete/` holds the earlier Postgres/pgvector version of this project,
superseded twice now (first by Chroma+Ollama-embeddings, now by
Chroma+OpenAI-embeddings to match ingestion.py). Safe to delete yourself.

## Python virtual environment on Windows

Run these commands in CMD from the repository root to install the Python dependencies once.

```
python -m venv warden-search\.venv
warden-search\.venv\Scripts\python.exe -m pip install -r warden-search\requirements.txt
```

In a new CMD window, launch the service from the repository root with the same environment.

```
warden-search\.venv\Scripts\python.exe warden-search\retrieval_service.py
```
