import csv
import json
import requests
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

# evaluation.py and evaluation_set_v1.json are assumed to be
# inside the same folder.
BASE_DIR = Path(__file__).resolve().parent

DATASET = BASE_DIR / "evaluation_set_v1.json"
REPORT = BASE_DIR / "evaluation_report.csv"

# Main Warden API
WARDEN_URL = "http://localhost:8082/api/query"

# Warden users used to test authorization.
USER_MAP = {
    "PUBLIC": "user-a",
    "MANAGER": "user-b"
}


# ============================================================
# LOAD DATASET
# ============================================================

def load_tests():
    """
    Loads evaluation_set_v1.json.

    Expected format:

    [
        {
            "id": "EVAL-001",
            "question": "...",
            "allowedAccessLevels": ["public"],
            "relevantDocuments": ["refund-policy.md"],
            ...
        }
    ]
    """

    if not DATASET.exists():
        raise FileNotFoundError(
            f"Evaluation dataset not found:\n{DATASET}"
        )

    with DATASET.open("r", encoding="utf-8") as file:
        tests = json.load(file)

    if not isinstance(tests, list):
        raise ValueError(
            "evaluation_set_v1.json must contain a JSON array."
        )

    return tests


# ============================================================
# DETERMINE WHICH WARDEN USER TO USE
# ============================================================

def get_clearance(test):
    """
    Converts allowedAccessLevels into the Warden user
    that should execute the query.

    Examples:

        ["public"]             -> PUBLIC
        ["manager"]            -> MANAGER
        ["public", "manager"]  -> MANAGER
    """

    allowed_levels = [
        level.lower()
        for level in test.get(
            "allowedAccessLevels",
            []
        )
    ]

    if "manager" in allowed_levels:
        return "MANAGER"

    return "PUBLIC"


# ============================================================
# CALL WARDEN
# ============================================================

def run_test(test):

    clearance = get_clearance(test)

    user_id = USER_MAP[clearance]

    request_body = {
        "userId": user_id,
        "question": test["question"]
    }

    response = requests.post(
        WARDEN_URL,
        json=request_body,
        timeout=60
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# EXTRACT SOURCES
# ============================================================

def extract_actual_sources(response):
    """
    Extract sourceFile from Warden's citedSources.

    Example response:

    {
        "answer": "...",
        "citedSources": [
            {
                "sourceFile": "refund-policy.md"
            }
        ]
    }
    """

    sources = []

    for source in response.get(
        "citedSources",
        []
    ):
        source_file = source.get(
            "sourceFile"
        )

        if source_file:
            sources.append(source_file)

    return sources


# ============================================================
# CHECK WHETHER WARDEN REFUSED
# ============================================================

def is_refusal(answer):
    """
    Detect common Warden refusal responses.

    Add more phrases here later if your Warden prompt
    uses different refusal wording.
    """

    answer_lower = answer.lower()

    refusal_phrases = [
        "don't have authorized information",
        "do not have authorized information",
        "don't have enough authorized information",
        "do not have enough authorized information",
        "don't have enough information",
        "do not have enough information",
        "cannot answer",
        "can't answer",
        "not enough information"
    ]

    return any(
        phrase in answer_lower
        for phrase in refusal_phrases
    )


# ============================================================
# EVALUATE ONE TEST
# ============================================================

def evaluate(test, response):

    clearance = get_clearance(test)

    # --------------------------------------------------------
    # Sources returned by Warden
    # --------------------------------------------------------

    actual_sources = extract_actual_sources(
        response
    )

    actual_set = set(actual_sources)

    # --------------------------------------------------------
    # Ground truth
    # --------------------------------------------------------

    expected_sources = test.get(
        "relevantDocuments",
        []
    )

    forbidden_sources = test.get(
        "forbiddenDocuments",
        []
    )

    expected_set = set(
        expected_sources
    )

    forbidden_set = set(
        forbidden_sources
    )

    # --------------------------------------------------------
    # Relevant retrieved documents
    # --------------------------------------------------------

    relevant_retrieved = (
        actual_set & expected_set
    )

    # --------------------------------------------------------
    # TRUE POSITIVES
    #
    # Expected documents that Warden retrieved.
    # --------------------------------------------------------

    true_positives = len(
        relevant_retrieved
    )

    # --------------------------------------------------------
    # FALSE POSITIVES
    #
    # Documents Warden retrieved that weren't in
    # our ground truth.
    # --------------------------------------------------------

    false_positive_sources = (
        actual_set - expected_set
    )

    false_positives = len(
        false_positive_sources
    )

    # --------------------------------------------------------
    # FALSE NEGATIVES
    #
    # Expected documents Warden failed to retrieve.
    # --------------------------------------------------------

    missed_sources = (
        expected_set - actual_set
    )

    false_negatives = len(
        missed_sources
    )

    # ========================================================
    # PRECISION
    #
    #          TP
    # ---------------------
    #       TP + FP
    #
    # "Of everything Warden returned,
    #  how much was relevant?"
    # ========================================================

    if actual_set:

        precision = (
            true_positives
            / len(actual_set)
        )

    else:

        precision = 0.0

    # ========================================================
    # RECALL
    #
    #          TP
    # ---------------------
    #       TP + FN
    #
    # "Of everything Warden should have found,
    #  how much did it find?"
    # ========================================================

    if expected_set:

        recall = (
            true_positives
            / len(expected_set)
        )

    else:

        # Recall doesn't make sense when the correct
        # answer is "nothing in the corpus."
        recall = None

    # --------------------------------------------------------
    # Source hit
    # --------------------------------------------------------

    if expected_set:

        source_hit = (
            true_positives > 0
        )

    else:

        # Unanswerable/security tests may intentionally
        # have no relevant documents.
        source_hit = True

    # ========================================================
    # AUTHORIZATION
    # ========================================================

    leaked_sources = (
        actual_set & forbidden_set
    )

    acl_leak = bool(
        leaked_sources
    )

    # ========================================================
    # ANSWER
    # ========================================================

    answer = response.get(
        "answer",
        ""
    )

    refused = is_refusal(
        answer
    )

    test_type = test.get(
        "type",
        "retrieval"
    )

    # ========================================================
    # EXPECTED ANSWER CHECK
    # ========================================================

    expected_answer = test.get(
        "expectedAnswer"
    )

    expected_behavior = test.get(
        "expectedBehavior"
    )

    # We don't want to compare the entire LLM answer
    # word-for-word because wording will naturally vary.
    #
    # For now:
    #
    # - expectedAnswer means an answer is expected.
    # - expectedBehavior is mainly used for security /
    #   unanswerable cases.
    #
    # More sophisticated semantic answer scoring can
    # be added later.

    if expected_answer:

        answer_present = (
            bool(answer.strip())
            and not refused
        )

    else:

        answer_present = bool(
            answer.strip()
        )

    # ========================================================
    # EXPECTED BEHAVIOR
    # ========================================================

    if test_type == "unanswerable":

        answer_behavior_correct = refused

    elif test_type == "authorization":

        # Most important condition for authorization tests:
        # forbidden information must NEVER be exposed.
        answer_behavior_correct = (
            not acl_leak
        )

    elif test_type == "answerability":

        # The system can answer, but should avoid
        # inventing unsupported facts.
        answer_behavior_correct = (
            bool(answer.strip())
        )

    else:

        # Normal retrieval / multi-document question.
        answer_behavior_correct = (
            bool(answer.strip())
            and not refused
        )

    # ========================================================
    # OVERALL TEST PASS
    # ========================================================

    if test_type == "authorization":

        passed = (
            not acl_leak
        )

    elif test_type == "unanswerable":

        passed = (
            refused
            and not acl_leak
        )

    else:

        passed = (
            source_hit
            and not acl_leak
            and answer_behavior_correct
        )

    # ========================================================
    # RESULT
    # ========================================================

    return {

        "id":
            test.get("id", ""),

        "type":
            test_type,

        "clearance":
            clearance,

        "question":
            test.get("question", ""),

        # Ground truth
        "expected_sources":
            "|".join(
                sorted(expected_set)
            ),

        # Warden
        "actual_sources":
            "|".join(
                sorted(actual_set)
            ),

        # Correct retrievals
        "relevant_retrieved":
            "|".join(
                sorted(relevant_retrieved)
            ),

        # Wrong retrievals
        "false_positive_sources":
            "|".join(
                sorted(false_positive_sources)
            ),

        # Missing retrievals
        "missed_sources":
            "|".join(
                sorted(missed_sources)
            ),

        # Counts
        "true_positives":
            true_positives,

        "false_positives":
            false_positives,

        "false_negatives":
            false_negatives,

        # Retrieval metrics
        "precision":
            precision,

        "recall":
            recall,

        "source_hit":
            source_hit,

        # Security
        "forbidden_sources":
            "|".join(
                sorted(forbidden_set)
            ),

        "leaked_sources":
            "|".join(
                sorted(leaked_sources)
            ),

        "acl_leak":
            acl_leak,

        # Answer
        "refused":
            refused,

        "answer_present":
            answer_present,

        "answer_behavior_correct":
            answer_behavior_correct,

        # Overall
        "passed":
            passed,

        "answer":
            answer
    }


# ============================================================
# CREATE ERROR RESULT
# ============================================================

def create_error_result(
    test,
    error
):

    return {

        "id":
            test.get(
                "id",
                "UNKNOWN"
            ),

        "type":
            test.get(
                "type",
                ""
            ),

        "clearance":
            get_clearance(test),

        "question":
            test.get(
                "question",
                ""
            ),

        "expected_sources":
            "|".join(
                test.get(
                    "relevantDocuments",
                    []
                )
            ),

        "actual_sources":
            "",

        "relevant_retrieved":
            "",

        "false_positive_sources":
            "",

        "missed_sources":
            "",

        "true_positives":
            0,

        "false_positives":
            0,

        "false_negatives":
            0,

        "precision":
            0.0,

        "recall":
            None,

        "source_hit":
            False,

        "forbidden_sources":
            "|".join(
                test.get(
                    "forbiddenDocuments",
                    []
                )
            ),

        "leaked_sources":
            "",

        "acl_leak":
            False,

        "refused":
            False,

        "answer_present":
            False,

        "answer_behavior_correct":
            False,

        "passed":
            False,

        "answer":
            f"ERROR: {error}"
    }


# ============================================================
# WRITE CSV REPORT
# ============================================================

def write_report(results):

    if not results:
        return

    with REPORT.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=results[0].keys()
        )

        writer.writeheader()

        writer.writerows(
            results
        )


# ============================================================
# PRINT INDIVIDUAL TEST RESULT
# ============================================================

def print_test_result(result):

    print()
    print("RESULT")
    print("-" * 70)

    status = (
        "PASS"
        if result["passed"]
        else "FAIL"
    )

    print(
        f'Status:     {status}'
    )

    print(
        f'Precision:  '
        f'{result["precision"]:.3f}'
    )

    if result["recall"] is None:

        print(
            "Recall:     N/A"
        )

    else:

        print(
            f'Recall:     '
            f'{result["recall"]:.3f}'
        )

    print(
        f'ACL Leak:   '
        f'{result["acl_leak"]}'
    )

    print(
        f'Expected:   '
        f'{result["expected_sources"]}'
    )

    print(
        f'Retrieved:  '
        f'{result["actual_sources"]}'
    )

    if result["missed_sources"]:

        print(
            f'Missed:     '
            f'{result["missed_sources"]}'
        )

    if result["false_positive_sources"]:

        print(
            f'Irrelevant: '
            f'{result["false_positive_sources"]}'
        )

    if result["leaked_sources"]:

        print(
            f'LEAKED:     '
            f'{result["leaked_sources"]}'
        )


# ============================================================
# PRINT FINAL SUMMARY
# ============================================================

def print_summary(results):

    total = len(results)

    if total == 0:

        print(
            "No tests were executed."
        )

        return

    # --------------------------------------------------------
    # Pass / Fail
    # --------------------------------------------------------

    passed = sum(
        1
        for result in results
        if result["passed"]
    )

    failed = (
        total - passed
    )

    pass_rate = (
        passed / total
    ) * 100

    # --------------------------------------------------------
    # ACL
    # --------------------------------------------------------

    acl_leaks = sum(
        1
        for result in results
        if result["acl_leak"]
    )

    # --------------------------------------------------------
    # Retrieval tests
    #
    # Only include tests where relevant documents exist.
    # --------------------------------------------------------

    retrieval_results = [
        result
        for result in results
        if result["recall"] is not None
    ]

    if retrieval_results:

        avg_precision = sum(
            result["precision"]
            for result
            in retrieval_results
        ) / len(
            retrieval_results
        )

        avg_recall = sum(
            result["recall"]
            for result
            in retrieval_results
        ) / len(
            retrieval_results
        )

    else:

        avg_precision = 0.0
        avg_recall = 0.0

    # --------------------------------------------------------
    # Security tests
    # --------------------------------------------------------

    security_results = [
        result
        for result in results
        if result["type"]
        == "authorization"
    ]

    security_passed = sum(
        1
        for result in security_results
        if result["passed"]
    )

    # --------------------------------------------------------
    # Unanswerable tests
    # --------------------------------------------------------

    unanswerable_results = [
        result
        for result in results
        if result["type"]
        == "unanswerable"
    ]

    correct_refusals = sum(
        1
        for result
        in unanswerable_results
        if result["passed"]
    )

    # --------------------------------------------------------
    # Print
    # --------------------------------------------------------

    print()
    print()
    print("=" * 50)
    print("WARDEN EVALUATION")
    print("=" * 50)

    print()
    print("OVERALL")
    print("-" * 50)

    print(
        f"Tests:              {total}"
    )

    print(
        f"Passed:             {passed}"
    )

    print(
        f"Failed:             {failed}"
    )

    print(
        f"Pass rate:          "
        f"{pass_rate:.1f}%"
    )

    print()
    print("RETRIEVAL")
    print("-" * 50)

    print(
        f"Tests evaluated:    "
        f"{len(retrieval_results)}"
    )

    print(
        f"Average Precision:  "
        f"{avg_precision:.3f}"
    )

    print(
        f"Average Recall:     "
        f"{avg_recall:.3f}"
    )

    print()
    print("AUTHORIZATION")
    print("-" * 50)

    print(
        f"Security tests:     "
        f"{len(security_results)}"
    )

    print(
        f"Security passed:    "
        f"{security_passed}"
    )

    print(
        f"ACL leaks:          "
        f"{acl_leaks}"
    )

    print()
    print("ANSWERABILITY")
    print("-" * 50)

    print(
        f"Unanswerable tests: "
        f"{len(unanswerable_results)}"
    )

    print(
        f"Correct refusals:   "
        f"{correct_refusals}"
    )

    print()
    print(
        f"Report: {REPORT}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("WARDEN EVALUATION STARTING")
    print("=" * 70)

    print()
    print(
        f"Dataset: {DATASET}"
    )

    print(
        f"Warden:  {WARDEN_URL}"
    )

    # --------------------------------------------------------
    # Load tests
    # --------------------------------------------------------

    tests = load_tests()

    print()
    print(
        f"Loaded {len(tests)} "
        f"evaluation tests."
    )

    results = []

    # --------------------------------------------------------
    # Run tests
    # --------------------------------------------------------

    for index, test in enumerate(
        tests,
        start=1
    ):

        print()
        print("=" * 70)

        print(
            f'[{index}/{len(tests)}] '
            f'Running {test.get("id")}'
        )

        print(
            f'Question: '
            f'{test.get("question")}'
        )

        print(
            f'Clearance: '
            f'{get_clearance(test)}'
        )

        try:

            # =================================================
            # Ask Warden
            # =================================================

            response = run_test(
                test
            )

            print()
            print("WARDEN RESPONSE")
            print("-" * 70)

            print(
                json.dumps(
                    response,
                    indent=2
                )
            )

            # =================================================
            # Evaluate
            # =================================================

            result = evaluate(
                test,
                response
            )

            print_test_result(
                result
            )

        except Exception as e:

            print()
            print(
                f"ERROR: {e}"
            )

            result = (
                create_error_result(
                    test,
                    e
                )
            )

        results.append(
            result
        )

    # --------------------------------------------------------
    # CSV
    # --------------------------------------------------------

    write_report(
        results
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print_summary(
        results
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()