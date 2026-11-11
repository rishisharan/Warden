package com.warden.config;

import jakarta.servlet.DispatcherType;
import jakarta.servlet.http.HttpServletResponse;
import java.util.ArrayList;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.provisioning.InMemoryUserDetailsManager;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
public class SecurityConfig {
    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        return http.cors(Customizer.withDefaults())
            .authorizeHttpRequests(auth -> auth
                .dispatcherTypeMatchers(DispatcherType.ERROR).permitAll()
                .requestMatchers(HttpMethod.GET, "/api/csrf").permitAll()
                .requestMatchers(HttpMethod.POST, "/api/documents").hasRole("MANAGER")
                .requestMatchers("/api/**").authenticated()
                .anyRequest().denyAll())
            .exceptionHandling(errors -> errors.authenticationEntryPoint(
                (request, response, failure) -> response.setStatus(HttpServletResponse.SC_UNAUTHORIZED)))
            .formLogin(login -> login.loginProcessingUrl("/api/login")
                .successHandler((request, response, auth) -> response.setStatus(HttpServletResponse.SC_NO_CONTENT))
                .failureHandler((request, response, failure) -> response.setStatus(HttpServletResponse.SC_UNAUTHORIZED))
                .permitAll())
            .logout(logout -> logout.logoutUrl("/api/logout")
                .logoutSuccessHandler((request, response, auth) -> response.setStatus(HttpServletResponse.SC_NO_CONTENT)))
            .build();
    }

    @Bean
    PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    InMemoryUserDetailsManager users(
            @Value("${WARDEN_REP_PASSWORD_HASH:}") String repHash,
            @Value("${WARDEN_MANAGER_PASSWORD_HASH:}") String managerHash) {
        List<UserDetails> accounts = new ArrayList<>();
        if (!repHash.isBlank()) accounts.add(User.withUsername("user-a").password(repHash).roles("SUPPORT_REP").build());
        if (!managerHash.isBlank()) accounts.add(User.withUsername("user-b").password(managerHash).roles("MANAGER").build());
        return new InMemoryUserDetailsManager(accounts);
    }
}
