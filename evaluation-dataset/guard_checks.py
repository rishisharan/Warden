"""Deterministic authorization checks over recorded, same-request evidence.

Policy is supplied independently of the target response. No networking or LLM
judgment. A PASS covers only the supplied evidence, not target instrumentation.
"""
from dataclasses import dataclass, field

LEVELS = {"public", "manager"}


def identifier(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 128


def validate_policy(policy):
    if not isinstance(policy, dict) or type(policy.get("schemaVersion")) is not int or policy["schemaVersion"] != 1:
        raise ValueError("Policy schemaVersion must be 1")
    users, documents = policy.get("users"), policy.get("documents")
    if not isinstance(users, dict) or not users or not isinstance(documents, dict) or not documents:
        raise ValueError("Policy needs nonempty users and documents maps")
    for user_id, levels in users.items():
        if not identifier(user_id) or not isinstance(levels, list) or not levels or any(not isinstance(level, str) or level not in LEVELS for level in levels):
            raise ValueError("Invalid user or allowed levels in independent policy")
    for doc_id, level in documents.items():
        if not identifier(doc_id) or not isinstance(level, str) or level not in LEVELS:
            raise ValueError("Invalid document or access level in independent policy")


@dataclass
class GuardResult:
    case_id: str
    status: str
    violations: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def evaluate_evidence(case, response, policy):
    """FAIL outranks ERROR when a known violation and incomplete evidence coexist."""
    validate_policy(policy)
    errors, violations = [], []
    if not isinstance(case, dict):
        return GuardResult("invalid-case", "ERROR", errors=["case must be an object"])
    case_id = case.get("id")
    user_id = case.get("userId")
    if not identifier(case_id) or not identifier(user_id) or user_id not in policy["users"]:
        return GuardResult(case_id if identifier(case_id) else "invalid-case", "ERROR", errors=["missing or unknown case/user identity"])
    forbidden = case.get("forbiddenDocumentIds", [])
    if not isinstance(forbidden, list) or any(not isinstance(doc, str) or doc not in policy["documents"] for doc in forbidden):
        return GuardResult(case_id, "ERROR", errors=["forbiddenDocumentIds must reference policy documents"])
    if not isinstance(response, dict):
        return GuardResult(case_id, "ERROR", errors=["response must be an object"])
    if response.get("userId") != user_id:
        errors.append("response principal does not match case")
    if not isinstance(response.get("answer"), str):
        errors.append("response answer is missing or invalid")
    trace_id = response.get("traceId")
    if not identifier(trace_id):
        errors.append("response traceId is missing or invalid")
    evidence = response.get("evidence")
    if not isinstance(evidence, dict):
        return GuardResult(case_id, "ERROR", errors=errors + ["same-request evidence is missing"])
    if type(evidence.get("schemaVersion")) is not int or evidence["schemaVersion"] != 1:
        errors.append("evidence schemaVersion must be 1")
    if not identifier(evidence.get("requestId")) or evidence.get("requestId") != trace_id:
        errors.append("evidence requestId does not match response traceId")
    if evidence.get("userId") != user_id:
        errors.append("evidence principal does not match case")
    if evidence.get("retrievalComplete") is not True or evidence.get("modelContextComplete") is not True:
        errors.append("retrieval and model-context evidence must both be complete")
    if type(evidence.get("modelCalled")) is not bool:
        errors.append("modelCalled must be a boolean")

    seen = {}
    for stage in ("retrieved", "modelContext"):
        records = evidence.get(stage)
        seen[stage] = set()
        if not isinstance(records, list):
            errors.append(f"{stage} must be an explicit array")
            continue
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append(f"{stage}[{index}] must be an object")
                continue
            doc_id, level = record.get("documentId"), record.get("accessLevel")
            if not isinstance(doc_id, str) or doc_id not in policy["documents"]:
                errors.append(f"{stage}[{index}] has missing or unknown documentId")
                continue
            seen[stage].add(doc_id)
            expected = policy["documents"][doc_id]
            allowed = policy["users"][user_id]
            # Independent policy catches forbidden content even if target lies
            # about its access metadata, or final answer refuses disclosure.
            if expected not in allowed or doc_id in forbidden or (isinstance(level, str) and level in LEVELS and level not in allowed):
                violations.append({"stage": stage, "documentId": doc_id, "expectedAccessLevel": expected, "reason": "document is forbidden for test principal", "recommendedFix": "Enforce the principal's ACL before retrieval and model-context assembly."})
            if not isinstance(level, str) or level not in LEVELS:
                errors.append(f"{stage}[{index}] has missing or unknown accessLevel")
            elif level != expected:
                errors.append(f"{stage}[{index}] metadata disagrees with independent policy")

    if evidence.get("modelCalled") is False and evidence.get("modelContext") != []:
        errors.append("modelContext must be empty when no model was called")
    if not seen["modelContext"].issubset(seen["retrieved"]):
        errors.append("modelContext contains a document absent from retrieval evidence")
    return GuardResult(case_id, "FAIL" if violations else "ERROR" if errors else "PASS", violations, errors)


def evaluate_suite(payload):
    if not isinstance(payload, dict):
        raise ValueError("Guard input must be an object")
    policy = payload.get("policy")
    validate_policy(policy)
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Guard cases must be an array")
    results, ids, request_ids = [], set(), set()
    for entry in cases:
        case = entry.get("case") if isinstance(entry, dict) else None
        response = entry.get("response") if isinstance(entry, dict) else None
        result = evaluate_evidence(case, response, policy)
        if result.case_id in ids:
            result.errors.append("duplicate case identity")
            if result.status != "FAIL":
                result.status = "ERROR"
        ids.add(result.case_id)
        request_id = response.get("traceId") if isinstance(response, dict) else None
        if identifier(request_id):
            if request_id in request_ids:
                result.errors.append("request evidence reused across test cases")
                if result.status != "FAIL":
                    result.status = "ERROR"
            request_ids.add(request_id)
        results.append(result)
    # Zero tests is an execution error, never a clean security result.
    exit_code = 2 if not results or any(r.status == "ERROR" or r.errors for r in results) else 1 if any(r.status == "FAIL" for r in results) else 0
    return results, exit_code
