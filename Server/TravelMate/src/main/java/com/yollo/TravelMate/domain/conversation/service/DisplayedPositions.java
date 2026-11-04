package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.Optional;
import com.yollo.TravelMate.domain.conversation.data.DisplayedResult;

/** Maps LiLi's 1-based positions onto the list the app displayed; a position that names nothing is never guessed. */
public final class DisplayedPositions {
    public enum Status {
        NONE_REQUESTED,
        RESOLVED,
        NO_DISPLAYED_RESULT,
        POSITION_OUT_OF_RANGE
    }

    public record Resolution(Status status, List<Integer> positions, List<Long> placeIds) {
        public boolean usable() {
            return status == Status.NONE_REQUESTED || status == Status.RESOLVED;
        }
    }

    private DisplayedPositions() {}

    public static Resolution resolve(DisplayedResult displayed, List<Integer> positions) {
        var requested = positions.stream().distinct().toList();
        if (requested.isEmpty()) return new Resolution(Status.NONE_REQUESTED, requested, List.of());
        if (displayed == null) return new Resolution(Status.NO_DISPLAYED_RESULT, requested, List.of());
        var placeIds = requested.stream().map(displayed::placeAt).flatMap(Optional::stream).toList();
        if (placeIds.size() != requested.size()) return new Resolution(Status.POSITION_OUT_OF_RANGE, requested, List.of());
        return new Resolution(Status.RESOLVED, requested, placeIds);
    }
}
