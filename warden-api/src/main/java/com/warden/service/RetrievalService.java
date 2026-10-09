package com.warden.service;

import com.warden.domain.AccessLevel;
import com.warden.domain.RetrievedChunk;
import com.warden.web.dto.IngestResponse;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

/**
 * Calls the Python retrieval service (see python-retrieval/retrieval_service.py),
 * which owns the Chroma vector store. This is the single choke point between
 * "what documents exist" and "what the model gets to see": the caller's
 * allowed access levels are sent as part of the request, and Chroma's own
 * metadata `where` filter excludes everything else before any chunk comes
 * back - not a filter applied after the fact, and never a step the LLM is
 * trusted to do itself. OllamaChatService only ever receives what this
 * method already returned.
 *
 * ingest() is the write side of the same choke point: whatever access level
 * the UI upload declared is the access level stored on every chunk, and
 * that's the only thing retrieveAuthorized() ever checks against later.
 */
@Service
public class RetrievalService {

    private final RestClient restClient;
    private final int topK;

    public RetrievalService(
            @Value("${app.warden.retrieval-base-url}") String retrievalBaseUrl,
            @Value("${app.warden.top-k}") int topK) {
        this.restClient = RestClient.create(retrievalBaseUrl);
        this.topK = topK;
    }

    @SuppressWarnings("unchecked")
    public List<RetrievedChunk> retrieveAuthorized(String question, AccessLevel clearance) {
        List<String> allowedLevels = clearance.allowedLevelsUpToInclusive();

        Map<String, Object> response = restClient.post()
                .uri("/search")
                .body(Map.of(
                        "question", question,
                        "allowedAccessLevels", allowedLevels,
                        "topK", topK
                ))
                .retrieve()
                .body(Map.class);

        if (response == null || !(response.get("results") instanceof List<?> rawResults)) {
            throw new IllegalStateException("Retrieval service returned no results field");
        }

        return rawResults.stream()
                .map(raw -> (Map<String, Object>) raw)
                .map(row -> new RetrievedChunk(
                        String.valueOf(row.get("id")),
                        String.valueOf(row.get("sourceFile")),
                        String.valueOf(row.get("sourceType")),
                        String.valueOf(row.get("accessLevel")),
                        String.valueOf(row.get("content")),
                        row.get("distance") instanceof Number number
                        ? number.doubleValue()
                        : Double.NaN                        
                ))
                .toList();
    }

    public IngestResponse ingest(String filename, String content, String accessLevel) {
        Map<String, Object> response = restClient.post()
                .uri("/ingest")
                .body(Map.of(
                        "filename", filename,
                        "content", content,
                        "accessLevel", accessLevel
                ))
                .retrieve()
                .body(Map.class);

        if (response == null || response.get("chunksStored") == null) {
            throw new IllegalStateException("Ingestion service returned no chunksStored field");
        }

        return new IngestResponse(
                String.valueOf(response.get("filename")),
                String.valueOf(response.get("collection")),
                String.valueOf(response.get("accessLevel")),
                ((Number) response.get("chunksStored")).intValue()
        );
    }
}
