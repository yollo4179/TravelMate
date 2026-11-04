package com.yollo.TravelMate.domain.plan.validator;

import java.time.Duration;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.data.request.GeneratePlanRequest;
import com.yollo.TravelMate.domain.plan.data.request.PlanContext;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

public final class DraftPlanValidator {
    private DraftPlanValidator() {}

    public static GeneratedPlan validate(
            GeneratedPlan draft,
            List<PlaceResult> candidates,
            GeneratePlanRequest request
    ) {
        validateStructure(draft);
        var candidatesById = candidates.stream().collect(Collectors.toMap(PlaceResult::id, Function.identity()));
        Set<Long> selectedIds = selectedIds(draft, candidatesById.keySet());
        Set<Long> requiredIds = request.requiredStops().stream()
                .map(GeneratePlanRequest.RequiredStop::placeId).collect(Collectors.toSet());
        if (requiredIds.size() != request.requiredStops().size()) {
            throw invalid("필수 장소가 중복되었습니다.");
        }
        if (!selectedIds.containsAll(requiredIds)) {
            throw invalid("초안에서 필수 방문 장소가 누락되었습니다.");
        }
        var selectedPlaces = selectedIds.stream().map(candidatesById::get).toList();
        if (selectedPlaces.stream().anyMatch(place -> !PlanAreaValidator.contains(request.context().area(), place))) {
            throw invalid("선택한 장소가 여행 범위를 벗어나거나 좌표를 확인할 수 없습니다.");
        }
        validateStayMinutes(selectedIds, request);
        validateCategories(selectedPlaces, request.context().categoryRequirements());
        return new GeneratedPlan(
                draft.planTitle(),
                draft.planDescription(),
                draft.pins().stream().sorted(Comparator.comparing(GeneratedPlan.GeneratedPin::sequence)).toList(),
                draft.dialogue()
        );
    }

    private static void validateStructure(GeneratedPlan draft) {
        if (draft == null || draft.planTitle() == null || draft.planTitle().isBlank()
                || draft.planTitle().length() > 100 || draft.pins() == null
                || draft.pins().isEmpty() || draft.pins().size() > 6) {
            throw invalid("초안에는 유효한 제목과 1~6개 방문 장소가 필요합니다.");
        }
    }

    private static Set<Long> selectedIds(GeneratedPlan draft, Set<Long> candidateIds) {
        Set<Long> selectedIds = new HashSet<>();
        Set<Integer> sequences = new HashSet<>();
        for (var pin : draft.pins()) {
            if (pin == null || !candidateIds.contains(pin.placeId()) || !selectedIds.add(pin.placeId())
                    || pin.sequence() == null || pin.sequence() < 1 || pin.sequence() > draft.pins().size()
                    || !sequences.add(pin.sequence())) {
                throw invalid("초안에 후보 밖 장소, 중복 장소 또는 잘못된 방문 순서가 있습니다.");
            }
        }
        return selectedIds;
    }

    private static void validateStayMinutes(Set<Long> selectedIds, GeneratePlanRequest request) {
        var stayById = request.requiredStops().stream().collect(Collectors.toMap(
                GeneratePlanRequest.RequiredStop::placeId,
                GeneratePlanRequest.RequiredStop::stayMinutes
        ));
        int defaultStay = request.context().preferences().pace() == PlanContext.Pace.RELAXED ? 60 : 40;
        int totalStay = selectedIds.stream().mapToInt(placeId -> stayById.getOrDefault(placeId, defaultStay)).sum();
        long availableMinutes = Duration.between(request.context().startAt(), request.context().endAt()).toMinutes();
        // 체류시간만으로도 불가능한 초안을 막는다. 남은 시간이 실제 이동에 충분하다는 판정은 아니다.
        if (totalStay > availableMinutes) {
            throw invalid("방문 체류시간이 여행 가능 시간을 초과합니다.");
        }
    }

    private static void validateCategories(
            List<PlaceResult> selectedPlaces,
            List<PlanContext.CategoryRequirement> requirements
    ) {
        long cafeCount = selectedPlaces.stream()
                .filter(place -> "카페".equals(place.category()) || "카페".equals(place.sourceCategory())).count();
        if (requirements.stream().anyMatch(requirement ->
                requirement.category() == PlanContext.Category.CAFE && cafeCount < requirement.minCount())) {
            throw invalid("선택한 범위에서 필수 카페 조건을 충족하지 못했습니다.");
        }
    }

    private static ResponseStatusException invalid(String reason) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, reason);
    }
}
