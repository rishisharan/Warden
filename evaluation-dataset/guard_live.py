"""One API call per case; consume private local evidence, never probe /search."""
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from guard_checks import validate_policy


def capture(manifest, url, directory, timeout=30):
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be an object")
    validate_policy(manifest.get("policy"))
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("cases must be an array")
    entries = []
    for case in cases:
        response = {}
        try:
            if not isinstance(case, dict) or case.get("userId") not in manifest["policy"]["users"]:
                raise ValueError("Unknown test identity")
            request = Request(url, json.dumps({"userId": case["userId"], "question": case["question"]}).encode(), {"Content-Type": "application/json"})
            with urlopen(request, timeout=timeout) as http:
                body = json.load(http)
                response = {key: body.get(key) for key in ("userId", "answer")}
                trace = http.headers.get("X-Trace-Id", "")
            # Never allow a server-supplied trace ID to select arbitrary paths.
            if str(uuid.UUID(trace)) != trace:
                raise ValueError("Invalid correlation ID")
            response["traceId"] = trace
            path = Path(directory) / (trace + ".json")
            deadline = time.monotonic() + 2
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            evidence = json.loads(path.read_text(encoding="utf-8"))
            response["evidence"] = evidence
            # Live mode requires decision coverage as well as Phase 1 fields.
            records = evidence.get("retrieved")
            decisions = evidence.get("authorizationDecisions")
            if not isinstance(records, list) or not isinstance(decisions, list) or len(records) != len(decisions):
                raise ValueError("Missing authorization observations")
            allowed = manifest["policy"]["users"][case["userId"]]
            for row, decision in zip(records, decisions):
                expected = "UNKNOWN" if row.get("accessLevel") not in ("public", "manager") else "ALLOW" if row["accessLevel"] in allowed else "DENY"
                if {k: decision.get(k) for k in ("documentId", "accessLevel")} != row or decision.get("decision") != expected:
                    raise ValueError("Inconsistent authorization observations")
        except Exception:
            # Retain known violations if other observations are incomplete.
            # Missing evidence stays missing. Never publish HTTP bodies/errors.
            if isinstance(response.get("evidence"), dict):
                response["evidence"]["retrievalComplete"] = False
        entries.append({"case": case, "response": response})
    return {"policy": manifest["policy"], "cases": entries}
