package com.warden.web;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * The React UI (warden-ui/, served by Vite on its own dev-server port) runs
 * on a different origin than this API, so the browser needs CORS opened up
 * for it. Also exposes X-Trace-Id (see TraceIdFilter) so the UI can show
 * the trace id for a request next to its chat response.
 */
@Configuration
public class CorsConfig implements WebMvcConfigurer {

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**")
                .allowedOrigins("http://localhost:5173", "http://127.0.0.1:5173")
                .allowedMethods("GET", "POST", "OPTIONS")
                .allowedHeaders("*")
                .exposedHeaders(TraceIdFilter.TRACE_ID_HEADER);
    }
}
