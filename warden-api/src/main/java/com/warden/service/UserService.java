package com.warden.service;

import com.warden.domain.AccessLevel;
import com.warden.domain.WardenUser;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * Stands in for a real login/identity system. Two fake users: a support
 * rep with PUBLIC-only clearance, and a manager with MANAGER clearance
 * (which also covers PUBLIC, per AccessLevel#allowedLevelsUpToInclusive).
 */
@Service
public class UserService {

    private final Map<String, WardenUser> users = Map.of(
            "user-a", new WardenUser("user-a", "Jamie Alvarez", "support-rep", AccessLevel.PUBLIC),
            "user-b", new WardenUser("user-b", "Morgan Chen", "manager", AccessLevel.MANAGER)
    );

    public WardenUser require(String userId) {
        WardenUser user = users.get(userId);
        if (user == null) {
            throw new NoSuchUserException(userId);
        }
        return user;
    }

    public List<WardenUser> listAll() {
        return List.copyOf(users.values());
    }

    public static class NoSuchUserException extends RuntimeException {
        public NoSuchUserException(String userId) {
            super("No such user: " + userId);
        }
    }
}
