# Warden Guard: GitHub Actions security gate

The workflow runs on pull requests, pushes to main or warden-guard-* branches,
and manual dispatch. It uses
an ephemeral Ubuntu 24.04 runner, Temurin Java 21, Python 3.12, and reviewed full
commit SHA pins for checkout/setup/upload actions. It needs no application secrets,
OpenAI calls, real Ollama server, cloud deployment, or persistent test server.
The workflow has read-only repository permissions and does not persist checkout
credentials. It uses `pull_request`, never `pull_request_target` for contributor code.

## What runs

`ci_guard.py --run` executes these groups in isolated subprocesses:

1. Maven `package`: runs the Java instrumentation tests and builds the jar.
2. Evaluator and CI gate unit tests, excluding the separate full-chain class.
3. Flask retrieval tests with real ephemeral Chroma and explicit test vectors.
4. All four end-to-end tests, with `WARDEN_RUN_INTEGRATION=1` set by the runner.

No group may be empty, fall below its current minimum test inventory, skip required
tests, or have a nonzero process exit/failure/error count. Java results must come
from fresh Surefire XML in a unique temporary directory; old reports cannot satisfy
the gate. Surefire `failIfNoTests=true` also blocks the zero-test false green found
during review. The overridable test report directory is the only POM change.

Current inventories: 6 Java, 56 evaluator/gate, 5 retrieval, 4 full integration.
There are 71 tests in total. Adding tests is allowed; removing required tests needs
an explicit review of the gate's inventory. Ordinary unittest discovery can still
skip the integration class when not opted in; that is not a successful CI gate.

## Security assertions, not blanket nonzero suppression

The integration harness now records all four named scenarios, including concurrent
requests. The gate requires exactly these scenarios and eight distinct request
receipts:

| Scenario | Cases | Expected Guard verdict | Guard exit |
| --- | ---: | --- | ---: |
| Authorized public/manager controls | 2 | PASS | 0 |
| Concurrent public/manager controls | 4 | PASS | 0 |
| Deliberately missing Flask evidence | 1 | ERROR | 2 |
| Restricted context followed by refusal | 1 | FAIL | 1 |

The last two are successful unittest assertions only when the specified failure is
actually observed. A passing verdict in the deliberate-leak test is a regression.
An unexpected violation, unknown scenario, absent receipt, duplicate request ID,
missing authorization decisions, incomplete positive evidence, or zero executed
security cases makes the overall gate FAIL. A test process returning nonzero is
never excused merely because some scenario expects a negative Guard verdict.

The report validator independently re-scores the receipts against the synthetic
ACL manifest values. Expected negative outcomes are not trusted merely because a
JSON field says they occurred. The context-leak scenario must contain the forbidden
document in a completed, actual model invocation and a detected context violation.

## Reports and privacy

Before dependency setup, the workflow initializes a sanitized FAIL report. After
testing it produces only `results.json` and `summary.md` for publication. A separate
always-run verification step revalidates/rebuilds these reports, publishes Markdown
to the job summary, and exits nonzero unless the validated gate passed. Missing or
invalid reports are replaced with a sanitized failure report. Report write errors
are nonzero and do not print exception details.

Only known suite/scenario names, numeric counters, fixed reason codes, expected and
observed verdicts, canonical UUIDs, known synthetic document hashes, user-a/user-b,
access levels, completion flags, and authorization decisions are exported. The gate
builds this schema from allowlisted fields rather than copying arbitrary input.
Prompts, answers, source text, filenames, filesystem paths, exception messages,
credentials, process output, raw Surefire XML, and raw receipt files are not uploaded.

Raw subprocess/build diagnostics and receipt inputs stay in a unique temporary
directory and are removed on normal completion. The integration harness registers
cleanup for partially started services and writes its private scenario data in a
finally block. Final reporting does not require successful assertion teardown.
The current synthetic harness still keeps prompts in memory to verify the actual
serialized Ollama request; they are not part of the publishable report schema.

The artifact action runs even after test failure, uploading only the two sanitized
files with seven-day retention. Bootstrap errors remain FAIL; successful artifact
upload cannot turn the failed gate green. No paid service is provisioned. Standard
GitHub-hosted runner and artifact quotas still apply to the account/repository.

## Local reproduction

From the repository root, with Java 21+, Maven, and Python 3.12:

```powershell
python -m venv <temporary-venv>
<temporary-venv-python> -m pip install -r evaluation-dataset/requirements-ci.lock
<temporary-venv-python> -B evaluation-dataset/ci_guard.py --run --report-dir <report-directory>
<temporary-venv-python> -B evaluation-dataset/ci_guard.py --verify --report-dir <report-directory>
```

If needed locally, pass `--maven-repo <existing-maven-cache>` and set
`WARDEN_TEST_JAVA` to the Java executable. These paths are never reported.
No `WARDEN_RUN_INTEGRATION` flag is needed for the orchestrator; it enables and
requires full integration itself. The initializer is only a bootstrap step:
`--initialize` exits zero after writing FAIL, while `--verify` correctly rejects it
until a real completed run replaces it.

`requirements-ci.lock` freezes the tested Python dependency set, including Chroma's
transitive packages and the Linux-only uvloop extra. It is a version lock, not a
hash-locked supply-chain attestation. Linux wheel resolution is checked separately;
it is not equivalent to running tests on Linux.

Estimated GitHub execution is 3–7 minutes with cold dependencies. Local Windows
validation uses the installed JDK 22 targeting Java 21; the GitHub Ubuntu/Temurin 21
job can only be verified after an approved commit/push or other authorized dispatch.
Do not claim an uploaded GitHub artifact or successful hosted run from local tests.

## Scope and changed files

The production Java/Python request flow and UI are unchanged by Phase 3. Synthetic
fixtures remain isolated; the deliberate filter defect stays test-only. The report
does not certify real OpenAI/Ollama providers, authenticated identity, hidden retrieval
candidates, or tamper-proof instrumentation.

- Added `.github/workflows/warden-guard.yml`.
- Added `evaluation-dataset/ci_guard.py`.
- Added `evaluation-dataset/tests/test_ci_guard.py`.
- Added `evaluation-dataset/requirements-ci.lock`.
- Added this `evaluation-dataset/GUARD_PHASE3.md`.
- Updated `evaluation-dataset/tests/test_guard_end_to_end.py` for complete scenario
  recording and cleanup, including startup failures.
- Updated `warden-api/pom.xml` for strict, fresh test reporting only.

No commits, pushes, deployment, or repository settings changes are performed by the
implementation. To make CI merge-blocking later, explicitly configure the workflow's
`Synthetic security gate` check as required in the repository rules after its first
successful hosted run. Merely adding workflow YAML does not configure branch rules.
