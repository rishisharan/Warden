package com.warden.guard;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class EvidenceWriter {
    private final boolean enabled;
    private final Path directory;
    private final ObjectMapper mapper;

    public EvidenceWriter(@Value("${app.warden.guard.enabled:false}") boolean enabled,
            @Value("${app.warden.guard.evidence-dir:}") String directory, ObjectMapper mapper) {
        if (enabled && directory.isBlank()) throw new IllegalArgumentException("Guard requires a private evidence directory");
        this.enabled = enabled;
        this.directory = directory.isBlank() ? null : Path.of(directory).toAbsolutePath().normalize();
        this.mapper = mapper;
    }
    public boolean enabled() { return enabled; }
    public void write(SecurityEvidence evidence) throws IOException {
        Files.createDirectories(directory);
        Path temporary = Files.createTempFile(directory, "guard-", ".tmp");
        try {
            mapper.writeValue(temporary.toFile(), evidence.snapshot());
            Files.move(temporary, directory.resolve(evidence.requestId + ".json"), StandardCopyOption.ATOMIC_MOVE);
        } finally { Files.deleteIfExists(temporary); }
    }
}
