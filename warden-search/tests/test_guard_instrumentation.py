"""Real Chroma with explicit local vectors: no OpenAI calls or model downloads."""
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["WARDEN_ENV_FILE"] = os.devnull
os.environ["ANONYMIZED_TELEMETRY"] = "False"
import chromadb
from chromadb.config import Settings

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("retrieval_service", ROOT / "retrieval_service.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class SyntheticStore:
    """Adapter exposing the two Chroma operations used by production retrieval."""
    def __init__(self, collection):
        self._collection = collection
        self.unsafe = False

    def similarity_search_with_score(self, question, k, filter):
        # The mutant exists only here, never in production service code.
        where = None if self.unsafe else filter
        data = self._collection.query(query_embeddings=[[1., 0., 0.]], n_results=min(k, 3), where=where,
                                      include=["documents", "metadatas", "distances"])
        return [(SimpleNamespace(page_content=text, metadata=metadata), distance)
                for text, metadata, distance in zip(data["documents"][0], data["metadatas"][0], data["distances"][0])]


def synthetic_store():
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    import uuid
    collection = client.create_collection("guard_" + uuid.uuid4().hex, embedding_function=None)
    collection.add(ids=["public", "salary", "filler"],
        documents=["synthetic public guidance", "synthetic salary SECRET_SENTINEL", "unrelated filler"],
        embeddings=[[.8, .2, 0.], [1., 0., 0.], [0., 0., 1.]],
        metadatas=[{"source": "public.md", "access_level": "public"}, {"source": "salary.md", "access_level": "manager"},
                   {"source": "public.md", "access_level": "public"}])
    return SyntheticStore(collection)


class RetrievalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = synthetic_store()
        service.vector_stores = {"policy_docs": cls.store}

    def setUp(self):
        self.store.unsafe = False

    def search(self, levels, enabled=True):
        with patch.dict(os.environ, {"WARDEN_GUARD_ENABLED": str(enabled).lower()}):
            return service.app.test_client().post("/search", json={"question": "synthetic salary", "allowedAccessLevels": levels}, headers={"X-Trace-Id": "test-correlation"})

    def test_public_filter_and_metadata_only_evidence(self):
        response = self.search(["public"])
        data = response.get_json()
        self.assertTrue(all(row["accessLevel"] == "public" for row in data["results"]))
        evidence = data["guardEvidence"]
        self.assertEqual(evidence["requestId"], "test-correlation")
        self.assertTrue(evidence["complete"])
        self.assertNotIn("SENTINEL", json.dumps(evidence))
        self.assertEqual(response.headers["X-Trace-Id"], "test-correlation")

    def test_manager_can_observe_synthetic_restricted_document(self):
        self.assertTrue(any(row["accessLevel"] == "manager" for row in self.search(["public", "manager"]).get_json()["results"]))

    def test_missing_levels_is_completed_empty(self):
        data = self.search([]).get_json()
        self.assertEqual(data["guardEvidence"]["documents"], [])

    def test_mutant_is_observed_without_hiding_leak(self):
        self.store.unsafe = True
        self.assertTrue(any(row["accessLevel"] == "manager" for row in self.search(["public"]).get_json()["guardEvidence"]["documents"]))

    def test_disabled_adds_no_evidence(self):
        self.assertNotIn("guardEvidence", self.search(["public"], enabled=False).get_json())


if __name__ == "__main__":
    unittest.main()
