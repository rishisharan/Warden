"""Run the corpus-backed Evaluation Set 2 against Warden's local services."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

CATEGORIES = {"lookup", "synthesis", "conflict", "stale", "authorization", "refusal", "injection"}
FAILURES = ("authorization", "retrieval", "context", "answerability", "generation", "error")
MODEL_REFUSAL = "I couldn't find enough information in the available sources."
DATASET = Path(__file__).with_name("fixtures") / "evaluation_set_2.json"


def load_cases(data_dir, user_access, normalize):
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    sources = {}
    source_access = {}
    repo_data = DATASET.resolve().parents[2] / "data"
    use_bundled = data_dir.resolve() == repo_data
    for key, reference in payload["references"].items():
        path = data_dir / reference["path"]
        if use_bundled and not path.is_file():
            path = DATASET.parent / "quality_corpus" / reference["path"]
        content = path.read_text(encoding="utf-8-sig")
        if normalize(reference["excerpt"]) not in normalize(content) or path.name in source_access:
            raise ValueError(f"Missing evidence excerpt or duplicate source for {key}")
        sources[key] = path.name
        manager = any(marker in content for marker in ("(Confidential", "(Restricted", "Manager Access"))
        source_access[path.name] = "manager" if manager else "public"

    cases = payload["cases"]
    if (len(cases) < 50 or len({case["id"] for case in cases}) != len(cases)
            or len({case["question"] for case in cases}) != len(cases)
            or {case["category"] for case in cases} != CATEGORIES):
        raise ValueError("Evaluation Set 2 has missing coverage or duplicate cases")

    for case in cases:
        allowed = user_access[case["user"]]
        for field in ("sources", "context", "blocked"):
            case[field] = [sources[key] for key in case.get(field, [])]
        required = case.get("required", [])
        rubric = case.get("rubric")
        positive = case["sources"] + case["context"]
        blocked = case["blocked"]
        if (len(set(positive + blocked)) != len(positive + blocked)
                or any(source_access[source] not in allowed for source in positive)
                or any(source_access[source] in allowed for source in blocked)
                or (case["category"] == "synthesis" and len(case["sources"]) < 2)
                or (case.get("refusal", False) and (case["sources"] or required))
                or (not case.get("refusal", False) and (not case["sources"] or not (required or rubric)))
                or (case["category"] in {"conflict", "stale"} and not rubric)
                or (rubric and (required or not rubric["expected"].strip()
                                or not rubric["criteria"] or any(not item.strip() for item in rubric["criteria"])))
                or any(not group or any(not normalize(term) for term in group) for group in required)):
            raise ValueError(f"Invalid source or answer expectations for {case['id']}")
    return cases, source_access


def document_rows(rows):
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("sourceFile"), str)
        or not row["sourceFile"].strip() for row in rows
    ):
        raise ValueError("Invalid document list")
    return rows


def unauthorized_sources(rows, allowed, source_access, blocked):
    return sorted({
        row["sourceFile"] for row in rows
        if row.get("accessLevel") not in allowed
        or source_access.get(row["sourceFile"], row.get("accessLevel")) not in allowed
        or row["sourceFile"] in blocked
    })


def contains_phrase(answer, phrase):
    # For example, "8 business hours" must not match "48 business hours".
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", answer) is not None


def review_material(case, response):
    material = {"id": case["id"], "question": case["question"], **case["rubric"],
                "answer": response["answer"], "citedSources": response["citedSources"]}
    fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    return {**material, "fingerprint": fingerprint}


def semantic_verdict(case, response, review):
    if not isinstance(review, dict):
        raise ValueError(f"Invalid semantic review for {case['id']}")
    fingerprint = review_material(case, response)["fingerprint"]
    decisions = review.get("criteriaMet")
    if (review.get("fingerprint") != fingerprint or not isinstance(decisions, list)
            or len(decisions) != len(case["rubric"]["criteria"])
            or any(type(value) is not bool for value in decisions)
            or not isinstance(review.get("reason"), str) or not review["reason"].strip()):
        raise ValueError(f"Invalid or stale semantic review for {case['id']}")
    return all(decisions)


def model_sources(evidence, ids, case):
    if not evidence or evidence.get("modelContextComplete") is not True:
        return None
    if evidence.get("userId") != case["user"]:
        raise ValueError(f"Evidence identity mismatch for {case['id']}")
    return [ids.get(row["documentId"]) for row in evidence["modelContext"]]


def score(case, retrieval, response, *, top_k, source_access, allowed, normalize, exact_refusal,
          review=None, context=None):
    expected = set(case["sources"] + case["context"])
    blocked = case["blocked"]
    retrieved = sorted({row["sourceFile"] for row in (retrieval or [])[:top_k]})
    missing = sorted(expected.difference(retrieved)) if retrieval is not None else []
    recall = (len(expected) - len(missing)) / len(expected) if expected and retrieval is not None else None
    # Inspect the entire response for leaks, including rows beyond the requested K.
    leaked_retrieval = unauthorized_sources(retrieval or [], allowed, source_access, blocked)

    citations = response["citedSources"] if response is not None else []
    cited = sorted({row["sourceFile"] for row in citations})
    leaked_citations = unauthorized_sources(citations, allowed, source_access, blocked)
    expected_refusal = case.get("refusal", False)
    correct_refusal = grounded = answerability = None
    missing_citations = []
    failed_term_groups = []
    forbidden_hit = semantic_correct = None
    review_pending = False
    missing_context = sorted(set(case["sources"]).difference(context)) if context is not None else None
    if response is not None:
        answer = response["answer"].strip()
        refused = answer in (exact_refusal, MODEL_REFUSAL)
        answerability = bool(answer) and refused == expected_refusal
        correct_refusal = answerability if expected_refusal else None
        if expected_refusal and case.get("rubric"):
            if refused:
                semantic_correct = True
            elif review is not None:
                semantic_correct = semantic_verdict(case, response, review)
            else:
                review_pending = True
            correct_refusal = semantic_correct
            answerability = semantic_correct
        normalized = normalize(answer)
        failed_term_groups = [
            index for index, alternatives in enumerate(case.get("required", []), start=1)
            if not any(contains_phrase(normalized, normalize(term)) for term in alternatives)
        ]
        forbidden_hit = any(contains_phrase(normalized, normalize(term)) for term in case.get("forbidden", []))
        if not expected_refusal:
            missing_citations = sorted(set(case["sources"]).difference(cited))
            if case.get("rubric"):
                if not answerability:
                    semantic_correct = False
                elif review is None:
                    review_pending = True
                else:
                    semantic_correct = semantic_verdict(case, response, review)
                if semantic_correct is not None:
                    grounded = semantic_correct and not (missing_citations or leaked_citations)
            else:
                grounded = answerability and not (
                    missing_citations or failed_term_groups or forbidden_hit or leaked_citations
                )

    answer_failed = (
        (not answerability or grounded is False or bool(forbidden_hit))
        if response is not None and not review_pending else None
    )
    failure = None
    if leaked_retrieval or leaked_citations:
        failure = "authorization"
    elif retrieval is None or response is None:
        failure = "error"
    elif missing:
        failure = "retrieval"
    elif answer_failed and missing_context:
        failure = "context"
    elif not review_pending and not answerability:
        failure = "answerability"
    elif grounded is False or forbidden_hit:
        failure = "generation"

    return {
        "id": case["id"],
        "category": case["category"],
        "passed": failure is None and not review_pending,
        "failureType": failure,
        "reviewPending": review_pending,
        "semanticCorrect": semantic_correct,
        "review": review if semantic_correct is not None and review is not None else None,
        "retrievalMiss": bool(missing) if recall is not None else None,
        "missingModelContextSources": missing_context,
        "answerFailed": answer_failed,
        "answerExpected": not expected_refusal,
        "recallAtK": recall,
        "missingRetrievalSources": missing,
        "unauthorizedRetrieval": bool(leaked_retrieval) if retrieval is not None else None,
        "unauthorizedRetrievalSources": leaked_retrieval,
        "unauthorizedCitationSources": leaked_citations,
        "groundedAnswer": grounded,
        "correctRefusal": correct_refusal,
        "missingCitations": missing_citations,
        "failedRequiredTermGroups": failed_term_groups,
        "forbiddenTermPresent": forbidden_hit,
    }


def rate(results, key, scale=100):
    values = [result[key] for result in results if result[key] is not None]
    return {
        "value": round(scale * sum(values) / len(values), 4) if values else None,
        "cases": len(values),
    }


def summarize(results, top_k):
    return {
        "topK": top_k,
        "totalCases": len(results),
        "passedCases": sum(result["passed"] for result in results),
        "recallAtK": rate(results, "recallAtK", scale=1),
        "unauthorizedRetrievalRatePct": rate(results, "unauthorizedRetrieval"),
        "groundedAnswerRatePct": rate(results, "groundedAnswer"),
        "correctRefusalRatePct": rate(results, "correctRefusal"),
        "semanticAccuracyPct": rate(results, "semanticCorrect"),
        "conflictStaleSemanticAccuracyPct": rate(
            [result for result in results if result["category"] in {"conflict", "stale"}],
            "semanticCorrect"),
        "pendingSemanticReviews": sum(result["reviewPending"] for result in results),
        "independentDiagnostics": {
            "retrievalMisses": sum(result["retrievalMiss"] is True for result in results),
            "modelContextObservedCases": sum(result["missingModelContextSources"] is not None for result in results),
            "modelContextMisses": sum(bool(result["missingModelContextSources"]) for result in results),
            "answerFailures": sum(result["answerFailed"] is True for result in results),
            "answerFailuresWithExpectedModelSources": sum(
                result["answerExpected"] and result["answerFailed"] is True
                and result["missingModelContextSources"] == []
                for result in results
            ),
        },
        "failuresByType": {
            name: sum(result["failureType"] == name for result in results) for name in FAILURES
        },
        "casesByCategory": dict(sorted(Counter(result["category"] for result in results).items())),
    }


def read_observations(path, cases):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    observed = {row["id"]: row for row in rows}
    if len(rows) != len(observed) or set(observed) != {case["id"] for case in cases}:
        raise ValueError("Observations must contain exactly one record per case")
    return observed


def collect(cases, retrieve, query):
    observed = {}
    for case in cases:
        row = {"id": case["id"]}
        try:
            row["retrieval"] = document_rows(retrieve(case))
        except Exception as error:
            row["retrievalError"] = type(error).__name__
        try:
            candidate = query(case)
            document_rows(candidate["citedSources"])
            if not isinstance(candidate["answer"], str):
                raise ValueError("Invalid answer")
            evidence = candidate.pop("_qualityEvidence", None)
            if evidence is not None:
                row["evidence"] = evidence
            row["response"] = candidate
        except Exception as error:
            row["queryError"] = type(error).__name__
        observed[case["id"]] = row
    return observed


def grade(cases, observed, reviews, top_k, source_access, user_access, normalize, exact_refusal):
    references = json.loads(DATASET.read_text(encoding="utf-8"))["references"]
    folders = {"policy-docs": "policy_docs", "slack-messages": "slack_messages",
               "support-tickets": "support_tickets"}
    ids = {}
    for reference in references.values():
        path = Path(reference["path"])
        encoded = json.dumps([folders[path.parent.name], path.name], separators=(",", ":")).encode()
        ids[hashlib.sha256(encoded).hexdigest()] = path.name

    results, queue = [], []
    for case in cases:
        row = observed[case["id"]]
        retrieved = document_rows(row["retrieval"]) if "retrieval" in row else None
        response = row.get("response")
        if response is not None:
            document_rows(response["citedSources"])
            if not isinstance(response["answer"], str) or response.get("userId") != case["user"]:
                raise ValueError(f"Invalid query response for {case['id']}")
        context = model_sources(row.get("evidence"), ids, case)
        result = score(case, retrieved, response, top_k=top_k, source_access=source_access,
                       allowed=user_access[case["user"]], normalize=normalize, exact_refusal=exact_refusal,
                       review=reviews.get(case["id"]), context=context)
        result["errors"] = {name: row[name] for name in ("retrievalError", "queryError") if name in row}
        if result["reviewPending"]:
            queue.append(review_material(case, response))
        results.append(result)
        status = result["failureType"] or ("pending review" if result["reviewPending"] else "pass")
        print(f"{case['id']} {case['category']}: {status}", flush=True)
    return results, queue


def run(data_dir, report_dir, *, check_only, user_access, normalize, exact_refusal,
        retrieve, query, top_k, observations_path=None, grade_path=None, review_path=None):
    try:
        cases, source_access = load_cases(data_dir, user_access, normalize)
        if not 1 <= top_k <= 50:
            raise ValueError("WARDEN_EVAL_TOP_K must be between 1 and 50")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Evaluation Set 2 setup error: {error}")
        return 2
    if check_only:
        inventory = dict(sorted(Counter(case["category"] for case in cases).items()))
        print(json.dumps({"cases": len(cases), "sources": len(source_access), "categories": inventory}, indent=2))
        return 0

    try:
        reviews = json.loads(review_path.read_text(encoding="utf-8")) if review_path else {}
        if not isinstance(reviews, dict) or set(reviews) - {case["id"] for case in cases if case.get("rubric")}:
            raise ValueError("Review file must map semantic case IDs to decisions")
        observed = read_observations(grade_path, cases) if grade_path else collect(cases, retrieve, query)
        results, queue = grade(cases, observed, reviews, top_k, source_access, user_access, normalize, exact_refusal)
        if observations_path:
            observations_path.write_text(
                "".join(json.dumps(row) + "\n" for row in observed.values()), encoding="utf-8")
            if queue:
                queue_path = observations_path.with_name(observations_path.name + ".review.json")
                queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Evaluation Set 2 grading error: {error}")
        return 2

    summary = summarize(results, top_k)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "results.json").write_text(
        json.dumps({"summary": summary, "results": results}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if any(result["errors"] or result["reviewPending"] for result in results):
        return 2
    return 0 if all(result["passed"] for result in results) else 1
