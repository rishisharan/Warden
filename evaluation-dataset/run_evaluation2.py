"""Isolated live Evaluation Set 2. No external model or production data access."""
import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import runpy
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from importlib.metadata import version
from pathlib import Path
from urllib.error import HTTPError

from guard_live import authenticated_query

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATASET = HERE / "fixtures" / "evaluation_set_2_golden.json"
SEARCH = ROOT / "warden-search"
OLLAMA = "http://127.0.0.1:18135"
FLASK = "http://127.0.0.1:18011"
JAVA = "http://127.0.0.1:18082"
MINIMUMS = dict(lookup=10, synthesis=10, conflict=8, stale=8,
                authorization=10, refusal=5, injection=5, ambiguous=4)
EMBEDDING = "nomic-embed-text:latest"
GENERATION = "llama3.2:latest"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def load():
    from collections import Counter

    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    cases = payload["cases"]
    refs = payload["references"]
    counts = Counter(case["category"] for case in cases)
    if set(counts) != set(MINIMUMS) or any(counts[key] < count for key, count in MINIMUMS.items()):
        raise ValueError("Missing golden category coverage")
    if len({case["id"] for case in cases}) != len(cases) or len({case["question"] for case in cases}) != len(cases):
        raise ValueError("Duplicate golden case ID or question")
    for case in cases:
        relevant = case.get("sources", []) + case.get("context", [])
        expected = [refs[key]["documentId"] for key in case.get("sources", [])]
        if (case["relevantDocumentIds"] != [refs[key]["documentId"] for key in relevant]
                or case["expectedCitations"] != expected
                or set(relevant).intersection(case.get("blocked", []))
                or (case["outcome"] == "answer") != bool(expected)
                or case["outcome"] not in {"answer", "refuse", "clarify"}
                or {"user-a": "public", "user-b": "manager"}.get(case["user"]) != case["access"]
                or any(refs[key]["access"] == "manager" and case["access"] == "public" for key in relevant)
                or not (case["expected"] and case["claims"] and case["why"])):
            raise ValueError(f"Invalid golden case {case['id']}")
    tracked = set(git("ls-files", "--", "data").splitlines())
    ids = set()
    for ref in refs.values():
        source = fixture(ref, tracked)
        content = source.read_text(encoding="utf-8-sig")
        source_key = [source.parent.name.replace("-", "_"), source.name]
        document_id = hashlib.sha256(json.dumps(source_key, separators=(",", ":")).encode()).hexdigest()
        access = ("manager" if any(tag in content for tag in ("(Confidential", "(Restricted", "Manager Access"))
                  else "public")
        if (ref["excerpt"].casefold() not in content.casefold() or ref["documentId"] != document_id
                or document_id in ids or ref["access"] != access):
            raise ValueError(f"Invalid golden source {source.name}")
        ids.add(document_id)
    return payload


def fixture(ref, tracked=None):
    corpora = (ROOT / "data", HERE / "fixtures" / "quality_corpus")
    candidates = [corpus / ref["path"] for corpus in corpora]
    if tracked is None:
        tracked = set(git("ls-files", "--", "data").splitlines())
    return candidates[0] if f"data/{ref['path']}" in tracked else candidates[1]


def request(method, url, **kwargs):
    import requests
    with requests.Session() as session:
        session.trust_env = False
        response = session.request(method, url, timeout=kwargs.pop("timeout", 120), **kwargs)
        response.raise_for_status()
        return response.json()


def search_process(stage):
    import langchain_openai
    from langchain_core.embeddings import Embeddings

    class LocalEmbeddings(Embeddings):
        def __init__(self, *, model):
            if model != "text-embedding-3-small":
                raise ValueError("Unexpected Warden embedding configuration")

        def embed_documents(self, texts):
            return request("POST", OLLAMA + "/api/embed",
                           json={"model": EMBEDDING, "input": texts})["embeddings"]

        def embed_query(self, text):
            return self.embed_documents([text])[0]

    langchain_openai.OpenAIEmbeddings = LocalEmbeddings
    runpy.run_path(str(SEARCH / stage), run_name="__main__")


def start(command, env, directory, name):
    with (directory / (name + ".log")).open("wb") as log:
        return subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                                stderr=subprocess.STDOUT)


def wait_for(process, url, ready):
    from requests import RequestException

    for _ in range(45):
        if process.poll() is not None:
            raise RuntimeError(f"{ready} exited with status {process.returncode}")
        try:
            return request("GET", url, timeout=1)
        except RequestException:
            time.sleep(1)
    raise RuntimeError(f"{ready} did not become reachable on loopback")


def validate_response(case, body):
    expected = case["access"].upper()
    if body["userId"] != case["user"] or body["clearance"] != expected:
        # Keep mismatched identity observable even if the answer is otherwise valid.
        body["identityMismatch"] = True
    if not isinstance(body["answer"], str):
        raise ValueError("Invalid answer")


def compact(rows):
    return [{k: row.get(k) for k in ("documentId", "accessLevel", "sourceFile")} for row in rows]


def evidence_at(directory, trace):
    if str(uuid.UUID(trace)) != trace:
        raise ValueError("Invalid trace")
    path = directory / (trace + ".json")
    for _ in range(40):
        if path.is_file():
            receipt = json.loads(path.read_text(encoding="utf-8"))
            return receipt if receipt["requestId"] == trace else None
        time.sleep(.05)
    return None


def capture(case, token, password, evidence, k):
    row = {"id": case["id"]}
    levels = ["public", "manager"] if case["access"] == "manager" else ["public"]
    start = time.perf_counter()
    try:
        result = request("POST", FLASK + "/search", headers={"Authorization": f"Bearer {token}"},
                         json={"question": case["question"], "allowedAccessLevels": levels, "topK": k})
        row["retrieval"] = compact(result["results"])
        row["retrievalMs"] = (time.perf_counter() - start) * 1000
    except Exception as error:
        row["retrievalError"] = type(error).__name__
    start = time.perf_counter()
    trace = None
    try:
        with authenticated_query(JAVA + "/api/query", case["user"], case["question"],
                                 120, password=password) as response:
            trace = response.headers.get("X-Trace-Id")
            body = json.load(response)
        validate_response(case, body)
        body["citedSources"] = compact(body["citedSources"])
        row["response"] = body
        row["endToEndMs"] = (time.perf_counter() - start) * 1000
    except Exception as error:
        if isinstance(error, HTTPError):
            trace = error.headers.get("X-Trace-Id")
            row["queryStatus"] = error.code
            error.close()
        row["queryError"] = type(error).__name__
    if trace:
        row["trace"] = trace
        try:
            row["evidence"] = evidence_at(evidence, trace)
        except (OSError, ValueError, KeyError):
            row["evidence"] = None
    return row


def live(payload, directory, k):
    import bcrypt
    import re

    private = directory / "private"
    private.mkdir(parents=True, exist_ok=False)
    (private / ".gitignore").write_text("*\n", encoding="utf-8")
    seed = private / "seed"
    processes = []
    corpus = {}
    tracked = set(git("ls-files", "--", "data").splitlines())
    for ref in payload["references"].values():
        source = fixture(ref, tracked)
        target = seed / ref["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        corpus[ref["path"]] = digest(target)

    env = os.environ.copy()
    token = secrets.token_urlsafe(32)
    passwords = {user: secrets.token_urlsafe(24) for user in ("user-a", "user-b")}
    env.update(WARDEN_ENV_FILE=str(private / "unused.env"), WARDEN_DATA_DIR=str(seed),
               WARDEN_RETRIEVAL_SERVICE_TOKEN=token, WARDEN_GUARD_ENABLED="true",
               ANONYMIZED_TELEMETRY="False", OLLAMA_HOST="127.0.0.1:18135",
               OLLAMA_NOPRUNE="true", OLLAMA_NO_CLOUD="true", PORT="18011",
               WARDEN_RETRIEVAL_HOST="127.0.0.1", OLLAMA_VULKAN="false",
               WARDEN_REP_PASSWORD_HASH=bcrypt.hashpw(passwords["user-a"].encode(), bcrypt.gensalt()).decode(),
               WARDEN_MANAGER_PASSWORD_HASH=bcrypt.hashpw(passwords["user-b"].encode(), bcrypt.gensalt()).decode())
    jar = ROOT / "warden-api" / "target" / "warden-api.jar"
    manifest = dict(timestamp=dt.datetime.now().astimezone().isoformat(), gitCommit=git("rev-parse", "HEAD"),
                    workingTree=git("status", "--porcelain"), datasetVersion=payload["version"],
                    datasetSha256=digest(DATASET), corpusSha256=corpus, topK=k, applicationTopK=1,
                    environment=platform.platform(), python=platform.python_version(),
                    javaJarSha256=digest(jar) if jar.is_file() else None,
                    embedding=EMBEDDING, generation=GENERATION,
                    generationOptions="Warden defaults, no sampling overrides",
                    packageVersions={name: version(name) for name in ("chromadb", "flask", "rank-bm25", "langchain-openai")})
    manifest_path = directory / "manifest.json"
    def save_manifest():
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    save_manifest()
    try:
        if not jar.is_file():
            raise RuntimeError("Java jar missing. Run Maven package first.")
        ollama = start(["ollama", "serve"], env, private, "ollama")
        processes.append(ollama)
        manifest["ollama"] = wait_for(ollama, OLLAMA + "/api/version", "Ollama")["version"]
        models = request("GET", OLLAMA + "/api/tags")["models"]
        manifest["modelDigests"] = {row["name"]: row["digest"] for row in models
                                    if row["name"] in (EMBEDDING, GENERATION)}
        if set(manifest["modelDigests"]) != {EMBEDDING, GENERATION}:
            raise RuntimeError("Required local Ollama models are missing")
        save_manifest()
        command = [sys.executable, "-B", str(Path(__file__).resolve())]
        ingestion = start(command + ["--stage", "ingestion.py"], env, private, "ingestion")
        processes.append(ingestion)
        if ingestion.wait(timeout=240):
            raise RuntimeError("Isolated Chroma ingestion failed. See private ingestion.log.")
        evidence = private / "evidence"
        retrieval = start(command + ["--stage", "retrieval_service.py"], env, private, "retrieval")
        processes.append(retrieval)
        # Flask has no health route. The trusted empty-level request only checks transport.
        for _ in range(45):
            if retrieval.poll() is not None:
                raise RuntimeError("Flask exited during startup")
            try:
                request("POST", FLASK + "/search", timeout=1, headers={"Authorization": f"Bearer {token}"},
                        json={"question": "readiness", "allowedAccessLevels": []})
                break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("Flask did not become reachable")
        application = start(["java", "-jar", str(jar), "--server.address=127.0.0.1",
                             "--server.port=18082", "--app.warden.top-k=1",
                             "--app.warden.retrieval-base-url=" + FLASK, "--app.ollama.base-url=" + OLLAMA,
                             "--app.ollama.chat-model=" + GENERATION,
                             "--app.warden.guard.enabled=true",
                             "--app.warden.guard.evidence-dir=" + str(evidence)], env, private, "java")
        processes.append(application)
        wait_for(application, JAVA + "/api/csrf", "Spring Boot")
        with (private / "observations.jsonl").open("w", encoding="utf-8") as output:
            for case in payload["cases"]:
                row = capture(case, token, passwords[case["user"]], evidence, k)
                if row.get("trace"):
                    pattern = rf"traceId={row['trace']} .*?llmDuration=(\d+)ms"
                    match = re.search(pattern, (private / "java.log").read_text(encoding="utf-8", errors="replace"))
                    if match:
                        row["generationMs"] = int(match[1])
                print(case["id"], "captured" if "response" in row else "query error", flush=True)
                output.write(json.dumps(row) + "\n")
                output.flush()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        manifest["blocker"] = str(error)
        save_manifest()
        print(manifest["blocker"], flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["ingestion.py", "retrieval_service.py"])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--top-k", type=int, default=5, choices=range(1, 51))
    args = parser.parse_args()
    if args.stage:
        search_process(args.stage)
        return 0
    payload = load()
    if args.check:
        print(f"Validated {len(payload['cases'])} golden cases.")
        return 0
    if args.output is None:
        parser.error("--output is required")
    directory = args.output.resolve()
    if not args.report_only:
        directory.mkdir(parents=True, exist_ok=False)
        live(payload, directory, args.top_k)
    from evaluation2_report import report
    return report(payload, directory, use_reviews=args.report_only)


if __name__ == "__main__":
    raise SystemExit(main())
