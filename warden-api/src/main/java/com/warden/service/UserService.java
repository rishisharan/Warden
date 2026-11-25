package com.warden.service;

import com.warden.domain.AccessLevel;
import com.warden.domain.WardenUser;
import java.util.Map;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;

/** Resolves query clearance from the current account, even for an existing session. */
@Service
public class UserService {

    private static final Map<String, String> DISPLAY_NAMES = Map.of(
            "user-a", "Jamie Alvarez", "user-b", "Morgan Chen");

    private final UserDetailsService accounts;

    public UserService(UserDetailsService accounts) {
        this.accounts = accounts;
    }

    public WardenUser require(String userId) {
        UserDetails account;
        try {
            account = accounts.loadUserByUsername(userId);
        } catch (UsernameNotFoundException ignored) {
            throw new NoSuchUserException(userId);
        }
        if (!account.isEnabled() || !account.isAccountNonLocked() || !account.isAccountNonExpired()) {
            throw new NoSuchUserException(userId);
        }
        boolean manager = account.getAuthorities().stream()
                .anyMatch(authority -> "ROLE_MANAGER".equals(authority.getAuthority()));
        return new WardenUser(userId, DISPLAY_NAMES.getOrDefault(userId, userId),
                manager ? "manager" : "support-rep", manager ? AccessLevel.MANAGER : AccessLevel.PUBLIC);
    }

    public static class NoSuchUserException extends RuntimeException {
        public NoSuchUserException(String userId) {
            super("No such user: " + userId);
        }
    }
}
