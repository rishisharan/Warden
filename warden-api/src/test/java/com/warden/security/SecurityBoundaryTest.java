package com.warden.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.warden.domain.AccessLevel;
import com.warden.domain.RetrievedChunk;
import com.warden.service.OllamaChatService;
import com.warden.service.RetrievalService;
import com.warden.web.dto.IngestResponse;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.mock.web.MockHttpSession;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
    "WARDEN_REP_PASSWORD_HASH=$2b$04$GlFSY5iQy3dc0HEMLTiKkOy81/Jl7hF/LJ1yUh4HjCjwFWPewMN9u",
    "WARDEN_MANAGER_PASSWORD_HASH=$2b$04$GlFSY5iQy3dc0HEMLTiKkOy81/Jl7hF/LJ1yUh4HjCjwFWPewMN9u"
})
@AutoConfigureMockMvc
class SecurityBoundaryTest {
    private static final String QUESTION = "What is the recovery code?";
    private static final RetrievedChunk PUBLIC = chunk("public");

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper json;
    @MockBean RetrievalService retrieval;
    @MockBean OllamaChatService ollama;

    @Test
    void anonymousCallerCannotQueryAsManager() throws Exception {
        when(retrieval.retrieveAuthorized(QUESTION, AccessLevel.MANAGER)).thenReturn(List.of(PUBLIC));
        when(ollama.answer(eq(QUESTION), anyList())).thenReturn("synthetic answer");

        MockHttpSession session = new MockHttpSession();
        mvc.perform(post("/api/query").session(session).header("X-CSRF-TOKEN", csrf(session)).contentType(MediaType.APPLICATION_JSON)
                .content(queryBody("user-b")))
            .andExpect(status().isUnauthorized());
        verifyNoInteractions(retrieval, ollama);
    }

    @Test
    void repCannotSelectManagerIdentityInRequestBody() throws Exception {
        when(retrieval.retrieveAuthorized(QUESTION, AccessLevel.PUBLIC)).thenReturn(List.of(PUBLIC));
        when(retrieval.retrieveAuthorized(QUESTION, AccessLevel.MANAGER)).thenReturn(List.of(PUBLIC));
        when(ollama.answer(eq(QUESTION), anyList())).thenReturn("synthetic answer");

        MockHttpSession session = login("user-a");
        mvc.perform(post("/api/query").session(session).header("X-CSRF-TOKEN", csrf(session)).contentType(MediaType.APPLICATION_JSON)
                .content(queryBody("user-b")))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.userId").value("user-a"))
            .andExpect(jsonPath("$.clearance").value("PUBLIC"));
    }

    @Test
    void repCannotPublishDocuments() throws Exception {
        when(retrieval.ingest("test.md", "synthetic document", "public"))
            .thenReturn(new IngestResponse("test.md", "policy_docs", "public", 1));

        MockHttpSession session = login("user-a");
        mvc.perform(multipart("/api/documents")
                .file(new MockMultipartFile("file", "test.md", "text/markdown", "synthetic document".getBytes(java.nio.charset.StandardCharsets.UTF_8)))
                .session(session).header("X-CSRF-TOKEN", csrf(session))
                .param("accessLevel", "public"))
            .andExpect(status().isForbidden());
        verifyNoInteractions(retrieval);
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {"manager", "unknown"})
    void invalidUpstreamAccessFailsClosedBeforeOllama(String accessLevel) throws Exception {
        when(retrieval.retrieveAuthorized(QUESTION, AccessLevel.PUBLIC)).thenReturn(List.of(chunk(accessLevel)));
        when(ollama.answer(eq(QUESTION), anyList())).thenReturn("synthetic answer");

        MockHttpSession session = login("user-a");
        mvc.perform(post("/api/query").session(session).header("X-CSRF-TOKEN", csrf(session)).contentType(MediaType.APPLICATION_JSON)
                .content(queryBody("user-a")))
            .andExpect(status().isBadGateway())
            .andExpect(jsonPath("$.answer").doesNotExist())
            .andExpect(jsonPath("$.citedSources").doesNotExist());
        verifyNoInteractions(ollama);
    }

    @Test
    void managerCanPublishAndCsrfIsRequired() throws Exception {
        when(retrieval.ingest("test.md", "synthetic document", "manager"))
            .thenReturn(new IngestResponse("test.md", "policy_docs", "manager", 1));
        MockHttpSession session = login("user-b");
        mvc.perform(multipart("/api/documents")
                .file(new MockMultipartFile("file", "test.md", "text/markdown", "synthetic document".getBytes()))
                .session(session)
                .param("accessLevel", "manager"))
            .andExpect(status().isForbidden());
        verifyNoInteractions(retrieval);
        mvc.perform(multipart("/api/documents")
                .file(new MockMultipartFile("file", "test.md", "text/markdown", "synthetic document".getBytes()))
                .session(session).header("X-CSRF-TOKEN", csrf(session))
                .param("accessLevel", "manager"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.chunksStored").value(1));
    }

    private MockHttpSession login(String username) throws Exception {
        MockHttpSession session = new MockHttpSession();
        return (MockHttpSession) mvc.perform(post("/api/login").session(session)
                .header("X-CSRF-TOKEN", csrf(session))
                .param("username", username).param("password", "warden-test-password"))
            .andExpect(status().isNoContent()).andReturn().getRequest().getSession(false);
    }

    private String csrf(MockHttpSession session) throws Exception {
        return json.readTree(mvc.perform(get("/api/csrf").session(session))
            .andExpect(status().isOk()).andReturn().getResponse().getContentAsString()).get("token").asText();
    }

    private static RetrievedChunk chunk(String accessLevel) {
        return new RetrievedChunk("synthetic", "fixture.md", "policy_docs", accessLevel, "synthetic context", 0.1);
    }

    private static String queryBody(String userId) {
        return """
            {"userId":"%s","question":"%s"}
            """.formatted(userId, QUESTION);
    }
}
