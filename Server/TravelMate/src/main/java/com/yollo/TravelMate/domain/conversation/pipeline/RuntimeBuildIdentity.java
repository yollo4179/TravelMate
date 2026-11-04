package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.Properties;
import org.springframework.core.io.ClassPathResource;

/** Built from source bytes, not an unverified manually supplied Git revision. */
public final class RuntimeBuildIdentity {
    private RuntimeBuildIdentity() {}
    public static String sourceSha256() {
        try (var stream = new ClassPathResource("pipeline-identity.properties").getInputStream()) {
            var properties = new Properties();
            properties.load(stream);
            return java.util.Objects.requireNonNull(properties.getProperty("source.sha256"));
        } catch (Exception failure) {
            throw new IllegalStateException("Runtime source identity unavailable", failure);
        }
    }
}
