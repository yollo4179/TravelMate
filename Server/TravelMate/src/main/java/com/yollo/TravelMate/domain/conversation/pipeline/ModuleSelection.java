package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.List;
import java.util.function.Predicate;

public final class ModuleSelection {
    private ModuleSelection() {}

    public static <T> T requireOne(List<T> modules, Predicate<T> supports, String role) {
        var matches = modules.stream().filter(supports).toList();
        if (matches.size() != 1) {
            throw new IllegalStateException("Expected exactly one " + role + " module; found " + matches.size());
        }
        return matches.get(0);
    }
}
