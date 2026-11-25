# Warden FDE evaluation interview questions

1. How would you decide whether low end-to-end accuracy comes from dense search, BM25, reciprocal rank fusion, final ranking or context assembly?
2. What changes would you make to test whether moving Java's top-K actually changes what the model sees?
3. How would you choose a context budget for multi-document questions where a single chunk is enough for most lookups?
4. How would you preserve BM25 quality while avoiding a corpus-wide rebuild per request as tenant data grows?
5. Which metrics would justify adding a cross-encoder after reciprocal rank fusion, and how would you measure the latency tradeoff?
6. How would you measure unique-document recall when duplicate chunks occupy the ranked slots?
7. What should a reliable answer-to-source citation prove, and how would you model the evidence contract between Flask, Java and Ollama?
8. How would you distinguish source selection failures from passage selection failures for a policy stored in several chunks?
9. Where should Warden enforce authorization when both lexical and dense search contribute candidates?
10. What should the Java API do when a downstream chunk has missing ACL metadata?
11. How would you evaluate revocation across active sessions, caches and replicas when an enterprise directory becomes the source of truth?
12. How should document ACLs be assigned when document text and the publisher's permissions disagree?
13. What architecture would prevent document text from gaining instruction authority in the model request?
14. How would you design the ingestion schema for effective dates, supersession, regional exceptions and historical lookup?
15. If a draft ranks above an active policy, where should Warden resolve source precedence and what evidence should its answer expose?
16. How would you distinguish an out-of-domain prompt, an ambiguous question and a legitimate question whose evidence is restricted?
17. How would you evaluate refusal policy with positive manager controls and negative public controls without confusing a safe refusal with success on a valid query?
18. What are the limits of Guard receipts, and how could you attest to the exact context sent to the model while minimizing sensitive telemetry?
19. What changes would you make to validate a local embedding benchmark against the configured OpenAI embedding model?
20. How would you align two reviewers on groundedness and quantify disagreement on partial answers?
21. What policies would you use to publish evaluation failures while preserving customer confidentiality and debugging utility?
22. How would you allocate latency budgets to CSRF/login, Warden, Flask, Chroma and Ollama without double-counting nested calls?
23. How should the application behave during an embedding outage, a failed index rebuild or an Ollama overload?
24. Which quality and security signals would gate rollout, and how would you handle a high overall pass rate alongside a single confirmed ACL breach?
25. How would you turn changes in synthesis accuracy, citation quality and correct refusals into measurable changes in support handling time, escalations and customer trust?
26. How would you explain the difference between a passing fault-injection test and live evidence of authorization across the complete application?
## Questions from the November 25 run

27. The isolated K=5 probes surfaced the labeled sources for the early synthesis cases while the production-shaped Java context omitted one or more sources. What would a controlled experiment need to hold constant to attribute an improvement to context assembly?
28. Two answers applied an obsolete acknowledgment target after receiving a superseded policy. What release gate would catch this while preserving valid historical lookups?
29. The model emitted a synthetic instruction marker even when it also returned the correct fact. How would you instrument and score that answer independently for factual correctness and integrity?
30. The authenticated query timing includes fresh session setup while Java's generation clock wraps the Ollama request. How would you design benchmarks for both cold customers and established sessions?
