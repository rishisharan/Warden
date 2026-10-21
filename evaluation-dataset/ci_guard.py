"""Fail-closed CI orchestration. Raw diagnostics stay in a temporary directory.

Only explicitly rebuilt, schema-checked JSON/Markdown is publishable. This module
uses the standard library; dependency installation failures can still be reported.
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from guard_checks import evaluate_evidence

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
SUITES = ("java", "evaluator", "retrieval", "integration")
MINIMUM = {"java": 6, "evaluator": 56, "retrieval": 5, "integration": 4}
SCENARIOS = {
    "test_authorized_real_chain_controls": ("authorized-controls", 2, "PASS", 0),
    "test_concurrent_api_requests_keep_principals_separate": ("concurrent-controls", 4, "PASS", 0),
    "test_missing_flask_evidence_blocks_real_query": ("missing-evidence-acceptance", 1, "ERROR", 2),
    "test_mutant_context_leak_with_final_refusal_fails": ("context-leak-acceptance", 1, "FAIL", 1),
}
PUBLIC_DOC = "d4d85910fe5de0e43b6e10c0c8049fc199fd8ab4eda7509b5a6f3b63779d88fc"
RESTRICTED_DOC = "38f8b51b3aa7c5d7c8322ddf4e7e79541464e365f170cd330603b85c1395e6d2"


def integer(value):
    return type(value) is int and value >= 0


def suite_result(name, counts, exit_code):
    keys = ("discovered", "passed", "skipped", "failures", "errors")
    if name not in SUITES or not isinstance(counts, dict) or any(not integer(counts.get(k)) for k in keys):
        raise ValueError("Invalid suite counts")
    result = {"suite": name, **{k: counts[k] for k in keys}, "exitCode": exit_code}
    result["executed"] = result["discovered"] - result["skipped"]
    if result["passed"] + result["skipped"] + result["failures"] + result["errors"] != result["discovered"]:
        raise ValueError("Inconsistent suite counts")
    if type(exit_code) is not int:
        raise ValueError("Invalid exit code")
    return result


def java_counts(directory):
    totals = dict(discovered=0, passed=0, skipped=0, failures=0, errors=0)
    files = list(Path(directory).glob("TEST-*.xml"))
    if not files:
        raise ValueError("No fresh Java reports")
    for path in files:
        root = ET.parse(path).getroot()
        for key, xml_key in (("discovered", "tests"), ("skipped", "skipped"), ("failures", "failures"), ("errors", "errors")):
            totals[key] += int(root.attrib[xml_key])
    totals["passed"] = totals["discovered"] - totals["skipped"] - totals["failures"] - totals["errors"]
    return totals


def safe_evidence(evidence):
    if not isinstance(evidence, dict):
        raise ValueError("Missing evidence")
    request_id = evidence.get("requestId")
    if not isinstance(request_id, str) or str(uuid.UUID(request_id)) != request_id:
        raise ValueError("Invalid request identity")
    if evidence.get("userId") not in ("user-a", "user-b") or type(evidence.get("schemaVersion")) is not int or evidence["schemaVersion"] != 1:
        raise ValueError("Invalid evidence identity")
    result = {"schemaVersion": 1, "requestId": request_id, "userId": evidence["userId"]}
    for key in ("retrievalComplete", "modelContextComplete", "modelCalled"):
        if type(evidence.get(key)) is not bool:
            raise ValueError("Missing completion observation")
        result[key] = evidence[key]
    for key in ("retrieved", "modelContext", "authorizationDecisions"):
        if not isinstance(evidence.get(key), list):
            raise ValueError("Missing observation array")
        result[key] = []
        for record in evidence[key]:
            if not isinstance(record, dict) or record.get("documentId") not in (PUBLIC_DOC, RESTRICTED_DOC) or record.get("accessLevel") not in ("public", "manager"):
                raise ValueError("Unknown observation")
            row = {"documentId": record["documentId"], "accessLevel": record["accessLevel"]}
            if key == "authorizationDecisions":
                if record.get("decision") not in ("ALLOW", "DENY", "UNKNOWN"):
                    raise ValueError("Missing decision")
                row["decision"] = record["decision"]
            result[key].append(row)
    if len(result["retrieved"]) != len(result["authorizationDecisions"]):
        raise ValueError("Missing decision coverage")
    allowed = ("public",) if result["userId"] == "user-a" else ("public", "manager")
    for row, decision in zip(result["retrieved"], result["authorizationDecisions"]):
        if any(row[k] != decision[k] for k in ("documentId", "accessLevel")) or decision["decision"] != ("ALLOW" if row["accessLevel"] in allowed else "DENY"):
            raise ValueError("Inconsistent authorization decision")
    return result


def security_results(raw):
    """Only four explicitly named acceptance scenarios may expect nonzero verdicts."""
    if not isinstance(raw, list) or len(raw) != len(SCENARIOS):
        raise ValueError("Missing required acceptance scenarios")
    seen, traces, summaries = set(), set(), []
    for item in raw:
        if not isinstance(item, dict) or item.get("test") not in SCENARIOS or item["test"] in seen:
            raise ValueError("Unexpected acceptance scenario")
        seen.add(item["test"])
        label, count, expected, expected_exit = SCENARIOS[item["test"]]
        results, receipts = item.get("results"), item.get("evidence")
        if type(item.get("exitCode")) is not int or item["exitCode"] != expected_exit or not isinstance(results, list) or len(results) != count or not isinstance(receipts, list) or len(receipts) != count:
            raise ValueError("Incorrect acceptance coverage")
        clean = []
        for verdict, receipt in zip(results, receipts):
            if not isinstance(verdict, dict) or verdict.get("status") != expected:
                raise ValueError("Unexpected security verdict")
            evidence = safe_evidence(receipt)
            policy = {"schemaVersion": 1, "users": {"user-a": ["public"], "user-b": ["public", "manager"]},
                      "documents": {PUBLIC_DOC: "public", RESTRICTED_DOC: "manager"}}
            rescored = evaluate_evidence({"id": "ci-observation", "userId": evidence["userId"]},
                {"userId": evidence["userId"], "traceId": evidence["requestId"], "answer": "", "evidence": evidence}, policy)
            if rescored.status != expected:
                raise ValueError("Security verdict disagrees with independent policy")
            if expected != "ERROR" and rescored.errors:
                raise ValueError("Unexpected evidence error")
            if evidence["requestId"] in traces:
                raise ValueError("Reused request observation")
            traces.add(evidence["requestId"])
            if expected == "ERROR":
                if evidence["retrievalComplete"] or not evidence["modelContextComplete"] or not evidence["modelCalled"]:
                    raise ValueError("Wrong missing-evidence acceptance failure")
            elif not evidence["retrievalComplete"] or not evidence["modelContextComplete"] or verdict.get("errors") != []:
                raise ValueError("Incomplete security evidence")
            if expected == "PASS" and verdict.get("violations") != []:
                raise ValueError("Unexpected violation in positive control")
            if expected == "FAIL":
                if not evidence["modelCalled"]:
                    raise ValueError("Missing actual model invocation")
                violations = verdict.get("violations")
                if not isinstance(violations, list) or not any(isinstance(v, dict) and v.get("stage") == "modelContext" and v.get("documentId") == RESTRICTED_DOC for v in violations):
                    raise ValueError("Expected context violation was not detected")
                if not any(r["documentId"] == RESTRICTED_DOC for r in evidence["modelContext"]):
                    raise ValueError("Missing actual restricted context")
            clean.append({"observedVerdict": expected, "evidence": evidence})
        summaries.append({"scenario": label, "expectedVerdict": expected, "assertionPassed": True,
                          "executedCases": count, "observedExitCode": expected_exit, "cases": clean})
    return summaries


def assemble(suites, raw_security):
    reasons = set()
    if not isinstance(suites, list) or any(not isinstance(s, dict) or s.get("suite") not in SUITES for s in suites):
        return failure("invalid_report")
    names = [s.get("suite") for s in suites]
    if sorted(names) != sorted(SUITES):
        reasons.add("missing_suite_results")
    checked = []
    for suite in suites:
        try:
            clean = suite_result(suite["suite"], suite, suite["exitCode"])
            checked.append(clean)
            if clean["executed"] < MINIMUM[clean["suite"]]: reasons.add("zero_or_missing_tests")
            if clean["skipped"]: reasons.add("required_tests_skipped")
            if clean["exitCode"] or clean["failures"] or clean["errors"]: reasons.add("suite_failed")
        except (KeyError, TypeError, ValueError):
            reasons.add("invalid_report")
    try:
        security = security_results(raw_security)
    except (ValueError, TypeError, KeyError, AttributeError):
        security = []
        reasons.add("missing_security_evidence" if not raw_security else "unexpected_security_verdict")
    executed = sum(s["executedCases"] for s in security)
    if not executed: reasons.add("zero_or_missing_tests")
    return {"schemaVersion": 1, "status": "FAIL" if reasons else "PASS", "reasonCodes": sorted(reasons),
            "suites": checked, "executedSecurityCases": executed, "securityScenarios": security}


def failure(reason):
    return {"schemaVersion": 1, "status": "FAIL", "reasonCodes": [reason], "suites": [],
            "executedSecurityCases": 0, "securityScenarios": []}


def write_reports(directory, report):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# Warden Guard security gate", "", f"Status: **{report['status']}**", "",
             f"Executed security cases: {report['executedSecurityCases']}", "",
             "| Suite | Executed | Skipped | Failures | Errors | Exit |", "|---|---:|---:|---:|---:|---:|"]
    for suite in report["suites"]:
        lines.append(f"| {suite['suite']} | {suite['executed']} | {suite['skipped']} | {suite['failures']} | {suite['errors']} | {suite['exitCode']} |")
    lines += ["", "Expected negative verdicts count as successful assertions only in named acceptance scenarios."]
    for scenario in report["securityScenarios"]:
        lines.append(f"- {scenario['scenario']}: expected {scenario['expectedVerdict']}; assertion passed; {scenario['executedCases']} cases.")
    lines += ["", "Reason codes: " + (", ".join(report["reasonCodes"]) or "none"), "",
              "Scope: synthetic Spring/Flask/Chroma chain with recording Ollama stub; no real-provider or authenticated-identity certification."]
    (directory / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite): yield from flatten(test)
        else: yield test


def run_python_child(name, result_file):
    if name == "retrieval":
        suite = unittest.defaultTestLoader.discover(str(REPO / "warden-api/python-retrieval/tests"))
    else:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
        suite = unittest.TestSuite(test for test in flatten(suite) if
            (".EndToEndTests." in test.id()) == (name == "integration"))
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    counts = {"discovered": result.testsRun, "skipped": len(result.skipped), "failures": len(result.failures), "errors": len(result.errors)}
    counts["passed"] = counts["discovered"] - counts["skipped"] - counts["failures"] - counts["errors"]
    Path(result_file).write_text(json.dumps(counts), encoding="utf-8")
    return 0 if result.wasSuccessful() and counts["discovered"] > counts["skipped"] else 1


def run_command(command, log, env):
    # Never forward raw build/test diagnostics to public CI logs or artifacts.
    with Path(log).open("wb") as stream:
        try:
            return subprocess.run(command, cwd=REPO, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                  timeout=300, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0).returncode
        except (OSError, subprocess.TimeoutExpired):
            return 2


def run_ci(directory, maven_repo=None):
    write_reports(directory, failure("not_executed"))
    with tempfile.TemporaryDirectory(prefix="warden-ci-") as tmp:
        private = Path(tmp)
        env = os.environ.copy()
        env.update(PYTHONDONTWRITEBYTECODE="1", WARDEN_ENV_FILE=os.devnull, ANONYMIZED_TELEMETRY="False")
        # A stale receipt/result from an earlier run cannot satisfy this gate.
        env["WARDEN_TEST_REPORT_DIR"] = str(private / "integration")
        maven = shutil.which("mvn")
        command = [maven or "mvn", "-B", "-ntp", "-f", str(REPO / "warden-api/pom.xml"),
                   "-DfailIfNoTests=true", f"-Dguard.reportsDirectory={private / 'java'}", "package"]
        if maven_repo: command.insert(1, f"-Dmaven.repo.local={maven_repo}")
        java_exit = run_command(command, private / "java.log", env)
        suites = []
        try: suites.append(suite_result("java", java_counts(private / "java"), java_exit))
        except (ValueError, KeyError, OSError, ET.ParseError):
            suites.append(suite_result("java", dict(discovered=0, passed=0, skipped=0, failures=0, errors=0), java_exit or 2))
        for name in ("evaluator", "retrieval", "integration"):
            env["WARDEN_RUN_INTEGRATION"] = "1" if name == "integration" else "0"
            result_file = private / (name + ".json")
            code = run_command([sys.executable, "-B", str(Path(__file__).resolve()), "--suite-child", name,
                                "--child-result", str(result_file)], private / (name + ".log"), env)
            try:
                counts = json.loads(result_file.read_text(encoding="utf-8"))
                suites.append(suite_result(name, counts, code))
            except (ValueError, KeyError, TypeError, OSError):
                suites.append(suite_result(name, dict(discovered=0, passed=0, skipped=0, failures=0, errors=0), code or 2))
        try: raw = json.loads((private / "integration/integration.json").read_text(encoding="utf-8"))
        except (OSError, ValueError): raw = None
        report = assemble(suites, raw)
        write_reports(directory, report)
        print("Warden Guard gate: " + report["status"])
        return 0 if report["status"] == "PASS" else 1


def verify(directory, github_summary=False):
    try:
        report = json.loads((Path(directory) / "results.json").read_text(encoding="utf-8"))
        # Rebuild the publishable schema rather than echo arbitrary report text.
        raw = []
        by_label = {value[0]: key for key, value in SCENARIOS.items()}
        for scenario in report["securityScenarios"]:
            raw.append({"test": by_label[scenario["scenario"]], "exitCode": scenario["observedExitCode"],
                        "results": [{"status": case["observedVerdict"], "errors": [], "violations":
                            [{"stage": "modelContext", "documentId": RESTRICTED_DOC}] if case["observedVerdict"] == "FAIL" else []}
                            for case in scenario["cases"]], "evidence": [case["evidence"] for case in scenario["cases"]]})
        clean = assemble(report["suites"], raw)
        if report.get("status") != "PASS" or report.get("reasonCodes") != []:
            clean["status"] = "FAIL"
            clean["reasonCodes"] = sorted(set(clean["reasonCodes"]) | {"runner_error"})
        write_reports(directory, clean)
    except (OSError, ValueError, TypeError, KeyError):
        clean = failure("invalid_report")
        write_reports(directory, clean)
    if github_summary and os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write((Path(directory) / "summary.md").read_text(encoding="utf-8"))
    return 0 if clean["status"] == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synthetic Warden Guard CI gate")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--initialize", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--suite-child", choices=SUITES[1:])
    parser.add_argument("--report-dir", type=Path, default=Path("reports/security"))
    parser.add_argument("--child-result", type=Path)
    parser.add_argument("--maven-repo")
    parser.add_argument("--github-summary", action="store_true")
    args = parser.parse_args(argv)
    if args.suite_child:
        if not args.child_result: parser.error("child result is required")
        return run_python_child(args.suite_child, args.child_result)
    try:
        if args.initialize:
            write_reports(args.report_dir, failure("not_executed")); return 0
        if args.verify: return verify(args.report_dir, args.github_summary)
        return run_ci(args.report_dir, args.maven_repo)
    except Exception:
        try: write_reports(args.report_dir, failure("runner_error"))
        except OSError: print("Could not write sanitized security report.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
