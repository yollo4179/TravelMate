package com.yollo.TravelMate;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.yollo.TravelMate.jwt.JwtTokenProvider;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.test.util.ReflectionTestUtils;
import static org.junit.jupiter.api.Assertions.*;

class JwtTokenProviderLoggingTest {
    private static final String SECRET = "test-only-signing-secret-that-is-long-enough-123";

    @Test
    void initializationNeverLogsTheSigningSecretOrItsEncoding() {
        var logger = (Logger) LoggerFactory.getLogger(JwtTokenProvider.class);
        var appender = new ListAppender<ILoggingEvent>();
        appender.start();
        logger.addAppender(appender);
        Level previous = logger.getLevel();
        // DEBUG as well: a debug line is still written wherever debug logging is enabled.
        logger.setLevel(Level.DEBUG);
        try {
            var provider = new JwtTokenProvider();
            ReflectionTestUtils.setField(provider, "secretKey", SECRET);
            ReflectionTestUtils.invokeMethod(provider, "init");
            String encoded = Base64.getEncoder().encodeToString(SECRET.getBytes(StandardCharsets.UTF_8));
            assertFalse(appender.list.isEmpty(), "initialization should still report that the key is ready");
            assertTrue(appender.list.stream().map(ILoggingEvent::getFormattedMessage)
                    .noneMatch(message -> message.contains(SECRET) || message.contains(encoded)));
        } finally {
            logger.detachAppender(appender);
            logger.setLevel(previous);
        }
    }
}
