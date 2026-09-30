package com.warden.domain;

import java.util.ArrayList;
import java.util.List;

/**
 * Access tiers, matching the values data/ground/ingestion.py actually
 * writes into each chunk's `access_level` metadata: lowercase "public" and
 * "manager" - not the earlier three-tier PUBLIC/MANAGER_ONLY/CONFIDENTIAL
 * scheme. wireValue() is what gets sent to the Python retrieval service;
 * it must equal those metadata strings exactly or the filter silently
 * matches nothing.
 */
public enum AccessLevel {
    PUBLIC(0, "public"),
    MANAGER(1, "manager");

    private final int rank;
    private final String wireValue;

    AccessLevel(int rank, String wireValue) {
        this.rank = rank;
        this.wireValue = wireValue;
    }

    public int rank() {
        return rank;
    }

    public String wireValue() {
        return wireValue;
    }

    /**
     * Every access level (as the Python service's wire values) a user with
     * this clearance may see, inclusive.
     */
    public List<String> allowedLevelsUpToInclusive() {
        List<String> allowed = new ArrayList<>();
        for (AccessLevel level : values()) {
            if (level.rank <= this.rank) {
                allowed.add(level.wireValue);
            }
        }
        return allowed;
    }
}
