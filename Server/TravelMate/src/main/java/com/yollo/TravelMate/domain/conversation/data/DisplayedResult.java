package com.yollo.TravelMate.domain.conversation.data;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

/**
 * The recommendation result the user is looking at, in the order the app shows it. "첫 번째" always means
 * position 1 of this list; the server never infers the order from a new search.
 */
public record DisplayedResult(
        @NotNull UUID resultId,
        @NotNull @Size(min = 1, max = MAX_PLACES) List<@NotNull @Positive Long> placeIds
) {
    public static final int MAX_PLACES = 20;
    public static final int FIRST_POSITION = 1;

    public DisplayedResult {
        placeIds = placeIds == null ? null : List.copyOf(placeIds);
        if (placeIds != null && placeIds.stream().distinct().count() != placeIds.size()) {
            throw new IllegalArgumentException("Duplicate displayed place IDs");
        }
    }

    public Optional<Long> placeAt(int position) {
        if (position < FIRST_POSITION || position > placeIds.size()) return Optional.empty();
        return Optional.of(placeIds.get(position - FIRST_POSITION));
    }
}
