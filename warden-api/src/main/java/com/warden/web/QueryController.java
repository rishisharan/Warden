package com.warden.web;

import com.warden.domain.WardenUser;
import com.warden.service.QueryService;
import com.warden.service.UserService;
import com.warden.web.dto.QueryRequest;
import com.warden.web.dto.QueryResponse;
import jakarta.validation.Valid;
import java.util.List;
import org.slf4j.MDC;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class QueryController {

    private final QueryService queryService;
    private final UserService userService;

    public QueryController(QueryService queryService, UserService userService) {
        this.queryService = queryService;
        this.userService = userService;
    }

    @PostMapping("/query")
    public QueryResponse query(@Valid @RequestBody QueryRequest request) {
        String traceId = MDC.get(TraceIdFilter.TRACE_ID_MDC_KEY);
        return queryService.answer(traceId, request.userId(), request.question());
    }

    /** Lists the fake users (and their clearance) - stands in for a login screen. */
    @GetMapping("/users")
    public List<WardenUser> users() {
        return userService.listAll();
    }
}
