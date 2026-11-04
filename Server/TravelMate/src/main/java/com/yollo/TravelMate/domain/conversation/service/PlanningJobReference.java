package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;
import java.util.regex.Pattern;

/** The job ID always comes from the user's own words, never from a model; the router and the lookup share this rule. */
public final class PlanningJobReference {
    // Not \b: Java treats Hangul as word characters, so "<id>의" would never match.
    private static final Pattern JOB_ID = Pattern.compile(
            "(?<![0-9a-fA-F-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F-])");

    private PlanningJobReference() {}

    /** Present only when the message names exactly one job; none or several means the server must ask. */
    public static Optional<UUID> single(String message) {
        List<String> ids = JOB_ID.matcher(message).results()
                .map(match -> match.group().toLowerCase(Locale.ROOT))
                .distinct()
                .toList();
        return ids.size() == 1 ? Optional.of(UUID.fromString(ids.get(0))) : Optional.empty();
    }
}
