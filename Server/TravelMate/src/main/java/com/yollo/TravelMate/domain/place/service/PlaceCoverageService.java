package com.yollo.TravelMate.domain.place.service;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import com.yollo.TravelMate.domain.place.data.internal.Sido;
import com.yollo.TravelMate.domain.place.data.result.PlaceCoverage;
import com.yollo.TravelMate.domain.place.repository.PlaceCoverageRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/**
 * What the place data covers, read from the data itself so it follows new imports without a code change.
 * It is reread at most every few minutes; every conversation turn reads it.
 */
@Service
@Slf4j
public class PlaceCoverageService {
    static final Duration REFRESH = Duration.ofMinutes(10);

    private record Snapshot(PlaceCoverage coverage, Instant loadedAt) {}

    private final PlaceCoverageRepository repository;
    private final Clock clock;
    private volatile Snapshot snapshot;

    @Autowired
    public PlaceCoverageService(PlaceCoverageRepository repository) {
        this(repository, Clock.systemUTC());
    }

    PlaceCoverageService(
            PlaceCoverageRepository repository,
            Clock clock
    ) {
        this.repository = repository;
        this.clock = clock;
    }

    public PlaceCoverage current() {
        var cached = snapshot;
        Instant now = clock.instant();
        if (cached != null && cached.loadedAt().plus(REFRESH).isAfter(now)) return cached.coverage();
        var loaded = load();
        snapshot = new Snapshot(loaded, now);
        return loaded;
    }

    private PlaceCoverage load() {
        try {
            List<String> stored = repository.regions();
            List<Optional<Sido>> regions = stored.stream().map(Sido::fromLabel).toList();
            // A region the server cannot name would make every request look outside the data; check nothing instead.
            if (regions.stream().anyMatch(Optional::isEmpty)) {
                log.warn("place coverage unknown: unrecognised region labels {}", stored);
                return PlaceCoverage.UNKNOWN;
            }
            return new PlaceCoverage(regions.stream().map(Optional::get).toList(), repository.categories());
        } catch (RuntimeException exception) {
            log.warn("place coverage unknown: {}", exception.toString());
            return PlaceCoverage.UNKNOWN;
        }
    }
}
