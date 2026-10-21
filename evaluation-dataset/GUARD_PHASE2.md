# Warden Guard Phase 2

Opt-in, same-request instrumentation. No endpoint or UI was added; existing query
response fields, prompts, source selection, RRF ranking and citations are preserved.
Instrumentation observes violations; it does not introduce a new authorization
gate or change how Warden handles a deliberately defective retriever.

## Evidence flow

Spring creates a full UUID (`X-Trace-Id`). Both Flask `/search` and the Ollama HTTP
invocation receive that header. Flask echoes it in the response header and its
metadata-only observation. Java compares Flask's observation with the actual
received records. A mismatch leaves `retrievalComplete=false`.

Document IDs are SHA-256 of compact JSON `[collection, source]`, not document text.
The old content-bearing retrieval ID remains internal and is never copied into
evidence. This is document-level identity, not chunk/version identity. Missing
source metadata yields an invalid ID and a blocking evaluator error.

Java records the retrieved documents and ALLOW/DENY/UNKNOWN metadata assessments
against the resolved user's allowed levels. These observations are not independent
proof of authorization: Guard's separately authored policy remains authoritative.
The context IDs are recorded in the same loop that builds the outgoing Ollama
source block. Warden currently selects only the first retrieved chunk; citations
continue to describe all retrieved chunks, as before.

After the request finishes, Spring atomically writes `<request UUID>.json` in a
configured private local directory. Collection is thread-local and always cleared.
Empty retrieval explicitly records no model invocation. Model/request errors leave
incomplete observations. Write failures leave missing evidence; they do not change
the application's normal answer, but they block the security test.

No source text, source filenames, raw legacy IDs, questions, answers or prompts are
written to these files. Existing raw document and prompt logging was removed.
Ollama itself is not assumed to log or echo our correlation header.

## Enable only in isolated local tests

Spring arguments (use an existing user-only directory on your computer):

```text
--app.warden.guard.enabled=true
--app.warden.guard.evidence-dir=<absolute-private-directory>
```

Flask environment:

```text
WARDEN_GUARD_ENABLED=true
```

Both are off by default. Flask still adds a safe `documentId` field and correlation
header when instrumentation is off. Default storage and embedding providers remain
unchanged; `WARDEN_DATA_DIR` optionally selects a separate test corpus/store root,
and `WARDEN_ENV_FILE` optionally selects a test dotenv file. Initialization is lazy
so the synthetic tests do not construct an OpenAI client or read real credentials.

Run the evaluator from the repo root:

```powershell
python evaluation-dataset/evaluation_set_2.py --guard-live evaluation-dataset/fixtures/guard_phase2.json --evidence-dir <absolute-private-directory> --query-url http://127.0.0.1:8082/api/query --report-dir <report-directory>
```

The supplied manifest describes only the synthetic test corpus, not your existing
documents. Do not run it against the real corpus and assume it will pass.
The adapter makes one query per case, validates the response UUID, reads only that
request's evidence file, checks decision coverage, and calls the Phase 1 scorer.
It polls for at most two seconds for the atomic file to appear. Transport errors,
missing files, unknown users, inconsistent decisions, partial traces and zero cases
cannot succeed. Reports omit raw answers; answers are held in memory only.

## Test commands

Java 21+ and Maven:

```powershell
mvn -f warden-api/pom.xml test package
```

Pure evaluator tests still need only Python 3.10+:

```powershell
python -B -m unittest discover -s evaluation-dataset/tests -v
```

Full synthetic integration requires Python packages `flask`, `chromadb`,
`rank-bm25`, `python-dotenv`, and the built `warden-api/target/warden-api.jar`:

```powershell
python -m pip install flask chromadb rank-bm25 python-dotenv
python -B -m unittest discover -s warden-api/python-retrieval/tests -v
$env:WARDEN_RUN_INTEGRATION = '1'
python -B -m unittest discover -s evaluation-dataset/tests -v
```

Optionally set `WARDEN_TEST_JAVA` to the Java executable and
`WARDEN_TEST_REPORT_DIR` to an output directory for sanitized integration results.
Without the integration flag, the live-chain tests are explicitly skipped, not
claimed as live security validation.

The integration harness launches Spring, Flask and a recording Ollama stub on
loopback ephemeral ports. Chroma is real and ephemeral, with explicit vectors and
no downloaded embedding model. A thin test adapter replaces LangChain's wrapper,
not Chroma or the production retrieval algorithm. OpenAI embedding quality and real
Ollama generation are outside this test's claim. The harness terminates its Java
process and local servers after testing.

The deliberate filter defect is confined to the synthetic store adapter. Its
restricted document reaches the actual serialized Ollama request; the recording
stub returns a refusal. Guard must still produce FAIL/nonzero, while authorized
public/manager controls pass. Additional tests cover missing evidence, exact first
context, disabled collection, empty retrieval and concurrent API calls.

## Scope and limitations

This covers returned retrieval output and serialized model context, not every
dense/BM25 candidate or vector-database internal operation. It trusts local
instrumentation and filesystem ownership; it is not tamper-proof attestation.
The current application still uses a body-supplied user selector, not authenticated
identity. A safe model answer never overrides a retrieval/context violation.
The local evidence channel is designed for this synchronous, single-model-call
application. Async execution, multi-call agents, tenant policy and ACL revocation
need explicit future contract work, not implied coverage.

## Files changed in Phase 2

- Existing: `TraceIdFilter.java`, `RetrievedChunk.java`, `QueryService.java`,
  `RetrievalService.java`, `OllamaChatService.java`, `retrieval_service.py`,
  retrieval `requirements.txt`, and `evaluation_set_2.py`.
- Added: `SecurityEvidence.java`, `EvidenceWriter.java`,
  `GuardInstrumentationTest.java`, retrieval `tests/test_guard_instrumentation.py`,
  `guard_live.py`, `fixtures/guard_phase2.json`, `tests/test_guard_live.py`,
  `tests/test_guard_end_to_end.py`, and this document.

`QueryController.java` and the Phase 1 scorer/tests did not need changes. The
additional end-to-end test replaces the planned controller edit with stronger
verification of actual HTTP calls. Existing unrelated working-tree changes remain.
