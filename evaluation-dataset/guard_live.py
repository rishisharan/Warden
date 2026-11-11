"""One API call per case; consume private local evidence, never probe /search."""
import json
import os
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, urlunsplit
import time
import uuid
from pathlib import Path
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from guard_checks import validate_policy


def authenticated_query(url, user_id, question, timeout, password=None):
    """Authenticate to Warden and submit the question with a fresh CSRF token."""
    if password is None:
        password = os.getenv({"user-a": "WARDEN_EVAL_REP_PASSWORD",
                              "user-b": "WARDEN_EVAL_MANAGER_PASSWORD"}[user_id])
    if not password:
        raise ValueError("Configure the evaluation account password")
    parts = urlsplit(url)
    api = urlunsplit((parts.scheme, parts.netloc, parts.path.rsplit("/", 1)[0], "", ""))
    session = build_opener(HTTPCookieProcessor(CookieJar()))

    def csrf():
        with session.open(api + "/csrf", timeout=timeout) as response:
            token = json.load(response)
        return {token["headerName"]: token["token"]}

    login = Request(api + "/login", urlencode({"username": user_id, "password": password}).encode(),
                    csrf())
    with session.open(login, timeout=timeout) as response:
        if response.status != 204:
            raise ValueError("Warden login did not succeed")
    headers = {**csrf(), "Content-Type": "application/json"}
    request = Request(url, json.dumps({"question": question}).encode(), headers)
    return session.open(request, timeout=timeout)


def capture(manifest, url, directory, timeout=30, query=None):
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
            try:
                request_result = (urlopen(request, timeout=timeout) if query is None
                                  else query(url, case["userId"], case["question"], timeout))
                with request_result as http:
                    body = json.load(http)
                    response = {key: body.get(key) for key in ("userId", "answer")}
                    trace = http.headers.get("X-Trace-Id", "")
            except HTTPError as error:
                with error:
                    if error.code != 502:
                        raise
                    # A rejected upstream result still has a Guard receipt and no answer.
                    trace = error.headers.get("X-Trace-Id", "")
                    response = {"userId": case["userId"], "answer": "", "httpStatus": 502}
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
