package com.yollo.TravelMate.domain.conversation.pipeline;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.springframework.core.io.ResourceLoader;

/** Stateless loading and {{token}} rendering for local prompt/query resources. */
public final class PromptTemplates {
    private static final Pattern TOKEN = Pattern.compile("\\{\\{([A-Za-z]+)}}");

    private PromptTemplates() {}

    public static String load(ResourceLoader resources, String location) {
        try (var stream = resources.getResource(location).getInputStream()) {
            String text = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
            if (text.isBlank()) throw new IllegalArgumentException("Prompt resource cannot be blank: " + location);
            return text;
        } catch (IOException exception) {
            throw new IllegalStateException("Prompt resource unavailable: " + location, exception);
        }
    }

    /** Unknown tokens fail at startup so literal braces or stale values never reach the model. */
    public static String render(String template, Map<String, String> values) {
        Matcher matcher = TOKEN.matcher(template);
        StringBuilder rendered = new StringBuilder();
        while (matcher.find()) {
            String value = values.get(matcher.group(1));
            if (value == null) throw new IllegalArgumentException("Unknown prompt token: " + matcher.group(1));
            matcher.appendReplacement(rendered, Matcher.quoteReplacement(value));
        }
        matcher.appendTail(rendered);
        return rendered.toString();
    }

    public static String sha256(String text) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 unavailable", exception);
        }
    }
}
