package com.warden.web.dto;

import jakarta.validation.constraints.NotBlank;

public record QueryRequest(
        @NotBlank String userId,
        @NotBlank String question
) {
}
