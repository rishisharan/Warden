package com.warden.guard;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.warden.service.*;
import com.warden.web.TraceIdFilter;
import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.*;
import static org.junit.jupiter.api.Assertions.*;

class GuardInstrumentationTest {
    @TempDir Path directory;
    final ObjectMapper mapper = new ObjectMapper();
    HttpServer server;
    String retrievalTrace, modelTrace, prompt;
    List<Map<String, Object>> rows;
    boolean observation = true;

    Map<String, Object> row(String id, String level, String text) {
        return Map.of("id", "unsafe::" + text, "sourceFile", "synthetic.md", "sourceType", "policy_docs",
            "accessLevel", level, "content", text, "distance", .1, "documentId", id);
    }
    @BeforeEach void start() throws Exception {
        rows = List.of(row("a".repeat(64), "public", "PUBLIC_SENTINEL"), row("b".repeat(64), "manager", "SECRET_SENTINEL"));
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/search", exchange -> {
            retrievalTrace = exchange.getRequestHeaders().getFirst("X-Trace-Id");
            Map<String, Object> body = new HashMap<>();
            body.put("results", rows);
            if (observation) body.put("guardEvidence", Map.of("requestId", retrievalTrace, "complete", true,
                "documents", rows.stream().map(r -> Map.of("documentId", r.get("documentId"), "accessLevel", r.get("accessLevel"))).toList()));
            byte[] bytes = mapper.writeValueAsBytes(body);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length); exchange.getResponseBody().write(bytes); exchange.close();
        });
        server.createContext("/api/chat", exchange -> {
            modelTrace = exchange.getRequestHeaders().getFirst("X-Trace-Id");
            prompt = new String(exchange.getRequestBody().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
            byte[] bytes = mapper.writeValueAsBytes(Map.of("message", Map.of("content", "I don't have authorized information to answer that question.")));
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length); exchange.getResponseBody().write(bytes); exchange.close();
        });
        server.start();
    }
    @AfterEach void stop() { server.stop(0); SecurityEvidence.clear(); }

    Map<?, ?> query(String user, boolean enabled) throws Exception {
        String base = "http://127.0.0.1:" + server.getAddress().getPort();
        QueryService service = new QueryService(new UserService(), new RetrievalService(base, 2), new OllamaChatService(base, "synthetic"));
        TraceIdFilter filter = new TraceIdFilter(new EvidenceWriter(enabled, directory.toString(), mapper));
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/query");
        MockHttpServletResponse response = new MockHttpServletResponse();
        filter.doFilter(request, response, (req, res) -> {
            var result = service.answer(response.getHeader("X-Trace-Id"), user, "SENSITIVE_QUESTION");
            assertEquals("I don't have authorized information to answer that question.", result.answer());
            assertEquals(rows.size(), result.citedSources().size());
        });
        String trace = response.getHeader("X-Trace-Id");
        assertEquals(trace, retrievalTrace);
        assertNull(SecurityEvidence.current());
        if (!enabled) { assertFalse(Files.exists(directory.resolve(trace + ".json"))); return Map.of(); }
        String json = Files.readString(directory.resolve(trace + ".json"));
        assertFalse(json.contains("SENTINEL")); assertFalse(json.contains("SENSITIVE_QUESTION")); assertFalse(json.contains("unsafe::"));
        return mapper.readValue(json, Map.class);
    }
    @Test void recordsActualFirstContextAndCorrelation() throws Exception {
        Map<?, ?> evidence = query("user-a", true);
        assertEquals(retrievalTrace, modelTrace);
        assertTrue(prompt.contains("PUBLIC_SENTINEL")); assertFalse(prompt.contains("SECRET_SENTINEL"));
        assertEquals(2, ((List<?>) evidence.get("retrieved")).size());
        assertEquals(1, ((List<?>) evidence.get("modelContext")).size());
        assertEquals(true, evidence.get("retrievalComplete")); assertEquals(true, evidence.get("modelContextComplete"));
        assertTrue(evidence.toString().contains("DENY"));
    }
    @Test void leakRemainsObservedDespiteRefusal() throws Exception {
        rows = List.of(row("b".repeat(64), "manager", "SECRET_SENTINEL"));
        Map<?, ?> evidence = query("user-a", true);
        assertTrue(prompt.contains("SECRET_SENTINEL"));
        assertTrue(evidence.get("modelContext").toString().contains("b".repeat(64)));
        assertTrue(evidence.get("authorizationDecisions").toString().contains("DENY"));
    }
    @Test void missingFlaskEvidenceStaysIncomplete() throws Exception {
        observation = false;
        assertEquals(false, query("user-a", true).get("retrievalComplete"));
    }
    @Test void emptyRetrievalDoesNotCallModel() throws Exception {
        rows = List.of();
        Map<?, ?> evidence = query("user-a", true);
        assertEquals(false, evidence.get("modelCalled")); assertEquals(true, evidence.get("modelContextComplete")); assertNull(modelTrace);
    }
    @Test void disabledInstrumentationPreservesBehavior() throws Exception { query("user-a", false); }
    @Test void threadLocalIsolatesConcurrentRequests() throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            var tasks = List.<Callable<String>>of(() -> localUser("user-a"), () -> localUser("user-b"));
            var results = pool.invokeAll(tasks);
            assertEquals("user-a", results.get(0).get()); assertEquals("user-b", results.get(1).get());
        } finally { pool.shutdownNow(); }
    }
    String localUser(String user) { try { var e = new SecurityEvidence(UUID.randomUUID().toString()); e.userId = user; SecurityEvidence.bind(e); return SecurityEvidence.current().userId; } finally { SecurityEvidence.clear(); } }
}
