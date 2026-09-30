package com.warden.domain;

/**
 * A fake user standing in for a real login system - see UserService.
 * clearance is the highest AccessLevel this user may see.
 */
public record WardenUser(
        String userId,
        String displayName,
        String role,
        AccessLevel clearance
) {
}
