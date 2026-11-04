package com.yollo.TravelMate.domain.conversation.pipeline;

import org.springframework.core.io.DefaultResourceLoader;

/** The one LiLi persona shared by the router, follow-up, recommendation and plan prompts. */
public final class LiliPersona {
    public static final String RESOURCE = "classpath:conversation/persona/lili-v1.txt";

    private LiliPersona() {}

    public static String text() {
        return Holder.TEXT;
    }

    // Loaded once on first use; a missing persona fails before any model call.
    private static final class Holder {
        private static final String TEXT = PromptTemplates.load(new DefaultResourceLoader(), RESOURCE).strip();
    }
}
