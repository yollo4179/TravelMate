package com.yollo.TravelMate;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import jakarta.validation.Validation;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PlanContextContractTest {
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();
    static final String REQUEST = """
            {"context":{
              "area":{"type":"CIRCLE","center":{"lat":35.8395,"lon":129.212},"radiusMeters":3000},
              "origin":{"coordinate":{"lat":35.8401,"lon":129.214},"label":"출발지","source":"SELECTED_POINT"},
              "startAt":"2026-10-20T10:00:00+09:00","endAt":"2026-10-20T17:00:00+09:00",
              "transportMode":"WALK","objective":"DISTANCE",
              "preferences":{"themes":["문화","산책"],"avoid":["등산"],"pace":"RELAXED","partySize":1},
              "categoryRequirements":[{"category":"CAFE","minCount":1}],
              "additionalRequest":"문화와 산책","unknownHoursPolicy":"ALLOW_WITH_WARNING"
            },"inputMethod":"TEXT","requiredStops":[{"placeId":101,"stayMinutes":60}]}
            """;

    @Test
    void acceptsPdfFieldsAndPreservesCoordinateAndTimezone() throws Exception {
        var request = mapper.readValue(REQUEST, GeneratePlanRequest.class);
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            assertTrue(factory.getValidator().validate(request).isEmpty());
        }
        assertNotEquals(request.context().area().center(), request.context().origin().coordinate());
        assertEquals(9 * 3600, request.context().startAt().getOffset().getTotalSeconds());
        assertEquals(60, request.requiredStops().get(0).stayMinutes());
    }

    @Test
    void rejectsInvalidNestedCoordinatesRadiusAndTime() throws Exception {
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            for (String invalid : java.util.List.of(
                    REQUEST.replace("35.8395", "135.8395"),
                    REQUEST.replace("3000", "0"),
                    REQUEST.replace("T17:00", "T09:00"),
                    REQUEST.replace("T17:00", "T23:00")
            )) {
                assertFalse(factory.getValidator().validate(mapper.readValue(invalid, GeneratePlanRequest.class)).isEmpty());
            }
        }
    }
}
