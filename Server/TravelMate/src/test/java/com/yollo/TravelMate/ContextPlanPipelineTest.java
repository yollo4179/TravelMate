package com.yollo.TravelMate;

import java.util.List;
import java.util.Set;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.validator.ContextPlanResultValidator;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ContextPlanPipelineTest {
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();

    @Test
    void qwenInputContainsFullContextAndOnlyRetrievedCandidates() throws Exception {
        var request = mapper.readValue(PlanContextContractTest.REQUEST, GeneratePlanRequest.class);
        var place = new PlaceResult(101L, "문화관", "소개".repeat(1000), "지역", "도시", "문화시설", null,
                35.84, 129.21, 0.9, null, null, null);
        String prompt = new ContextPlanPromptFactory(mapper).create(request, List.of(place));
        var payload = mapper.readTree(prompt.substring(prompt.indexOf('{')));
        assertEquals(request, mapper.treeToValue(payload.get("request"), GeneratePlanRequest.class));
        assertEquals(1, payload.get("candidates").size());
        assertEquals(101, payload.get("candidates").get(0).get("placeId").asLong());
        assertTrue(payload.get("candidates").get(0).get("description").asText().length() <= 400);
    }

    @Test
    void refusesHallucinatedDuplicateAndMissingRequiredStops() throws Exception {
        var request = mapper.readValue(PlanContextContractTest.REQUEST, GeneratePlanRequest.class);
        var validator = new ContextPlanResultValidator(mapper);
        for (String pins : List.of(
                "[{\"placeId\":999,\"sequence\":1}]",
                "[{\"placeId\":102,\"sequence\":1}]",
                "[{\"placeId\":101,\"sequence\":1},{\"placeId\":101,\"sequence\":2}]",
                "[{\"placeId\":101,\"sequence\":4}]"
        )) {
            assertThrows(IllegalStateException.class, () -> validator.validate(
                    "{\"planTitle\":\"여행\",\"planDescription\":\"초안\",\"pins\":" + pins + "}",
                    Set.of(101L, 102L), request
            ));
        }
        assertEquals(101L, validator.validate(
                "{\"planTitle\":\"여행\",\"pins\":[{\"placeId\":101,\"sequence\":1}]}",
                Set.of(101L), request
        ).pins().get(0).placeId());
    }
}
