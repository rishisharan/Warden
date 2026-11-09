package com.warden.guard;

import com.warden.domain.RetrievedChunk;
import java.util.*;

/** Request-local metadata only. Never copy retrieval IDs, source names or text. */
public final class SecurityEvidence {
    private static final ThreadLocal<SecurityEvidence> CURRENT = new ThreadLocal<>();
    public final String requestId;
    public String userId;
    public List<String> allowed = List.of();
    public boolean retrievalComplete, modelContextComplete, modelCalled;
    public final List<Map<String, Object>> retrieved = new ArrayList<>();
    public final List<Map<String, Object>> modelContext = new ArrayList<>();
    public final List<Map<String, Object>> authorizationDecisions = new ArrayList<>();

    public SecurityEvidence(String requestId) { this.requestId = requestId; }
    public static SecurityEvidence current() { return CURRENT.get(); }
    public static void bind(SecurityEvidence value) { CURRENT.set(value); }
    public static void clear() { CURRENT.remove(); }

    public static Map<String, Object> document(RetrievedChunk chunk) {
        Map<String, Object> row = new LinkedHashMap<>();
        String id = chunk.documentId();
        row.put("documentId", id != null && id.matches("[a-f0-9]{64}") ? id : null);
        row.put("accessLevel", "public".equals(chunk.accessLevel()) || "manager".equals(chunk.accessLevel()) ? chunk.accessLevel() : null);
        return row;
    }

    public void retrieval(List<RetrievedChunk> chunks, Object observation) {
        for (RetrievedChunk chunk : chunks) {
            Map<String, Object> row = document(chunk);
            retrieved.add(row);
            Map<String, Object> decision = new LinkedHashMap<>(row);
            decision.put("decision", row.get("accessLevel") == null ? "UNKNOWN" : allowed.contains(row.get("accessLevel")) ? "ALLOW" : "DENY");
            authorizationDecisions.add(decision);
        }
        if (observation instanceof Map<?, ?> map) {
            retrievalComplete = requestId.equals(map.get("requestId"))
                && Boolean.TRUE.equals(map.get("complete")) && retrieved.equals(map.get("documents"));
        }
    }

    public Map<String, Object> snapshot() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("schemaVersion", 1);
        result.put("requestId", requestId);
        result.put("userId", userId);
        result.put("retrievalComplete", retrievalComplete);
        result.put("modelContextComplete", modelContextComplete);
        result.put("modelCalled", modelCalled);
        result.put("retrieved", retrieved);
        result.put("modelContext", modelContext);
        result.put("authorizationDecisions", authorizationDecisions);
        return result;
    }
}
