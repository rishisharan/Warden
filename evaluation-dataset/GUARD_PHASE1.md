# Warden Guard Phase 1

Strict authorization checks extend `evaluation_set_2.py`. The existing Warden
API, retrieval service, UI, and generation flow are unchanged. No infrastructure
or additional dependencies are needed for Guard checks or their tests.

## Run

From the repository root, with Python 3.10 or newer:

```powershell
python -m unittest discover -s evaluation-dataset/tests -v
python evaluation-dataset/evaluation_set_2.py --guard-evidence evaluation-dataset/fixtures/guard_phase1.json --report-dir evaluation-dataset/evaluation_results/guard
```

The unit tests should exit 0. The demonstration command intentionally exits **1**:
it includes two allowed cases and one unauthorized LLM-context example whose
final response refuses disclosure. That case must FAIL. Both retrieval and model
context violations are reported. JSON and Markdown reports contain verdicts and
evidence errors, not raw answers, prompts, or source text.

Exit codes: 0 = all supplied cases PASS; 1 = known authorization failure;
2 = input/evidence error or zero cases. Known violations retain a FAIL verdict
even if there are also evidence errors; the suite then exits 2 to flag incomplete
execution as well. A PASS is scoped to the supplied evidence, not live security.

For the original networked quality evaluator, explicitly run:

```powershell
python evaluation-dataset/evaluation_set_2.py --legacy-quality
```

This still needs `requests` and the existing Warden services. Its manager mapping
now matches local Java `user-b`. Unknown test users, fixture-probe errors, empty
suites, and skipped/failed cases cannot return success. Its original heuristic
quality checks otherwise remain intact. It is clearly labeled quality-only:
separate retrieval probes and citations do not establish model-context security.
Running without a mode exits 2 rather than silently presenting quality tests as
strict security tests.

## Independent policy and evidence contract

The JSON input has a `policy` object and a `cases` array. Policy is test-owned;
never construct it from the target response or allow the target to choose it.
This phase supports the local public/manager tiers. See `fixtures/guard_phase1.json`
for the complete format.

- `policy.schemaVersion`: integer 1; `users`: user ID to allowed-level list;
  `documents`: opaque document ID to expected access level.
- Each entry has `case` (`id`, known `userId`, optional `forbiddenDocumentIds`)
  and `response` (`userId`, `traceId`, string `answer`, `evidence`).
- Evidence needs integer `schemaVersion: 1`, `requestId` matching `traceId`,
  matching `userId`, booleans `retrievalComplete` and `modelContextComplete`
  both true, boolean `modelCalled`, and explicit `retrieved` and `modelContext`
  arrays. Every record needs known `documentId` and valid `accessLevel`.
- Model-context IDs must also occur in retrieval evidence. A no-model-call case
  must have an empty model context. Completed empty retrieval plus no model call
  is valid evidence; missing arrays are not equivalent to empty arrays.
- Every observed document is checked against independent policy, even without a
  forbidden-ID list. Incorrectly labeling a manager document public cannot make
  it pass. Missing metadata, unknown documents, mismatched request/principal IDs,
  incomplete evidence, malformed policies, duplicate test IDs, and reused request
  IDs block success.

## Boundaries

All fixture data is synthetic. Evidence is recorded/replayed; the current Warden
application does **not** yet emit this contract. The evaluator does not fabricate
evidence from citations, call a second retrieval endpoint in Guard mode, or assert
that the final refusal prevents unauthorized context exposure.

The contract covers supplied retrieval output and supplied model context. It does
not prove hidden dense/BM25 candidate handling, database internals, omitted model
calls, tenant boundaries, actual authentication, or prompt-injection resistance.
Completion flags are assertions by the evidence producer, not proof of complete
instrumentation. Multiple model calls and chunk/version-level tracing are later
contract extensions. A real integration must instrument the actual same request
and collect trustworthy evidence; otherwise it cannot claim a live Guard PASS.

Use only opaque IDs and synthetic inputs here: Warden's current content-bearing
retrieval IDs must not be copied into reports. Reports include known policy IDs
in JSON and numeric labels in Markdown to avoid rendering untrusted identifiers.
Report directories are replaced on each invocation; use separate directories for
concurrent runs. Report write failures terminate nonzero.
