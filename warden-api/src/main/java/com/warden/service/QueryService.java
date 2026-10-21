package com.warden.service;

import com.warden.domain.RetrievedChunk;
import com.warden.guard.SecurityEvidence;
import com.warden.domain.WardenUser;
import com.warden.web.dto.CitedSource;
import com.warden.web.dto.QueryResponse;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class QueryService {

    private static final Logger log = LoggerFactory.getLogger(QueryService.class);

    private final UserService userService;
    private final RetrievalService retrievalService;
    private final OllamaChatService chatService;

    public QueryService(UserService userService, RetrievalService retrievalService, OllamaChatService chatService) {
        this.userService = userService;
        this.retrievalService = retrievalService;
        this.chatService = chatService;
    }

    public QueryResponse answer(String traceId, String userId, String question) {
        long totalStart = System.currentTimeMillis();

        WardenUser user = userService.require(userId);
        SecurityEvidence evidence = SecurityEvidence.current();
        if (evidence != null) {
            evidence.userId = user.userId();
            evidence.allowed = user.clearance().allowedLevelsUpToInclusive();
        }
        List<RetrievedChunk> authorized = retrievalService.retrieveAuthorized(question, user.clearance());
        if (authorized.isEmpty()) {
            if (evidence != null) evidence.modelContextComplete = true;
            long totalDuration = System.currentTimeMillis() - totalStart;
            log.info("traceId={} retrievedChunks=0 model={} totalDuration={}ms", traceId, chatService.model(), totalDuration);

            return new QueryResponse(
                    userId,
                    user.role(),
                    user.clearance().name(),
                    "I don't have authorized information to answer that question.",
                    List.of()
            );
        }

        long llmStart = System.currentTimeMillis();
        String answer = chatService.answer(question, List.of(authorized.get(0)));
        long llmDuration = System.currentTimeMillis() - llmStart;

        Set<CitedSource> cited = new LinkedHashSet<>();
        for (RetrievedChunk chunk : authorized) {
            cited.add(new CitedSource(chunk.sourceFile(), chunk.sourceType(), chunk.accessLevel()));
        }

        long totalDuration = System.currentTimeMillis() - totalStart;

        log.info("traceId={} retrievedChunks={} topDistance={} model={} llmDuration={}ms totalDuration={}ms",
                traceId,
                authorized.size(),
                String.format("%.3f", authorized.get(0).distance()),
                chatService.model(),
                llmDuration,
                totalDuration);

        return new QueryResponse(userId, user.role(), user.clearance().name(), answer, List.copyOf(cited));
    }
}
