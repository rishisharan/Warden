package com.warden.web.dto;

public record IngestResponse(
        String filename,
        String collection,
        String accessLevel,
        int chunksStored
) {
}
