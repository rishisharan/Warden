import json
import csv
import requests
from pathlib import Path

DATASET = Path("../evaluation-dataset/retrieval_eval_50.jsonl")
REPORT = Path("evaluation_report.csv")

WARDEN_URL = "http://localhost:8082/api/query"

USER_MAP = {
    "PUBLIC": "user-a",
    "MANAGER": "user-b"
}


def load_tests():
    tests = []

    with DATASET.open("r", encoding="utf-8") as file:
        for line in file:
            tests.append(json.loads(line))

    return tests


def run_test(test):

    user_id = USER_MAP[test["clearance"]]

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


def evaluate(test, response):

    actual_sources = [
        source["sourceFile"]
        for source in response.get("citedSources", [])
    ]

    expected_sources = test["expectedSources"]
    forbidden_sources = test["mustNotRetrieve"]

    # Did we retrieve at least one expected document?
    source_hit = (
        True
        if not expected_sources
        else any(
            source in actual_sources
            for source in expected_sources
        )
    )

    # Did we accidentally expose something forbidden?
    acl_leak = any(
        source in actual_sources
        for source in forbidden_sources
    )

    answer = response.get("answer", "")

    expected_terms = test["expectedAnswerContains"]

    answer_contains_expected = (
        True
        if not expected_terms
        else all(
            term.lower() in answer.lower()
            for term in expected_terms
        )
    )

    expected_should_answer = test["shouldAnswer"]

    refused = (
        "don't have authorized information"
        in answer.lower()
    )

    answer_behavior_correct = (
        not refused
        if expected_should_answer
        else refused
    )

    passed = (
        source_hit
        and not acl_leak
        and answer_contains_expected
        and answer_behavior_correct
    )

    return {
        "id": test["id"],
        "clearance": test["clearance"],
        "question": test["question"],
        "expected_sources": "|".join(expected_sources),
        "actual_sources": "|".join(actual_sources),
        "source_hit": source_hit,
        "acl_leak": acl_leak,
        "answer_contains_expected": answer_contains_expected,
        "answer_behavior_correct": answer_behavior_correct,
        "passed": passed,
        "answer": answer
    }


def main():

    tests = load_tests()

    results = []

    for test in tests:

        print(
            f'Running {test["id"]}: '
            f'{test["question"]}'
        )

        try:

            response = run_test(test)

            print("\nTEST:")
            print(json.dumps(test, indent=2))

            print("\nACTUAL RESPONSE:")
            print(json.dumps(response, indent=2))

            result = evaluate(test, response)

            print("\nEVALUATION:")
            print(json.dumps(result, indent=2))

            result = evaluate(
                test,
                response
            )

        except Exception as e:

            result = {
                "id": test["id"],
                "clearance": test["clearance"],
                "question": test["question"],
                "expected_sources": "",
                "actual_sources": "",
                "source_hit": False,
                "acl_leak": False,
                "answer_contains_expected": False,
                "answer_behavior_correct": False,
                "passed": False,
                "answer": f"ERROR: {e}"
            }

        results.append(result)

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
        writer.writerows(results)

    passed = sum(
        1 for result in results
        if result["passed"]
    )

    acl_leaks = sum(
        1 for result in results
        if result["acl_leak"]
    )

    print()
    print("==============================")
    print("WARDEN EVALUATION")
    print("==============================")

    print(f"Tests:       {len(results)}")
    print(f"Passed:      {passed}")
    print(f"Failed:      {len(results) - passed}")
    print(
        f"Pass rate:   "
        f"{passed / len(results) * 100:.1f}%"
    )
    print(f"ACL leaks:   {acl_leaks}")

    print()
    print(f"Report written to: {REPORT}")


if __name__ == "__main__":
    main()