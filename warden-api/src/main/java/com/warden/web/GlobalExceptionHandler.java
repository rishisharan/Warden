package com.warden.web;

import com.warden.service.UserService;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(UserService.NoSuchUserException.class)
    public ResponseEntity<Map<String, String>> handleNoSuchUser(UserService.NoSuchUserException ex) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Map.of("error", ex.getMessage()));
    }

    /**
     * DocumentController throws these for upload validation failures (bad
     * extension, bad access level, empty file, ...). Handled here so every
     * error from this API - 404s above included - comes back in the same
     * {"error": "..."} shape, which is what the UI's fetch wrappers parse.
     */
    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<Map<String, String>> handleResponseStatus(ResponseStatusException ex) {
        return ResponseEntity.status(ex.getStatusCode())
                .body(Map.of("error", ex.getReason() != null ? ex.getReason() : "Request failed"));
    }
}
