package com.yollo.TravelMate.domain.conversation.pipeline;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Component;

@Component
public class ResourcePromptV1 implements PromptModule {
    private final String prompt;
    private final String fingerprint;

    public ResourcePromptV1(ConversationModuleConfig config, ResourceLoader resources) {
        try (var stream = resources.getResource(config.promptResource()).getInputStream()) {
            byte[] original = stream.readAllBytes();
            prompt = new String(original, StandardCharsets.UTF_8);
            if (prompt.isBlank()) throw new IllegalArgumentException("Conversation prompt cannot be blank");
            fingerprint = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(original));
        } catch (IOException | NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Conversation prompt resource unavailable", exception);
        }
    }

    @Override
    public boolean supports(Version version) {
        return version == Version.RESOURCE_V1;
    }

    @Override
    public String execute(ConversationRequest input, ConversationModuleConfig config) {
        return prompt;
    }

    @Override
    public String sha256() {
        return fingerprint;
    }
}
