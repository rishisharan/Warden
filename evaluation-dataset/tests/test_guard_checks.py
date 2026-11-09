"""Offline synthetic regression tests. No API, model, or vector store needed."""
import contextlib
import copy
import io
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import evaluation_set_2 as runner
from guard_checks import evaluate_evidence, evaluate_suite


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / "fixtures" / "guard_phase1.json").read_text(encoding="utf-8"))
        self.policy = self.fixture["policy"]
        self.case = self.fixture["cases"][0]["case"]
        self.response = self.fixture["cases"][0]["response"]
        self.evidence = self.response["evidence"]
        self.network = patch.object(socket, "socket", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def score(self):
        return evaluate_evidence(self.case, self.response, self.policy)

    def test_primary_unauthorized_llm_context_fails_despite_final_refusal(self):
        entry = self.fixture["cases"][1]
        result = evaluate_evidence(entry["case"], entry["response"], self.policy)
        self.assertIn("don't have authorized information", entry["response"]["answer"])
        self.assertEqual(result.status, "FAIL")
        self.assertEqual({v["stage"] for v in result.violations}, {"retrieved", "modelContext"})
        self.assertTrue(any(v["documentId"] == "doc-synthetic-salary" for v in result.violations))

    def test_allowed_public_and_manager_controls_pass(self):
        for index in (0, 2):
            entry = self.fixture["cases"][index]
            self.assertEqual(evaluate_evidence(entry["case"], entry["response"], self.policy).status, "PASS")

    def test_answer_wording_does_not_change_security_verdict(self):
        for answer in ("I refuse", "A synthetic answer", ""):
            self.response["answer"] = answer
            self.assertEqual(self.score().status, "PASS")

    def test_missing_evidence_cannot_pass_even_with_safe_citations(self):
        del self.response["evidence"]
        self.response["citedSources"] = [{"sourceFile": "public.md"}]
        self.assertEqual(self.score().status, "ERROR")

    def test_required_evidence_fields_cannot_default_to_success(self):
        original = copy.deepcopy(self.evidence)
        for field in original:
            with self.subTest(field=field):
                self.response["evidence"] = {k: v for k, v in original.items() if k != field}
                self.assertEqual(self.score().status, "ERROR")

    def test_unknown_and_missing_users_are_errors(self):
        for value in (None, "", "manager-a", "unknown", [], True):
            with self.subTest(user=value):
                self.case["userId"] = value
                self.assertEqual(self.score().status, "ERROR")

    def test_identity_and_request_correlation_must_match(self):
        for target, field, value in ((self.response, "userId", "user-b"), (self.evidence, "userId", "user-b"), (self.evidence, "requestId", "other-request")):
            with self.subTest(field=field):
                original = target[field]
                target[field] = value
                self.assertEqual(self.score().status, "ERROR")
                target[field] = original

    def test_incomplete_and_wrongly_typed_evidence_is_rejected(self):
        for field, value in (("retrievalComplete", False), ("modelContextComplete", 1), ("modelCalled", "yes"), ("schemaVersion", True), ("retrieved", None), ("modelContext", {})):
            with self.subTest(field=field):
                original = self.evidence[field]
                self.evidence[field] = value
                self.assertEqual(self.score().status, "ERROR")
                self.evidence[field] = original

    def test_missing_unknown_and_malformed_document_metadata_is_rejected(self):
        for record in ({}, {"documentId": "unknown", "accessLevel": "public"}, {"documentId": "doc-public-guide"}, {"documentId": "doc-public-guide", "accessLevel": "ADMIN"}, {"documentId": [], "accessLevel": "public"}, None):
            with self.subTest(record=record):
                self.evidence["retrieved"] = [record]
                self.assertEqual(self.score().status, "ERROR")

    def test_independent_policy_catches_relabelled_restricted_document(self):
        self.evidence["modelContext"] = [{"documentId": "doc-synthetic-salary", "accessLevel": "public"}]
        result = self.score()
        self.assertEqual(result.status, "FAIL")
        self.assertTrue(result.errors)
        self.assertEqual(result.violations[0]["expectedAccessLevel"], "manager")

    def test_retrieval_leak_fails_even_if_not_sent_to_model(self):
        self.evidence["retrieved"].append({"documentId": "doc-synthetic-salary", "accessLevel": "manager"})
        result = self.score()
        self.assertEqual(result.status, "FAIL")
        self.assertEqual([v["stage"] for v in result.violations], ["retrieved"])

    def test_model_only_leak_is_still_failure_with_provenance_error(self):
        self.evidence["modelContext"].append({"documentId": "doc-synthetic-salary", "accessLevel": "manager"})
        self.assertEqual(self.score().status, "FAIL")
        self.assertTrue(self.score().errors)

    def test_explicit_forbidden_document_overrides_otherwise_allowed_policy(self):
        self.case["forbiddenDocumentIds"] = ["doc-public-guide"]
        self.assertEqual(self.score().status, "FAIL")

    def test_empty_completed_retrieval_and_no_model_call_is_valid(self):
        self.evidence.update(retrieved=[], modelContext=[], modelCalled=False)
        self.assertEqual(self.score().status, "PASS")

    def test_context_with_no_model_call_is_inconsistent(self):
        self.evidence["modelCalled"] = False
        self.assertEqual(self.score().status, "ERROR")

    def test_malformed_policy_cannot_pass(self):
        for policy in (None, {}, {"schemaVersion": 1, "users": {}, "documents": {}}, {"schemaVersion": 1, "users": {"a": ["ADMIN"]}, "documents": {"d": "public"}}):
            with self.subTest(policy=policy):
                with self.assertRaises(ValueError):
                    evaluate_evidence(self.case, self.response, policy)

    def test_duplicate_and_zero_cases_block_success(self):
        self.fixture["cases"] = []
        self.assertEqual(evaluate_suite(self.fixture), ([], 2))
        self.fixture["cases"] = [{"case": self.case, "response": self.response}] * 2
        self.assertEqual(evaluate_suite(self.fixture)[1], 2)

    def test_suite_exit_codes_for_pass_fail_error(self):
        for index, expected in ((0, 0), (1, 1)):
            payload = {"policy": self.policy, "cases": [self.fixture["cases"][index]]}
            self.assertEqual(evaluate_suite(payload)[1], expected)
        self.response.pop("evidence")
        self.assertEqual(evaluate_suite({"policy": self.policy, "cases": [{"case": self.case, "response": self.response}]})[1], 2)

    def test_same_request_evidence_cannot_be_reused_to_inflate_test_count(self):
        first = self.fixture["cases"][0]
        second = copy.deepcopy(first)
        second["case"]["id"] = "different-case"
        results, code = evaluate_suite({"policy": self.policy, "cases": [first, second]})
        self.assertEqual(code, 2)
        self.assertEqual(results[1].status, "ERROR")

    def test_cli_reports_expected_failure_without_raw_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                code = runner.main(["--guard-evidence", str(ROOT / "fixtures" / "guard_phase1.json"), "--report-dir", tmp])
            report_text = (Path(tmp) / "results.json").read_text(encoding="utf-8")
            report = json.loads(report_text)
            self.assertEqual(code, 1)
            self.assertEqual(report["summary"]["executedCases"], 3)
            self.assertEqual(report["summary"]["failedCases"], 1)
            self.assertNotIn("I don't have authorized information", report_text)
            self.assertTrue((Path(tmp) / "summary.md").exists())

    def test_missing_file_malformed_json_and_empty_suite_generate_error_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            empty = root / "empty.json"
            empty.write_text(json.dumps({"policy": self.policy, "cases": []}), encoding="utf-8")
            for source in (root / "missing.json", bad, empty):
                with self.subTest(source=source), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.main(["--guard-evidence", str(source), "--report-dir", str(root / "reports")]), 2)
                    report = json.loads((root / "reports" / "results.json").read_text(encoding="utf-8"))
                    self.assertEqual(report["summary"]["exitCode"], 2)

    def test_no_arguments_cannot_silently_run_quality_as_security(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            runner.main([])
        self.assertEqual(raised.exception.code, 2)

    def test_legacy_zero_skipped_or_failed_cases_cannot_succeed(self):
        passed = SimpleNamespace(passed=True, skipped=False)
        skipped = SimpleNamespace(passed=False, skipped=True)
        for results in ([], [skipped], [passed, skipped], [SimpleNamespace(passed=False, skipped=False)]):
            self.assertNotEqual(runner.legacy_exit_code(results), 0)
        self.assertEqual(runner.legacy_exit_code([passed]), 0)

    def test_legacy_manager_mapping_matches_local_java(self):
        self.assertEqual(runner.USER_ACCESS["user-b"], ["public", "manager"])
        self.assertNotIn("manager-a", runner.USER_ACCESS)
        with self.assertRaises(ValueError):
            runner.evaluate_case(runner.EvalCase("bad", "authorization", "unknown", "demo"))

    def test_guard_mode_never_calls_live_retrieval_or_application(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "post_json", side_effect=AssertionError("no live requests")) as http, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(["--guard-evidence", str(ROOT / "fixtures" / "guard_phase1.json"), "--report-dir", tmp]), 1)
            http.assert_not_called()

    def test_legacy_quality_positive_case_still_works(self):
        case = runner.EvalCase("quality", "positive", "user-b", "demo", expected_source="demo.md")
        with patch.object(runner, "retrieve", return_value=([{"sourceFile": "demo.md", "accessLevel": "manager"}], 1)), patch.object(runner, "ask_warden", return_value=({"answer": "Synthetic answer (Source 1)", "citedSources": [{"sourceFile": "demo.md"}]}, 1)):
            self.assertTrue(runner.evaluate_case(case).passed)

    def test_duplicate_json_keys_block_cli_success(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            source = Path(tmp) / "duplicate.json"
            source.write_text('{"policy": {}, "policy": {}, "cases": []}', encoding="utf-8")
            self.assertEqual(runner.main(["--guard-evidence", str(source), "--report-dir", str(Path(tmp) / "reports")]), 2)

    def test_legacy_fixture_errors_are_not_silently_skipped(self):
        case = runner.EvalCase("fixture", "authorization", "user-a", "demo", expected_source="demo.md", requires_fixture=True)
        with patch.object(runner, "retrieve", side_effect=TimeoutError("offline test timeout")):
            with self.assertRaises(TimeoutError):
                runner.fixture_available(case)

    def test_process_exit_code_matches_acceptance_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run([sys.executable, str(ROOT / "evaluation_set_2.py"), "--guard-evidence", str(ROOT / "fixtures" / "guard_phase1.json"), "--report-dir", tmp], capture_output=True, text=True, timeout=15)
            self.assertEqual(completed.returncode, 1, completed.stderr)


if __name__ == "__main__":
    unittest.main()
