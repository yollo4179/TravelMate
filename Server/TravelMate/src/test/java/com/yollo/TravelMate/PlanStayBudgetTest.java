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

/** The plan prompt asks for exactly as many stops as the validator's stay-and-walk rule accepts. */
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

    // r3 and var4 drafts: 창경궁 60 min + another 60 min filled all 120 minutes and left no time to walk between them.
    @Test
    void twoHoursWithAnHourAlreadyRequiredLeaveNoRoomForASecondStopOnceWalkingIsCounted() throws Exception {
        var request = mapper.readValue(TWO_HOUR_REQUEST, GeneratePlanRequest.class);
        assertEquals(1, PlanStayBudget.maxStops(request));
        assertEquals(60 + PlanStayBudget.WALKING_LEG_MINUTES, PlanStayBudget.requiredMinutes(List.of(378L), request));
        assertTrue(PlanStayBudget.requiredMinutes(List.of(378L, 380L), request) > PlanStayBudget.availableMinutes(request),
                "the live two-stop draft is exactly what the validator now rejects");
    }

    @Test
    void threeHoursFitTwoRelaxedStopsWithTheirWalks() throws Exception {
        var request = mapper.readValue(TWO_HOUR_REQUEST.replace("12:00:00", "13:00:00"), GeneratePlanRequest.class);
        assertEquals(2, PlanStayBudget.maxStops(request));
    }

    @Test
    void aDestinationAddsTheLastLeg() throws Exception {
        String toDestination = TWO_HOUR_REQUEST.replace("12:00:00", "12:30:00").replace("\"destination\":null",
                "\"destination\":{\"coordinate\":{\"lat\":37.57,\"lon\":126.98},\"label\":\"도착\",\"source\":\"SELECTED_POINT\"}");
        var request = mapper.readValue(toDestination, GeneratePlanRequest.class);
        assertEquals(2, PlanStayBudget.legs(1, request));
        assertEquals(1, PlanStayBudget.maxStops(request), "two stops would need 60 + 60 + three 15-minute legs in 150 minutes");
    }

    @Test
    void thePromptStatesTheBudgetAndThatTheWalkIsNotMeasured() throws Exception {
        var request = mapper.readValue(TWO_HOUR_REQUEST, GeneratePlanRequest.class);
        String prompt = new ContextPlanPromptFactory(mapper).prepare(request, List.of(), List.of()).userPrompt();
        assertTrue(prompt.contains("최대 1개 장소"), prompt);
        assertTrue(prompt.contains("120분"));
        assertTrue(prompt.contains("구간마다 " + PlanStayBudget.WALKING_LEG_MINUTES + "분"));
        assertTrue(prompt.contains("실제 경로로 확인한 값이 아니다"));
        assertTrue(prompt.contains("빡빡하지 않다"), "the draft may not call an unchecked schedule relaxed");
        assertFalse(prompt.contains("최대 6개 장소"));
    }

    @Test
    void aLongDayIsStillCappedAtSixStops() throws Exception {
        var request = mapper.readValue(TWO_HOUR_REQUEST.replace("12:00:00", "22:00:00"), GeneratePlanRequest.class);
        assertEquals(PlanStayBudget.MAX_STOPS, PlanStayBudget.maxStops(request));
    }
}
