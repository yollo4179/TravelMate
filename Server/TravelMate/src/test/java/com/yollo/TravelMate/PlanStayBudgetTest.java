package com.yollo.TravelMate;

import java.util.List;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.validator.PlanStayBudget;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** The plan prompt asks for exactly as many stops as the validator's stay-time rule accepts. */
class PlanStayBudgetTest {
    // The live CONV-PLAN-create conditions: two hours, a relaxed pace, 창경궁 required for 60 minutes.
    private static final String TWO_HOUR_REQUEST = """
            {"context":{"area":{"type":"CIRCLE","center":{"lat":37.58,"lon":126.99},"radiusMeters":2000,"regionId":null},
             "origin":{"coordinate":{"lat":37.58,"lon":126.99},"label":"종로 출발 지점","source":"SELECTED_POINT"},
             "destination":null,"startAt":"2027-01-15T10:00:00+09:00","endAt":"2027-01-15T12:00:00+09:00",
             "transportMode":"WALK","objective":"DURATION",
             "preferences":{"themes":["역사"],"avoid":[],"pace":"RELAXED","partySize":2,"budgetKrw":null},
             "categoryRequirements":[],"additionalRequest":null,"unknownHoursPolicy":"ALLOW_WITH_WARNING"},
             "inputMethod":"TEXT","requiredStops":[{"placeId":378,"stayMinutes":60,"fixedStartAt":null}]}
            """;
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();

    @Test
    void twoHoursWithAnHourAlreadyRequiredLeavesRoomForOneMoreRelaxedStop() throws Exception {
        var request = mapper.readValue(TWO_HOUR_REQUEST, GeneratePlanRequest.class);
        assertEquals(2, PlanStayBudget.maxStops(request));
        assertTrue(PlanStayBudget.totalStayMinutes(List.of(378L, 380L), request) <= PlanStayBudget.availableMinutes(request));
        assertTrue(PlanStayBudget.totalStayMinutes(List.of(378L, 380L, 379L), request) > PlanStayBudget.availableMinutes(request),
                "one stop past the budget is exactly what the validator rejects");
    }

    @Test
    void thePromptStatesTheBudgetInsteadOfAFixedSixStops() throws Exception {
        var request = mapper.readValue(TWO_HOUR_REQUEST, GeneratePlanRequest.class);
        String prompt = new ContextPlanPromptFactory(mapper).prepare(request, List.of(), List.of()).userPrompt();
        assertTrue(prompt.contains("최대 2개 장소"), prompt);
        assertTrue(prompt.contains("120분"));
        assertFalse(prompt.contains("최대 6개 장소"));
    }

    @Test
    void aLongDayIsStillCappedAtSixStops() throws Exception {
        var request = mapper.readValue(TWO_HOUR_REQUEST.replace("12:00:00", "22:00:00"), GeneratePlanRequest.class);
        assertEquals(PlanStayBudget.MAX_STOPS, PlanStayBudget.maxStops(request));
    }
}
