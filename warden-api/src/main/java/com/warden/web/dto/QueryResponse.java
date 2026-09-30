package com.warden.web.dto;

import java.util.List;

public record QueryResponse(
        String userId,
        String role,
        String clearance,
        String answer,
        List<CitedSource> citedSources
) {
}
