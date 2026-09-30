package com.warden.web;

import com.warden.service.RetrievalService;
import com.warden.web.dto.IngestResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

/**
 * Lets the UI add a new document straight into the permission-filtered
 * knowledge base. The caller declares an access level at upload time
 * (public/manager) and it is stored as metadata on every chunk - the same
 * metadata RetrievalService's Chroma filter checks on every /search call.
 * There is no "upload now, classify later": a chunk is either tagged
 * correctly the moment it enters Chroma, or the upload is rejected here
 * before it ever reaches the vector store.
 */
@RestController
@RequestMapping("/api")
public class DocumentController {

    private static final Set<String> ALLOWED_EXTENSIONS = Set.of("txt", "md");
    private static final Set<String> ALLOWED_ACCESS_LEVELS = Set.of("public", "manager");
    private static final long MAX_FILE_BYTES = 2L * 1024 * 1024; // 2 MB - plenty for a text/markdown doc

    private final RetrievalService retrievalService;

    public DocumentController(RetrievalService retrievalService) {
        this.retrievalService = retrievalService;
    }

    @PostMapping(value = "/documents", consumes = "multipart/form-data")
    public IngestResponse upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam("accessLevel") String accessLevel) {

        if (file.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Uploaded file is empty");
        }
        if (file.getSize() > MAX_FILE_BYTES) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "File too large (max 2 MB for this MVP)");
        }

        String filename = file.getOriginalFilename();
        String extension = extensionOf(filename);
        if (!ALLOWED_EXTENSIONS.contains(extension)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Only .txt and .md files are supported right now, got: " + filename);
        }

        String normalizedAccessLevel = accessLevel == null ? "" : accessLevel.toLowerCase(Locale.ROOT);
        if (!ALLOWED_ACCESS_LEVELS.contains(normalizedAccessLevel)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "accessLevel must be 'public' or 'manager', got: " + accessLevel);
        }

        String content;
        try {
            content = new String(file.getBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Could not read uploaded file", e);
        }

        if (content.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Uploaded file has no text content");
        }

        return retrievalService.ingest(filename, content, normalizedAccessLevel);
    }

    private static String extensionOf(String filename) {
        if (filename == null) {
            return "";
        }
        int dot = filename.lastIndexOf('.');
        return dot < 0 ? "" : filename.substring(dot + 1).toLowerCase(Locale.ROOT);
    }
}
