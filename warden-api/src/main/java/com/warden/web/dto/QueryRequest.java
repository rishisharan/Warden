package com.warden.web.dto;

import jakarta.validation.constraints.NotBlank;

public record QueryRequest(
        String userId,
        @NotBlank String question
) {
}
