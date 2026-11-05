package com.yollo.TravelMate.domain.place.service;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.List;
import com.yollo.TravelMate.domain.place.data.internal.Sido;
import com.yollo.TravelMate.domain.place.data.result.PlaceCoverage;
import com.yollo.TravelMate.domain.place.repository.PlaceCoverageRepository;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class PlaceCoverageServiceTest {
    private final PlaceCoverageRepository repository = mock(PlaceCoverageRepository.class);
    private final MovableClock clock = new MovableClock(Instant.parse("2026-11-05T00:00:00Z"));
    private final PlaceCoverageService service = new PlaceCoverageService(repository, clock);

    @Test
    void coverageIsReadFromThePlaceData() {
        when(repository.regions()).thenReturn(List.of("서울"));
        when(repository.categories()).thenReturn(List.of("관광지"));
        var coverage = service.current();
        assertEquals(List.of(Sido.SEOUL), coverage.regions());
        assertTrue(coverage.excludes(Sido.BUSAN));
        assertFalse(coverage.excludes(Sido.SEOUL));
        assertEquals(new PlaceCoverage.Facts(List.of("서울"), List.of("관광지")), coverage.facts());
    }

    // "서울특별시" would make every request look outside the data, so nothing is refused instead.
    @Test
    void aRegionLabelTheServerCannotNameTurnsTheCheckOff() {
        when(repository.regions()).thenReturn(List.of("서울특별시"));
        assertFalse(service.current().known());
        assertFalse(service.current().excludes(Sido.BUSAN));
    }

    @Test
    void anUnreadableDatabaseTurnsTheCheckOff() {
        when(repository.regions()).thenThrow(new DataAccessResourceFailureException("down"));
        assertSame(PlaceCoverage.UNKNOWN, service.current());
    }

    @Test
    void theDataIsRereadOnlyAfterTheRefreshInterval() {
        when(repository.regions()).thenReturn(List.of("서울"));
        when(repository.categories()).thenReturn(List.of("관광지"));
        service.current();
        service.current();
        verify(repository, times(1)).regions();
        clock.advance(PlaceCoverageService.REFRESH.plusSeconds(1));
        when(repository.regions()).thenReturn(List.of("부산", "서울"));
        assertEquals(List.of(Sido.BUSAN, Sido.SEOUL), service.current().regions(), "new imports are picked up without a restart");
    }

    private static final class MovableClock extends Clock {
        private Instant now;

        private MovableClock(Instant now) {
            this.now = now;
        }

        void advance(java.time.Duration duration) {
            now = now.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return now;
        }
    }
}
