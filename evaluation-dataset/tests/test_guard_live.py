import copy
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from guard_live import capture
from guard_checks import evaluate_suite


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "fixtures/guard_phase2.json").read_text())
        self.manifest["cases"] = self.manifest["cases"][:1]
        self.trace = str(uuid.uuid4())
        self.doc = next(iter(self.manifest["policy"]["documents"]))
        self.row = {"documentId": self.doc, "accessLevel": "public"}
        self.evidence = {"schemaVersion": 1, "requestId": self.trace, "userId": "user-a", "retrievalComplete": True,
            "modelContextComplete": True, "modelCalled": True, "retrieved": [self.row], "modelContext": [self.row],
            "authorizationDecisions": [dict(self.row, decision="ALLOW")]}

    def run_capture(self, directory):
        body = BytesIO(json.dumps({"userId": "user-a", "answer": "SYNTHETIC_REFUSAL"}).encode())
        body.headers = {"X-Trace-Id": self.trace}
        with patch("guard_live.urlopen", return_value=body) as http:
            result = capture(self.manifest, "http://127.0.0.1/api/query", directory)
            self.assertEqual(http.call_count, 1)
            return evaluate_suite(result)

    def test_successful_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / (self.trace + ".json")).write_text(json.dumps(self.evidence))
            self.assertEqual(self.run_capture(tmp)[1], 0)

    def test_missing_evidence_blocks(self):
        with tempfile.TemporaryDirectory() as tmp, patch("guard_live.time.monotonic", side_effect=[0, 3]):
            self.assertEqual(self.run_capture(tmp)[1], 2)

    def test_missing_decisions_and_correlation_block(self):
        for field in ("authorizationDecisions", "requestId", "retrievalComplete"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                evidence = copy.deepcopy(self.evidence)
                del evidence[field]
                (Path(tmp) / (self.trace + ".json")).write_text(json.dumps(evidence))
                self.assertEqual(self.run_capture(tmp)[1], 2)

    def test_live_context_leak_fails_despite_refusal(self):
        forbidden = list(self.manifest["policy"]["documents"])[1]
        row = {"documentId": forbidden, "accessLevel": "manager"}
        self.evidence.update(retrieved=[row], modelContext=[row], authorizationDecisions=[dict(row, decision="DENY")])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / (self.trace + ".json")).write_text(json.dumps(self.evidence))
            results, code = self.run_capture(tmp)
            self.assertEqual(code, 1)
            self.assertEqual(results[0].status, "FAIL")


if __name__ == "__main__":
    unittest.main()
