package com.warden.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import com.warden.guard.EvidenceWriter;
import com.warden.guard.SecurityEvidence;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Assigns a short traceId to every incoming request, before anything else
 * runs. The id is put in MDC so every log line for this request - not just
 * QueryService's summary line - can be correlated back to it, and it is
 * echoed on the response as X-Trace-Id so a caller (e.g. Postman) can match
 * their request to the server logs for it.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TraceIdFilter extends OncePerRequestFilter {
    private final EvidenceWriter evidenceWriter;

    public TraceIdFilter(EvidenceWriter evidenceWriter) { this.evidenceWriter = evidenceWriter; }

    public static final String TRACE_ID_MDC_KEY = "traceId";
    public static final String TRACE_ID_HEADER = "X-Trace-Id";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String traceId = UUID.randomUUID().toString();
        MDC.put(TRACE_ID_MDC_KEY, traceId);
        response.setHeader(TRACE_ID_HEADER, traceId);
        SecurityEvidence evidence = evidenceWriter.enabled() && request.getRequestURI().equals("/api/query")
            ? new SecurityEvidence(traceId) : null;
        if (evidence != null) SecurityEvidence.bind(evidence);
        try {
            filterChain.doFilter(request, response);
        } finally {
            try {
                if (evidence != null) evidenceWriter.write(evidence);
            } catch (IOException error) {
                // Do not log exception details: paths or response data may be sensitive.
                org.slf4j.LoggerFactory.getLogger(TraceIdFilter.class).warn("Guard evidence write failed; security evaluation must fail");
            } finally { SecurityEvidence.clear(); }
            MDC.remove(TRACE_ID_MDC_KEY);
        }
    }
}
