# Warden Evaluation Set 2

The 54 cases use the synthetic documents under [data](../data). They cover 18
lookups, 10 cross-document questions, five conflicts, five stale-policy cases,
eight authorization checks, four refusals, and four injection cases. The
[case file](fixtures/evaluation_set_2.json) records the source paths, evidence
excerpts, expected answers, and expected refusals. The offline validator uses
the bundled synthetic additions in a fresh checkout when a referenced file
is absent from the repository data directory.

The [measured local baseline](baselines/local-ollama/summary.md) includes actual metrics and failure analysis.

## Run it

From the repository root, validate the fixtures and run the evaluator tests.
This step needs only Python and the checked-out corpus.

```powershell
python -B evaluation-dataset/evaluation_set_2.py --check-quality-v2
python -B -m unittest discover -s evaluation-dataset/tests
```

For a live run, follow the [local setup](../README.md#run-it) and
[security setup](../warden-api/README.md#local-security-setup) for dependencies and credentials. Prepare an isolated seed directory with both the
tracked base documents and the bundled additions, then point ingestion
and Flask at it. Ingestion rebuilds its target collections.

```powershell
$env:WARDEN_DATA_DIR = Join-Path $env:TEMP ("warden-eval2-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $env:WARDEN_DATA_DIR | Out-Null
foreach ($folder in 'policy-docs','slack-messages','support-tickets') {
    $target = New-Item -ItemType Directory -Path (Join-Path $env:WARDEN_DATA_DIR $folder)
    Copy-Item "data/$folder/*.md" $target
    Copy-Item "evaluation-dataset/fixtures/quality_corpus/$folder/*.md" $target
}
python warden-search/ingestion.py
python warden-search/retrieval_service.py
```

Start Java and Ollama as described in the local setup. Set the same data directory in the evaluator shell and supply the demo credentials and matching service token
in your shell as `WARDEN_EVAL_REP_PASSWORD`, `WARDEN_EVAL_MANAGER_PASSWORD`,
and `WARDEN_RETRIEVAL_SERVICE_TOKEN`.

```powershell
python -B evaluation-dataset/evaluation_set_2.py --quality-v2 --quality-observations observations.jsonl
```

Flask defaults to `http://localhost:8011/search`
(`WARDEN_RETRIEVAL_URL`). The query endpoint defaults to
`http://localhost:8082/api/query` (`WARDEN_QUERY_URL` or `--query-url`).
Use `--data-dir` for a different local fixture directory and
`WARDEN_EVAL_TOP_K` (default 5, range 1–50) to set the standalone retrieval
probe depth. The Java service independently configures its retrieval depth, which defaults to one chunk.
The evaluator writes `evaluation-dataset/evaluation_results/quality_set_2/results.json`.
Use `--report-dir` to pick a different destination. The sanitized report
includes source filenames and review decisions. The optional observations
and review queue contain raw synthetic answers. Keep them private and use
the capture flag only with the synthetic corpus.

## Review conflict and stale-policy answers

Each conflict, stale-policy, and refusal case has a gold outcome and criteria that specify which
source controls, which action or deadline applies, and when a discarded
value may be mentioned. Review the actual answers in
`observations.jsonl.review.json` against those criteria. Accept equivalent
wording and reject answers that state the right value but apply the wrong
policy. Record one boolean in criterion order, a brief reason, and the
unchanged fingerprint under each case ID in `decisions.json`.
The grader checks the fingerprint against the question, rubric, answer, and
citations. It handles exact refusals and empty answers deterministically.
The initial run exits 2 when semantic decisions are pending. Refusal reviews accept equivalent explanations and check that no missing or restricted facts are supplied.

```powershell
python -B evaluation-dataset/evaluation_set_2.py --grade-quality-v2 observations.jsonl --semantic-review decisions.json
```

Use the same corpus and `WARDEN_EVAL_TOP_K` for grading. For same-request
context diagnostics, enable Guard instrumentation on Flask and Java and
pass the private receipt directory with `--evidence-dir` during capture.
Receipts record document identities. A document match does not guarantee
that the specific supporting passage reached the model.

## Interpret results

- **Recall@K** averages the fraction of distinct expected documents found
  within the first K returned chunks per eligible case. Expected documents
  include answer sources and any explicit context or distractor documents.
- **Unauthorized retrieval rate** is the fraction of valid retrieval
  responses with at least one unauthorized row anywhere in the result.
  The evaluator checks reported access and the corpus labels for known
  references. Unauthorized API citations also fail the case.
- **Grounded-answer rate** is the fraction of answer-expected cases with a
  valid query response that cite all answer sources, avoid unauthorized
  citations, and satisfy the answer checks. Conflict and stale-policy
  answers require the criterion-level semantic review. Other positive
  cases use required and forbidden phrases and may miss valid paraphrases.
  An unexpected refusal counts as an ungrounded answer.
- **Correct-refusal rate** is the fraction of refusal-expected cases with
  a valid query response that satisfy the refusal criteria. Both canonical refusal messages pass directly. Equivalent explanations receive a semantic review.

Reports include each metric's denominator and a semantic accuracy rate
independent of citation coverage. The primary failure category gives
precedence to authorization, followed by request or response errors,
standalone retrieval misses, model-context gaps on failed answers,
answerability, and generation. Independent counts preserve overlapping
retrieval, context, and answer failures. Case details retain the available retrieval and
citation diagnostics even when a request fails. Exit codes are 0 for all
cases passing, 1 for evaluated failures, and 2 for setup or request errors.

The standalone Flask probe and Java query are separate requests. The Java
response currently lists the retrieved sources and sends only the first
chunk to Ollama. Expect this limit to affect synthesis, and use
[Warden Guard](GUARD_PHASE2.md) for same-request model-context evidence.
The legacy quality and Guard commands continue to use their existing modes.

## Add a case

Add a unique ID and question to the case file. Reuse a reference key or add
a corpus-relative path and literal evidence excerpt. Set `sources` to the
files required in the answer's citations, `context` to additional files
expected in retrieval, and `blocked` to any specifically targeted restricted
files. `required` contains groups of accepted phrases. Each group must match
at least one phrase. Use `forbidden` for known bad answers or attack markers
and `refusal: true` when a Warden refusal is expected. For conflict and stale
questions, use a `rubric` with the expected answer and criteria.
