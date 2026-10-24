package com.yollo.TravelMate.domain.plan.validator;

import java.time.Duration;
import java.util.HashSet;
import java.util.Set;
import java.util.stream.Collectors;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.data.request.PlanContext;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class ContextPlanResultValidator {
    private final ObjectMapper objectMapper;

    public GeneratedPlan validate(
            String output,
            Set<Long> candidateIds,
            GeneratePlanRequest request
    ) {
        if (output == null || output.isBlank()) throw new IllegalStateException("AI가 빈 결과를 반환했습니다.");
        final GeneratedPlan generated;
        try { generated = objectMapper.readValue(output, GeneratedPlan.class); }
        catch (JsonProcessingException exception) { throw new IllegalStateException("AI 응답이 일정 JSON 형식과 일치하지 않습니다.", exception); }
        if (generated == null || generated.planTitle() == null || generated.planTitle().isBlank()
                || generated.planTitle().length() > 100 || generated.pins() == null
                || generated.pins().isEmpty() || generated.pins().size() > 6) {
            throw new IllegalStateException("AI가 유효한 제목과 1~6개 방문 장소를 반환하지 않았습니다.");
        }
        Set<Long> selectedIds = new HashSet<>();
        Set<Integer> sequences = new HashSet<>();
        for (var pin : generated.pins()) {
            if (pin == null || !candidateIds.contains(pin.placeId()) || !selectedIds.add(pin.placeId())
                    || pin.sequence() == null || pin.sequence() < 1 || pin.sequence() > generated.pins().size()
                    || !sequences.add(pin.sequence())) {
                throw new IllegalStateException("AI 결과에 후보 밖 장소, 중복 장소 또는 잘못된 방문 순서가 있어 저장하지 않았습니다.");
            }
        }
        var requiredIds = request.requiredStops().stream().map(GeneratePlanRequest.RequiredStop::placeId).toList();
        if (!selectedIds.containsAll(requiredIds)) throw new IllegalStateException("AI 결과에서 필수 방문 장소가 누락되었습니다.");
        var stayById = request.requiredStops().stream().collect(Collectors.toMap(
                GeneratePlanRequest.RequiredStop::placeId,
                GeneratePlanRequest.RequiredStop::stayMinutes
        ));
        int defaultStay = request.context().preferences().pace() == PlanContext.Pace.RELAXED ? 60 : 40;
        int totalStay = selectedIds.stream().mapToInt(placeId -> stayById.getOrDefault(placeId, defaultStay)).sum();
        long availableMinutes = Duration.between(request.context().startAt(), request.context().endAt()).toMinutes();
        if (totalStay > availableMinutes) throw new IllegalStateException("방문 체류시간이 여행 가능 시간을 초과합니다.");
        return new GeneratedPlan(
                generated.planTitle(),
                generated.planDescription(),
                generated.pins().stream().sorted(java.util.Comparator.comparing(GeneratedPlan.GeneratedPin::sequence)).toList()
        );
    }
}
