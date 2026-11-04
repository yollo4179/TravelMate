package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.EnumMap;
import java.util.Map;
import org.springframework.core.io.DefaultResourceLoader;

/** Rendered LiLi system prompts. They belong to LILI_ROUTER_V1, so a new behavior gets a new versioned file. */
public final class LiliPrompts {
    public enum Prompt {
        ROUTER("classpath:conversation/prompts/v1-lili-router-system.txt"),
        FOLLOWUP("classpath:conversation/prompts/v1-lili-followup-system.txt"),
        RECOMMENDATION("classpath:conversation/prompts/v1-recommendation-system.txt");

        private final String resource;

        Prompt(String resource) {
            this.resource = resource;
        }

        public String resource() {
            return resource;
        }
    }

    private LiliPrompts() {}

    public static String text(Prompt prompt) {
        return Holder.RENDERED.get(prompt);
    }

    public static String sha256(Prompt prompt) {
        return PromptTemplates.sha256(text(prompt));
    }

    private static final class Holder {
        private static final Map<Prompt, String> RENDERED = render();

        private static Map<Prompt, String> render() {
            var loader = new DefaultResourceLoader();
            var rendered = new EnumMap<Prompt, String>(Prompt.class);
            for (Prompt prompt : Prompt.values()) {
                rendered.put(prompt, PromptTemplates.render(PromptTemplates.load(loader, prompt.resource()), PromptVocabulary.tokens()));
            }
            return Map.copyOf(rendered);
        }
    }
}
