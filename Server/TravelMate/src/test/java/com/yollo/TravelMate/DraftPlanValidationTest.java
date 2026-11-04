package com.yollo.TravelMate;

import java.util.List;
import java.util.UUID;
import java.util.stream.IntStream;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.place.service.PlaceSemanticSearchService;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse;
import com.yollo.TravelMate.domain.plan.prompts.ContextPlanPromptFactory;
import com.yollo.TravelMate.domain.plan.repository.ContextPlanRepository;
import com.yollo.TravelMate.domain.plan.repository.PlanningJobRepository;
import com.yollo.TravelMate.domain.plan.service.ContextPlanningService;
import com.yollo.TravelMate.domain.plan.validator.ContextPlanResultValidator;
import com.yollo.TravelMate.domain.plan.validator.DraftPlanValidator;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class DraftPlanValidationTest {
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();

    private enum Outcome {
        ACCEPT(null),
        STAY("방문 체류시간과 이동 여유를 합하면 여행 가능 시간을 초과합니다."),
        CAFE("선택한 범위에서 필수 카페 조건을 충족하지 못했습니다."),
        AREA("필수 장소가 선택한 여행 범위를 벗어납니다."),
        HOURS("현재 장소의 운영시간을 검증할 수 없습니다. 미확인 장소 포함을 선택하면 확인이 필요한 초안으로 저장할 수 있습니다.");

        private final String reason;

        Outcome(String reason) { this.reason = reason; }
    }

    // Stay limits include one 15-minute walking leg per stop (the fixture has an origin and no destination).
    @ParameterizedTest(name = "{0}")
    @CsvSource({
            "unknown_hours_allowed,1,60,420,카페,,35.8395,1,ALLOW_WITH_WARNING,ACCEPT",
            "stay_at_limit,1,60,75,카페,,35.8395,1,ALLOW_WITH_WARNING,ACCEPT",
            "stay_over_limit,1,61,75,카페,,35.8395,1,ALLOW_WITH_WARNING,STAY",
            "stay_sum_at_limit,2,60,150,카페,,35.8395,2,ALLOW_WITH_WARNING,ACCEPT",
            "stay_sum_over_limit,2,60,149,카페,,35.8395,2,ALLOW_WITH_WARNING,STAY",
            "missing_cafe,1,60,420,공원,,35.8395,1,ALLOW_WITH_WARNING,CAFE",
            "source_category_cafe,1,60,420,시설,카페,35.8395,1,ALLOW_WITH_WARNING,ACCEPT",
            "cafe_minimum_two,1,60,420,카페,,35.8395,2,ALLOW_WITH_WARNING,CAFE",
            "outside_circle,1,60,420,카페,,0,1,ALLOW_WITH_WARNING,AREA",
            "unknown_coordinates,1,60,420,카페,,,1,ALLOW_WITH_WARNING,AREA",
            "unknown_hours_excluded,1,60,420,카페,,35.8395,1,EXCLUDE,HOURS"
    })
    void sameDraftHasSameSaveDecisionAcrossBothPaths(
            String scenario,
            int stopCount,
            int stayMinutes,
            int availableMinutes,
            String category,
            String sourceCategory,
            Double latitude,
            int cafeMinimum,
            String hoursPolicy,
            Outcome outcome
    ) throws Exception {
        ObjectNode payload = requestPayload();
        ((ObjectNode) payload.path("requiredStops").get(0)).put("stayMinutes", stayMinutes);
        IntStream.range(1, stopCount).forEach(index -> payload.withArray("requiredStops")
                .addObject().put("placeId", 101L + index).put("stayMinutes", stayMinutes));
        var base = mapper.treeToValue(payload, GeneratePlanRequest.class);
        ((ObjectNode) payload.get("context")).put("endAt", base.context().startAt().plusMinutes(availableMinutes).toString());
        ((ObjectNode) payload.path("context").path("categoryRequirements").get(0)).put("minCount", cafeMinimum);
        ((ObjectNode) payload.get("context")).put("unknownHoursPolicy", hoursPolicy);
        var request = mapper.treeToValue(payload, GeneratePlanRequest.class);
        var selectedPlaces = request.requiredStops().stream()
                .map(stop -> place(stop.placeId(), category, sourceCategory, latitude)).toList();
        var jobs = mock(PlanningJobRepository.class);
        var plans = mock(ContextPlanRepository.class);
        var search = mock(PlaceSemanticSearchService.class);
        var llm = mock(LlmClient.class);
        when(jobs.insert(any(), anyString(), any(), any(), anyString())).thenReturn(true);
        when(plans.requiredPlaces(request.requiredStops().stream().map(GeneratePlanRequest.RequiredStop::placeId).toList()))
                .thenReturn(selectedPlaces);
        when(plans.save(anyString(), any(), any(), anyList(), anyString())).thenReturn(77L);
        var proposed = new GeneratedPlan(
                "나의 여행 일정",
                request.context().additionalRequest(),
                IntStream.range(0, stopCount).mapToObj(index -> new GeneratedPlan.GeneratedPin(
                        request.requiredStops().get(index).placeId(),
                        index + 1,
                        "직접 선택",
                        "필수 방문 장소"
                )).toList()
        );
        when(llm.generate(anyString(), anyString())).thenReturn(mapper.writeValueAsString(proposed));
        var service = service(jobs, plans, search, llm);
        try {
            if (outcome == Outcome.ACCEPT) {
                service.create("mock-user", UUID.randomUUID(), request);
                verify(plans).save(eq("mock-user"), eq(request), eq(proposed), eq(selectedPlaces), anyString());
            } else {
                var rejection = assertThrows(ResponseStatusException.class,
                        () -> service.create("mock-user", UUID.randomUUID(), request), scenario);
                assertEquals(outcome.reason, rejection.getReason());
                verify(plans, never()).save(anyString(), any(), any(), anyList(), anyString());
            }
            clearInvocations(plans, jobs);
            UUID generatedJob = UUID.randomUUID();
            ReflectionTestUtils.invokeMethod(service, "runGeneration", generatedJob, "mock-user", request, "mock-request");
            if (outcome == Outcome.ACCEPT) {
                verify(plans).save(eq("mock-user"), eq(request), eq(proposed), eq(selectedPlaces), eq("mock-request"));
                verify(jobs).update(generatedJob, PlanningResponse.JobStatus.SUCCEEDED, 77L, null);
            } else {
                verify(plans, never()).save(anyString(), any(), any(), anyList(), anyString());
                verify(jobs).update(generatedJob, PlanningResponse.JobStatus.FAILED, null, outcome.reason);
            }
        } finally {
            ReflectionTestUtils.invokeMethod(service, "shutdown");
        }
    }

    @Test
    void duplicateRequiredStopsAreRejectedBeforeEitherEntryPointStartsWork() throws Exception {
        ObjectNode payload = requestPayload();
        payload.withArray("requiredStops").add(payload.path("requiredStops").get(0).deepCopy());
        var request = mapper.treeToValue(payload, GeneratePlanRequest.class);
        var jobs = mock(PlanningJobRepository.class);
        var plans = mock(ContextPlanRepository.class);
        var search = mock(PlaceSemanticSearchService.class);
        var llm = mock(LlmClient.class);
        var service = service(jobs, plans, search, llm);
        try {
            var manual = assertThrows(ResponseStatusException.class,
                    () -> service.create("mock-user", UUID.randomUUID(), request));
            var generated = assertThrows(ResponseStatusException.class,
                    () -> service.generate("mock-user", UUID.randomUUID(), request));
            assertEquals("필수 장소가 중복되었습니다.", manual.getReason());
            assertEquals(manual.getReason(), generated.getReason());
            verifyNoInteractions(jobs, plans, search, llm);
        } finally {
            ReflectionTestUtils.invokeMethod(service, "shutdown");
        }
    }

    @ParameterizedTest
    // 60 required + 60 relaxed or 40 normal default stay + two walking legs.
    @CsvSource({"RELAXED,149,false", "RELAXED,150,true", "NORMAL,130,true"})
    void extraSelectedPlacesUseTheSameStayDefaultsAsPersistence(
            String pace,
            int availableMinutes,
            boolean accepted
    ) throws Exception {
        ObjectNode payload = requestPayload();
        ((ObjectNode) payload.path("context").get("preferences")).put("pace", pace);
        var base = mapper.treeToValue(payload, GeneratePlanRequest.class);
        ((ObjectNode) payload.get("context")).put("endAt", base.context().startAt().plusMinutes(availableMinutes).toString());
        var request = mapper.treeToValue(payload, GeneratePlanRequest.class);
        var proposed = new GeneratedPlan("초안", null, List.of(
                new GeneratedPlan.GeneratedPin(102L, 2, null, null),
                new GeneratedPlan.GeneratedPin(101L, 1, null, null)));
        var candidates = List.of(place(101L, "카페", null, 35.8395), place(102L, "공원", null, 35.8395));
        if (!accepted) {
            assertThrows(ResponseStatusException.class, () -> DraftPlanValidator.validate(proposed, candidates, request));
            return;
        }
        var saved = DraftPlanValidator.validate(proposed, candidates, request);
        assertEquals(List.of(101L, 102L), saved.pins().stream().map(GeneratedPlan.GeneratedPin::placeId).toList());
        assertNull(saved.planDescription(), "초안의 설명·활동·도착 시각 미작성은 허용한다");
    }

    @Test
    void nonexistentRequiredPlaceCannotBeSavedByEitherPath() throws Exception {
        var request = mapper.treeToValue(requestPayload(), GeneratePlanRequest.class);
        var jobs = mock(PlanningJobRepository.class);
        var plans = mock(ContextPlanRepository.class);
        var search = mock(PlaceSemanticSearchService.class);
        var llm = mock(LlmClient.class);
        var service = service(jobs, plans, search, llm);
        try {
            var manual = assertThrows(ResponseStatusException.class,
                    () -> service.create("mock-user", UUID.randomUUID(), request));
            assertEquals("존재하지 않는 필수 장소가 있습니다.", manual.getReason());
            UUID jobId = UUID.randomUUID();
            ReflectionTestUtils.invokeMethod(service, "runGeneration", jobId, "mock-user", request, "mock-request");
            verify(jobs).update(jobId, PlanningResponse.JobStatus.FAILED, null, manual.getReason());
            verify(plans, never()).save(anyString(), any(), any(), anyList(), anyString());
            verifyNoInteractions(search, llm);
        } finally {
            ReflectionTestUtils.invokeMethod(service, "shutdown");
        }
    }

    @Test
    void selectedNonRequiredPlaceMustAlsoBeInsideTheCircle() throws Exception {
        var request = mapper.treeToValue(requestPayload(), GeneratePlanRequest.class);
        var proposed = new GeneratedPlan("초안", null, List.of(
                new GeneratedPlan.GeneratedPin(101L, 1, null, null),
                new GeneratedPlan.GeneratedPin(102L, 2, null, null)));
        var rejection = assertThrows(ResponseStatusException.class, () -> DraftPlanValidator.validate(
                proposed,
                List.of(place(101L, "카페", null, 35.8395), place(102L, "공원", null, 0.0)),
                request
        ));
        assertEquals("선택한 장소가 여행 범위를 벗어나거나 좌표를 확인할 수 없습니다.", rejection.getReason());
    }

    @Test
    void parserRejectsEmptyOrMalformedModelOutputBeforeSaving() {
        var parser = new ContextPlanResultValidator(mapper);
        assertThrows(IllegalStateException.class, () -> parser.parse(" "));
        assertThrows(IllegalStateException.class, () -> parser.parse("not-json"));
    }

    private ObjectNode requestPayload() throws Exception {
        return (ObjectNode) mapper.readTree(PlanContextContractTest.REQUEST);
    }

    private ContextPlanningService service(
            PlanningJobRepository jobs,
            ContextPlanRepository plans,
            PlaceSemanticSearchService search,
            LlmClient llm
    ) {
        return new ContextPlanningService(
                jobs,
                plans,
                search,
                mapper,
                llm,
                new ContextPlanResultValidator(mapper),
                new ContextPlanPromptFactory(mapper)
        );
    }

    private PlaceResult place(
            Long placeId,
            String category,
            String sourceCategory,
            Double latitude
    ) {
        return new PlaceResult(
                placeId,
                "모의 장소",
                null,
                null,
                null,
                category,
                sourceCategory,
                latitude,
                129.212,
                0.9,
                null,
                null,
                null
        );
    }
}
