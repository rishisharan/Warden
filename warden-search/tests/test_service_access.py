"""Regression tests for the Java-to-Flask service boundary."""
import os
import unittest
from unittest.mock import Mock, patch

from test_guard_instrumentation import SERVICE_TOKEN, service, synthetic_store


class ServiceAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = synthetic_store()

    def setUp(self):
        credentials = patch.dict(os.environ, {"WARDEN_RETRIEVAL_SERVICE_TOKEN": SERVICE_TOKEN})
        credentials.start()
        self.addCleanup(credentials.stop)

    def test_search_denies_untrusted_callers(self):
        for label, headers in (
            ("missing", {}),
            ("invalid", {"Authorization": "Bearer invalid-test-token"}),
        ):
            with self.subTest(credential=label):
                with patch.object(service, "get_stores", return_value={"policy_docs": self.store}) as get_stores:
                    response = service.app.test_client().post(
                        "/search", headers=headers,
                        json={"question": "synthetic salary", "allowedAccessLevels": ["manager"], "topK": 3},
                    )
                self.assertEqual(response.status_code, 401)
                get_stores.assert_not_called()
                self.assertNotIn("SECRET_SENTINEL", response.get_data(as_text=True))

    def test_ingest_denies_untrusted_callers(self):
        for label, headers in (
            ("missing", {}),
            ("invalid", {"Authorization": "Bearer invalid-test-token"}),
        ):
            with self.subTest(credential=label):
                store = Mock()
                with patch.object(service, "get_stores", return_value={"policy_docs": store}) as get_stores:
                    response = service.app.test_client().post(
                        "/ingest", headers=headers,
                        json={"filename": "test.md", "content": "synthetic document", "accessLevel": "public"},
                    )
                self.assertEqual(response.status_code, 401)
                get_stores.assert_not_called()
                store.add_texts.assert_not_called()

    def test_missing_server_credential_fails_closed(self):
        with patch.dict(os.environ, {"WARDEN_RETRIEVAL_SERVICE_TOKEN": ""}):
            response = service.app.test_client().post(
                "/search", headers={"Authorization": "Bearer "}, json={},
            )
        self.assertEqual(response.status_code, 401)

    def test_trusted_service_can_ingest(self):
        store = Mock()
        with patch.object(service, "get_stores", return_value={"policy_docs": store}):
            response = service.app.test_client().post(
                "/ingest", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
                json={"filename": "test.md", "content": "synthetic document", "accessLevel": "manager"},
            )
        self.assertEqual(response.status_code, 200)
        store.add_texts.assert_called_once_with(
            texts=["synthetic document"], metadatas=[{"source": "test.md", "access_level": "manager"}],
        )
