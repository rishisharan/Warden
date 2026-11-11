"""Evaluate retrieval and access filtering for the synthetic Warden corpus."""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Source:
    collection: str
    filename: str
    access: str


@dataclass(frozen=True)
class Case:
    name: str
    question: str
    allowed: tuple[str, ...]
    expected: Source | None = None
    excluded: tuple[Source, ...] = ()
    empty: bool = False


PUBLIC_CASES = (
    Case(
        "public-policy",
        "In POL-5002, when should Brindle Quay Research open a duplicate invoice case?",
        ("public",),
        Source("policy_docs", "pol-5002-billing.md", "public"),
    ),
    Case(
        "public-slack",
        "In SLK-5064, what did the API team ask Dapple Ridge Labs to capture for the webhook retry case?",
        ("public",),
        Source("slack_messages", "slk-5064-api.md", "public"),
    ),
    Case(
        "public-ticket",
        "What is the next step in TCK-5241 for Aster Run Observatory's renewal entitlement sync?",
        ("public",),
        Source("support_tickets", "tck-5241-renewal.md", "public"),
    ),
)

RESTRICTED_SETS = (
    ("policy", "Who approves reopening the invoice replay workflow in POL-5001?",
     5001, "billing", "policy_docs"),
    ("slack", "What verification did the data owner propose in SLK-5124 for Dapple Ridge Labs?",
     5124, "data", "slack_messages"),
    ("ticket", "What is the recovery plan in TCK-5165 for Ember Harbor Analytics' OAuth connector?",
     5165, "integrations", "support_tickets"),
)


def build_cases():
    yield from PUBLIC_CASES
    for name, question, number, category, collection in RESTRICTED_SETS:
        sources = {
            kind: Source(kind, f"{prefix}-{number}-{category}.md", "manager")
            for kind, prefix in (
                ("policy_docs", "pol"),
                ("slack_messages", "slk"),
                ("support_tickets", "tck"),
            )
        }
        yield Case(f"manager-{name}-visible", question, ("public", "manager"), sources[collection])
        yield Case(f"manager-{name}-blocked", question, ("public",), excluded=tuple(sources.values()))
    yield Case("empty-access", PUBLIC_CASES[0].question, (), empty=True)
    yield Case("invalid-access", PUBLIC_CASES[0].question, ("unknown",), empty=True)


def search(url, case, top_k, timeout):
    payload = {"question": case.question, "allowedAccessLevels": case.allowed, "topK": top_k}
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)

    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        raise ValueError("expected a response object with a results array")
    sources = []
    for row in result["results"]:
        fields = ("sourceType", "sourceFile", "accessLevel")
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key] for key in fields):
            raise ValueError("a result is missing sourceType, sourceFile, or accessLevel")
        sources.append(Source(*(row[key] for key in fields)))
    return sources


def check_results(case, sources, top_k):
    failures = []
    if len(sources) > top_k:
        failures.append(f"returned more than {top_k} results")
    if case.empty and sources:
        failures.append("expected zero results")
    if any(source.access not in case.allowed for source in sources):
        failures.append("returned a result with an unauthorized access level")
    if case.expected and case.expected not in sources:
        failures.append(f"expected {case.expected.filename} in the top {top_k}")
    excluded = {(source.collection, source.filename) for source in case.excluded}
    if any((source.collection, source.filename) in excluded for source in sources):
        failures.append("returned a restricted source from the linked document set")
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("WARDEN_RETRIEVAL_URL", "http://localhost:8011/search"))
    parser.add_argument("--top-k", type=int, default=os.getenv("WARDEN_EVAL_TOP_K", "5"))
    parser.add_argument("--timeout", type=float, default=os.getenv("WARDEN_EVAL_TIMEOUT", "30"))
    args = parser.parse_args(argv)
    if not 1 <= args.top_k <= 50 or not 0 < args.timeout < float("inf"):
        parser.error("--top-k must be between 1 and 50 and --timeout must be finite and positive")

    cases = list(build_cases())
    passed = 0
    for case in cases:
        try:
            sources = search(args.url, case, args.top_k, args.timeout)
        except (URLError, TimeoutError, ValueError) as error:
            print(f"ERROR {case.name}: {error}", file=sys.stderr)
            return 2

        failures = check_results(case, sources, args.top_k)
        if failures:
            print(f"FAIL {case.name}: {', '.join(failures)}")
        else:
            print(f"PASS {case.name} ({len(sources)} results)")
            passed += 1
    print(f"{passed}/{len(cases)} cases passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())

