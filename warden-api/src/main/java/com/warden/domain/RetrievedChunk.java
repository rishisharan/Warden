package com.warden.domain;

/**
 * A chunk returned from a permission-filtered similarity search. Only ever
 * populated from rows the requesting user's clearance already permitted -
 * the Python retrieval service applies the access-level filter inside its
 * own Chroma query, not Java.
 */
public record RetrievedChunk(
        String id,
        String sourceFile,
        String sourceType,
        String accessLevel,
        String content,
        double distance
) {
}
