package com.yollo.TravelMate.domain.place.data.result;

import java.util.List;
import com.yollo.TravelMate.domain.place.data.internal.Sido;

/**
 * The regions and categories the place data actually holds. UNKNOWN means the server could not read them, and then
 * nothing is refused on coverage: the search runs as it did before the check existed.
 */
public record PlaceCoverage(
        List<Sido> regions,
        List<String> categories
) {
    public static final PlaceCoverage UNKNOWN = new PlaceCoverage(List.of(), List.of());

    public PlaceCoverage {
        regions = List.copyOf(regions);
        categories = List.copyOf(categories);
    }

    public boolean known() {
        return !regions.isEmpty();
    }

    /** Only a known coverage can rule a region out. */
    public boolean excludes(Sido region) {
        return known() && region != null && !regions.contains(region);
    }

    public List<String> regionLabels() {
        return regions.stream().map(Sido::label).toList();
    }

    /** The form LiLi reads: the labels users and the data use, not enum names. */
    public Facts facts() {
        return new Facts(regionLabels(), categories);
    }

    public record Facts(
            List<String> regions,
            List<String> categories
    ) {}
}
