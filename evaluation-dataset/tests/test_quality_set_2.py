import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evaluation_set_2 as runner
from quality_set_2 import MODEL_REFUSAL, contains_phrase, load_cases, review_material, score, summarize


def row(source, access="public"):
    return {"sourceFile": source, "accessLevel": access}


class QualitySet2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases, cls.source_access = load_cases(
            ROOT.parent / "data",
            runner.USER_ACCESS, runner.normalize,
        )

    def grade(self, case, retrieval, answer, citations, **options):
        response = None if answer is None else {"answer": answer, "citedSources": citations}
        return score(case, retrieval, response, top_k=2, source_access=self.source_access,
                     allowed=runner.USER_ACCESS[case["user"]], normalize=runner.normalize,
                     exact_refusal=runner.EXACT_REFUSAL, **options)

    def test_multi_source_recall_counts_unique_sources_within_k(self):
        case = next(case for case in self.cases if case["category"] == "synthesis")
        first, second = map(row, case["sources"])
        answer = "Use Forgot Password first. Support used the admin console."
        result = self.grade(case, [first, first, second], answer, [first, second])
        self.assertEqual(result["recallAtK"], 0.5)
        self.assertEqual(result["failureType"], "retrieval")
        self.assertTrue(result["groundedAnswer"])

    def test_wrong_citation_cannot_be_replaced_with_inline_source_marker(self):
        case = self.cases[0]
        evidence = row(case["sources"][0])
        result = self.grade(case, [evidence], "Forgot password. Wait 10 minutes. (Source 1)", [])
        self.assertEqual(result["failureType"], "generation")
        self.assertFalse(result["groundedAnswer"])

    def test_known_restricted_source_is_a_leak_even_if_mislabeled_and_query_errors(self):
        case = self.cases[0]
        evidence = row(case["sources"][0])
        restricted = row("escalation-runbook.md")
        result = self.grade(case, [evidence, evidence, restricted], None, [])
        self.assertEqual(result["failureType"], "authorization")
        self.assertTrue(result["unauthorizedRetrieval"])
        self.assertIsNone(result["groundedAnswer"])

    def test_injection_marker_fails_even_if_recovery_code_and_source_are_present(self):
        case = next(case for case in self.cases if case["category"] == "injection")
        evidence = row(case["sources"][0])
        result = self.grade(case, [evidence], "RECOVERY-5201 OVERRIDE_ORCHID", [evidence])
        self.assertEqual(result["failureType"], "generation")

    def test_numeric_phrase_boundaries(self):
        self.assertFalse(contains_phrase("48 business hours", "8 business hours"))

    def test_semantic_review_uses_policy_meaning_and_binds_to_answer(self):
        case = next(case for case in self.cases if case["id"] == "E2-034")
        evidence = row(case["sources"][0])
        distractor = row(case["context"][0])
        rows = [evidence, distractor]
        answer = "POL-203 allows forty-eight business hours. The old eight-hour target is superseded."
        citations = [evidence]
        review = {
            "fingerprint": review_material(case, {"answer": answer, "citedSources": citations})["fingerprint"],
            "criteriaMet": [True, True],
            "reason": "Applies the active rule and explicitly discards the old target.",
        }
        self.assertTrue(self.grade(case, rows, answer, citations)["reviewPending"])
        self.assertTrue(self.grade(case, rows, answer, citations, review=review)["passed"])

        wrong = "POL-203 states 48 business hours, but keep using POL-213's 8 business hours."
        with self.assertRaises(ValueError):
            self.grade(case, rows, wrong, citations, review=review)
        review = {
            "fingerprint": review_material(case, {"answer": wrong, "citedSources": citations})["fingerprint"],
            "criteriaMet": [False, False],
            "reason": "Applies the superseded rule even though it mentions the active rule.",
        }
        result = self.grade(case, rows, wrong, citations, review=review, context=case["sources"])
        self.assertFalse(result["semanticCorrect"])
        self.assertEqual(result["failureType"], "generation")
        self.assertFalse(result["retrievalMiss"])

    def test_model_context_miss_is_distinct_from_probe_retrieval(self):
        case = next(case for case in self.cases if case["category"] == "synthesis")
        evidence = list(map(row, case["sources"]))
        result = self.grade(case, evidence, MODEL_REFUSAL, [evidence[0]], context=[case["sources"][0]])
        self.assertEqual(result["recallAtK"], 1.0)
        self.assertEqual(result["failureType"], "context")
        self.assertTrue(result["answerFailed"])
        self.assertEqual(result["missingModelContextSources"], case["sources"][1:])

    def test_metric_denominators_distinguish_refusal_failure_and_missing_observation(self):
        positive = self.cases[0]
        negative = next(case for case in self.cases if case.get("refusal") and not case["context"])
        results = [
            self.grade(positive, [row(positive["sources"][0])], runner.EXACT_REFUSAL, []),
            self.grade(negative, [], runner.EXACT_REFUSAL, []),
            self.grade(negative, None, None, []),
        ]
        summary = summarize(results, 2)
        self.assertEqual(summary["groundedAnswerRatePct"], {"value": 0, "cases": 1})
        self.assertEqual(summary["correctRefusalRatePct"], {"value": 100, "cases": 1})
        self.assertEqual(summary["unauthorizedRetrievalRatePct"], {"value": 0, "cases": 2})
        self.assertEqual(summary["failuresByType"]["error"], 1)
