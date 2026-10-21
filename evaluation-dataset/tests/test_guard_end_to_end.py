"""Opt-in live local chain. Build the Java jar and install retrieval test deps first."""
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from guard_live import capture
from guard_checks import evaluate_suite


@unittest.skipUnless(os.getenv("WARDEN_RUN_INTEGRATION") == "1", "opt-in live Spring/Flask/Chroma integration")
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server
        path = ROOT.parent / "warden-api/python-retrieval/tests/test_guard_instrumentation.py"
        spec = importlib.util.spec_from_file_location("synthetic_retrieval", path)
        cls.fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.fixture)
        cls.store = cls.fixture.synthetic_store()
        cls.fixture.service.vector_stores = {"policy_docs": cls.store}
        cls.previous_guard = os.environ.get("WARDEN_GUARD_ENABLED")
        os.environ["WARDEN_GUARD_ENABLED"] = "true"
        cls.addClassCleanup(cls.restore_environment)
        cls.flask = make_server("127.0.0.1", 0, cls.fixture.service.app, threaded=True)
        cls.addClassCleanup(cls.flask.server_close)
        cls.prompts = {}
        cls.lock = threading.Lock()

        from flask import Flask, request, jsonify
        model = Flask("recording-ollama")
        @model.post("/api/chat")
        def ollama():
            with cls.lock:
                cls.prompts[request.headers.get("X-Trace-Id")] = request.get_json()
            return jsonify({"message": {"content": "I don't have authorized information to answer that question."}})
        cls.ollama = make_server("127.0.0.1", 0, model, threaded=True)
        cls.addClassCleanup(cls.ollama.server_close)
        cls.threads = [threading.Thread(target=cls.flask.serve_forever, daemon=True), threading.Thread(target=cls.ollama.serve_forever, daemon=True)]
        for thread in cls.threads: thread.start()
        cls.addClassCleanup(cls.flask.shutdown)
        cls.addClassCleanup(cls.ollama.shutdown)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.directory = Path(cls.tmp.name)
        cls.log = (cls.directory / "java.log").open("wb")
        cls.addClassCleanup(cls.log.close)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        cls.url = f"http://127.0.0.1:{port}/api/query"
        java = os.getenv("WARDEN_TEST_JAVA", "java")
        jar = ROOT.parent / "warden-api/target/warden-api.jar"
        cls.process = subprocess.Popen([java, "-jar", str(jar), f"--server.port={port}", "--server.address=127.0.0.1",
            "--app.warden.guard.enabled=true", f"--app.warden.guard.evidence-dir={cls.directory}",
            f"--app.warden.retrieval-base-url=http://127.0.0.1:{cls.flask.server_port}",
            f"--app.ollama.base-url=http://127.0.0.1:{cls.ollama.server_port}"], stdout=cls.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        cls.addClassCleanup(cls.stop_process)
        cls.reports = []
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/users", timeout=1): break
            except Exception:
                if cls.process.poll() is not None: raise RuntimeError("Synthetic Spring process failed; inspect temporary Java log")
                time.sleep(.1)
        else: raise RuntimeError("Synthetic Spring startup timed out")

    @classmethod
    def tearDownClass(cls):
        cls.stop_process()
        try:
            text = (cls.directory / "java.log").read_text(encoding="utf-8", errors="replace")
            if "SECRET_SENTINEL" in text or "PUBLIC_SENTINEL" in text:
                raise AssertionError("Raw document data reached application logs")
        finally:
            output = os.getenv("WARDEN_TEST_REPORT_DIR")
            if output:
                Path(output).mkdir(parents=True, exist_ok=True)
                (Path(output) / "integration.json").write_text(json.dumps(cls.reports, indent=2), encoding="utf-8")

    @classmethod
    def stop_process(cls):
        if cls.process.poll() is None:
            cls.process.terminate()
            try: cls.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.process.kill(); cls.process.wait(timeout=5)

    @classmethod
    def restore_environment(cls):
        if cls.previous_guard is None: os.environ.pop("WARDEN_GUARD_ENABLED", None)
        else: os.environ["WARDEN_GUARD_ENABLED"] = cls.previous_guard

    def setUp(self):
        self.store.unsafe = False
        os.environ["WARDEN_GUARD_ENABLED"] = "true"
        self.manifest = json.loads((ROOT / "fixtures/guard_phase2.json").read_text())

    def check(self, manifest):
        payload = capture(manifest, self.url, self.directory)
        results, code = evaluate_suite(payload)
        self.reports.append({"test": self._testMethodName, "exitCode": code,
            "results": [asdict(r) for r in results],
            "evidence": [entry["response"].get("evidence") for entry in payload["cases"]]})
        for entry in payload["cases"]:
            response = entry["response"]
            if "evidence" in response:
                trace = response["traceId"]
                evidence = response["evidence"]
                self.assertEqual(trace, evidence["requestId"])
                if evidence["modelCalled"]: self.assertIn(trace, self.prompts)
                self.assertNotIn("SECRET_SENTINEL", json.dumps(evidence))
        return payload, results, code

    def test_authorized_real_chain_controls(self):
        _, results, code = self.check(self.manifest)
        self.assertEqual(code, 0)
        self.assertTrue(all(r.status == "PASS" for r in results))

    def test_mutant_context_leak_with_final_refusal_fails(self):
        self.store.unsafe = True
        self.manifest["cases"] = [{"id": "mutant-context-leak", "userId": "user-a", "question": "synthetic salary"}]
        payload, results, code = self.check(self.manifest)
        response = payload["cases"][0]["response"]
        self.assertIn("don't have authorized information", response["answer"])
        self.assertIn("SECRET_SENTINEL", json.dumps(self.prompts[response["traceId"]]))
        self.assertEqual(code, 1)
        self.assertTrue(any(v["stage"] == "modelContext" for v in results[0].violations))

    def test_missing_flask_evidence_blocks_real_query(self):
        os.environ["WARDEN_GUARD_ENABLED"] = "false"
        self.manifest["cases"] = self.manifest["cases"][:1]
        self.assertEqual(self.check(self.manifest)[2], 2)

    def test_concurrent_api_requests_keep_principals_separate(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            payloads = list(pool.map(lambda _: capture(self.manifest, self.url, self.directory), range(2)))
        traces = []
        all_results, all_evidence = [], []
        for payload in payloads:
            results, code = evaluate_suite(payload)
            self.assertEqual(code, 0)
            all_results.extend(asdict(result) for result in results)
            all_evidence.extend(entry["response"].get("evidence") for entry in payload["cases"])
            for entry in payload["cases"]:
                response = entry["response"]
                self.assertEqual(entry["case"]["userId"], response["evidence"]["userId"])
                traces.append(response["traceId"])
        self.assertEqual(len(traces), len(set(traces)))
        self.reports.append({"test": self._testMethodName, "exitCode": 0,
                             "results": all_results, "evidence": all_evidence})
