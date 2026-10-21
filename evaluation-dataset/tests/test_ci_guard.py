"""Regression tests for CI false greens and publishable report privacy."""
import copy
import contextlib
import io
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ci_guard as ci


def good_suites():
    return [ci.suite_result(name, dict(discovered=n, passed=n, skipped=0, failures=0, errors=0), 0)
            for name, n in ci.MINIMUM.items()]


def good_security():
    raw = []
    for method, (_, count, expected, exit_code) in ci.SCENARIOS.items():
        item = {"test": method, "exitCode": exit_code, "results": [], "evidence": []}
        for index in range(count):
            restricted = expected == "FAIL" or (expected == "PASS" and index % 2 == 1)
            user = "user-a" if expected != "PASS" or not restricted else "user-b"
            row = {"documentId": ci.RESTRICTED_DOC if restricted else ci.PUBLIC_DOC,
                   "accessLevel": "manager" if restricted else "public"}
            evidence = {"schemaVersion": 1, "requestId": str(uuid.uuid4()), "userId": user,
                        "retrievalComplete": expected != "ERROR", "modelContextComplete": True,
                        "modelCalled": True, "retrieved": [row], "modelContext": [row],
                        "authorizationDecisions": [dict(row, decision="DENY" if expected == "FAIL" else "ALLOW")]}
            item["evidence"].append(evidence)
            item["results"].append({"status": expected, "errors": ["incomplete"] if expected == "ERROR" else [],
                                    "violations": [{"stage": "modelContext", "documentId": ci.RESTRICTED_DOC}] if expected == "FAIL" else []})
        raw.append(item)
    return raw


class CIGateTests(unittest.TestCase):
    def setUp(self):
        self.suites = good_suites()
        self.raw = good_security()

    def test_expected_negative_results_are_successful_assertions(self):
        report = ci.assemble(self.suites, self.raw)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["executedSecurityCases"], 8)
        self.assertEqual({s["expectedVerdict"] for s in report["securityScenarios"]}, {"PASS", "FAIL", "ERROR"})

    def test_zero_executed_tests_fail_each_suite(self):
        for index in range(4):
            with self.subTest(index=index):
                suites = good_suites()
                suites[index] = ci.suite_result(suites[index]["suite"], dict(discovered=0, passed=0, skipped=0, failures=0, errors=0), 0)
                self.assertEqual(ci.assemble(suites, self.raw)["status"], "FAIL")

    def test_skipped_integration_is_not_live_coverage(self):
        self.suites[-1] = ci.suite_result("integration", dict(discovered=4, passed=0, skipped=4, failures=0, errors=0), 0)
        self.assertIn("required_tests_skipped", ci.assemble(self.suites, self.raw)["reasonCodes"])

    def test_nonzero_suite_exit_cannot_be_excused_as_expected_negative(self):
        self.suites[-1]["exitCode"] = 1
        self.assertEqual(ci.assemble(self.suites, self.raw)["status"], "FAIL")

    def test_suite_failure_and_error_counts_override_zero_exit(self):
        for key in ("failures", "errors"):
            with self.subTest(key=key):
                suites = good_suites()
                suites[0]["passed"] -= 1
                suites[0][key] = 1
                self.assertEqual(ci.assemble(suites, self.raw)["status"], "FAIL")

    def test_missing_security_cases_or_scenarios_block(self):
        for raw in (None, [], self.raw[:-1]):
            with self.subTest(raw=bool(raw)):
                self.assertEqual(ci.assemble(self.suites, raw)["status"], "FAIL")

    def test_missing_or_duplicate_suite_blocks(self):
        for suites in (self.suites[:-1], self.suites + [self.suites[0]]):
            self.assertEqual(ci.assemble(suites, self.raw)["status"], "FAIL")

    def test_missing_receipt_is_not_expected_missing_evidence_assertion(self):
        negative = next(r for r in self.raw if r["test"] == "test_missing_flask_evidence_blocks_real_query")
        negative["evidence"] = [None]
        self.assertEqual(ci.assemble(self.suites, self.raw)["status"], "FAIL")

    def test_unexpected_violation_in_positive_control_fails(self):
        self.raw[0]["results"][0]["status"] = "FAIL"
        self.assertEqual(ci.assemble(self.suites, self.raw)["status"], "FAIL")

    def test_independent_policy_catches_falsely_claimed_pass(self):
        for key in ("retrieved", "modelContext"):
            self.raw[0]["evidence"][0][key] = [{"documentId": ci.RESTRICTED_DOC, "accessLevel": "public"}]
        self.assertEqual(ci.assemble(self.suites, self.raw)["status"], "FAIL")

    def test_primary_negative_requires_actual_context_violation(self):
        negative = next(r for r in self.raw if r["test"] == "test_mutant_context_leak_with_final_refusal_fails")
        negative["results"][0]["violations"] = []
        self.assertEqual(ci.assemble(self.suites, self.raw)["status"], "FAIL")

    def test_reused_request_ids_block(self):
        self.raw[0]["evidence"][1]["requestId"] = self.raw[0]["evidence"][0]["requestId"]
        self.assertEqual(ci.assemble(self.suites, self.raw)["status"], "FAIL")

    def test_missing_or_incorrect_authorization_decisions_block(self):
        for decisions in ([], [{"documentId": ci.PUBLIC_DOC, "accessLevel": "public", "decision": "DENY"}]):
            raw = copy.deepcopy(self.raw)
            raw[0]["evidence"][0]["authorizationDecisions"] = decisions
            self.assertEqual(ci.assemble(self.suites, raw)["status"], "FAIL")

    def test_context_acceptance_requires_model_invocation(self):
        negative = next(r for r in self.raw if r["test"] == "test_mutant_context_leak_with_final_refusal_fails")
        negative["evidence"][0]["modelCalled"] = False
        self.assertEqual(ci.assemble(self.suites, self.raw)["status"], "FAIL")

    def test_report_write_failure_exits_nonzero_without_sensitive_exception(self):
        with patch.object(ci, "write_reports", side_effect=PermissionError("SECRET_SENTINEL")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ci.main(["--initialize"]), 1)
            self.assertNotIn("SECRET_SENTINEL", output.getvalue())

    def test_sanitizer_drops_prompts_answers_content_paths_and_arbitrary_errors(self):
        secret = "SECRET_SENTINEL private-path api-key prompt answer document-content"
        self.raw[0]["prompt"] = secret
        self.raw[0]["results"][0]["answer"] = secret
        self.raw[0]["evidence"][0]["sourceContent"] = secret
        self.raw[0]["evidence"][0]["retrieved"][0]["sourcePath"] = secret
        self.suites[0]["stdout"] = secret
        report = ci.assemble(self.suites, self.raw)
        self.assertEqual(report["status"], "PASS")
        with tempfile.TemporaryDirectory() as tmp:
            ci.write_reports(tmp, report)
            self.assertNotIn(secret, (Path(tmp) / "results.json").read_text())
            self.assertNotIn(secret, (Path(tmp) / "summary.md").read_text())

    def test_invalid_id_cannot_be_published(self):
        self.raw[0]["evidence"][0]["requestId"] = "SECRET_SENTINEL"
        report = ci.assemble(self.suites, self.raw)
        self.assertEqual(report["status"], "FAIL")
        self.assertNotIn("SECRET_SENTINEL", json.dumps(report))

    def test_initial_report_cannot_pass_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ci.main(["--initialize", "--report-dir", tmp]), 0)
            self.assertEqual(ci.verify(tmp), 1)

    def test_valid_report_verifies_and_emits_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            ci.write_reports(tmp, ci.assemble(self.suites, self.raw))
            self.assertEqual(ci.verify(tmp), 0)
            self.assertIn("expected FAIL; assertion passed", (Path(tmp) / "summary.md").read_text())

    def test_corrupt_or_missing_report_fails_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ci.verify(tmp), 1)
            (Path(tmp) / "results.json").write_text('{bad-json SECRET_SENTINEL')
            self.assertEqual(ci.verify(tmp), 1)
            self.assertNotIn("SECRET_SENTINEL", (Path(tmp) / "results.json").read_text())

    def test_fresh_java_report_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): ci.java_counts(tmp)
            (Path(tmp) / "TEST-synthetic.xml").write_text('<testsuite tests="6" failures="0" errors="0" skipped="0"/>')
            self.assertEqual(ci.java_counts(tmp)["passed"], 6)

    def test_inconsistent_and_boolean_counts_are_rejected(self):
        for counts in (dict(discovered=6, passed=0, skipped=0, failures=0, errors=0),
                       dict(discovered=True, passed=1, skipped=0, failures=0, errors=0)):
            with self.assertRaises(ValueError): ci.suite_result("java", counts, 0)

    def test_missing_child_results_cannot_make_gate_green(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ci, "run_command", return_value=0), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ci.run_ci(tmp), 1)
            self.assertEqual(json.loads((Path(tmp) / "results.json").read_text())["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
