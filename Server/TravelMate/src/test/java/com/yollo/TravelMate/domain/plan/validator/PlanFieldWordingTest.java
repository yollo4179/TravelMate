package com.yollo.TravelMate.domain.plan.validator;

import java.util.LinkedHashSet;
import java.util.List;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PlanFieldWordingTest {
    // Live core run k2-core2 saved this description.
    @Test
    void theFieldNameSeenLiveBecomesPlainWords() {
        assertEquals("시간 조건도 고려해서 꼭 넣을 장소를 그대로 반영하고",
                reword("시간 조건도 고려해서 requiredStops를 그대로 반영하고"));
    }

    @Test
    void particlesFollowTheReplacementNotTheEnglishWord() {
        assertEquals("후보 장소를 보고", reword("candidates을 보고"));
        assertEquals("머무는 시간은 60분", reword("stayMinutes는 60분"));
        assertEquals("요청 내용이 바뀌면", reword("searchQuery가 바뀌면"));
        assertEquals("보충 설명과 원문", reword("generatedSupplement와 원문"));
    }

    @Test
    void theCopulaIsNotTakenForASubjectMarker() {
        assertEquals("꼭 넣을 장소이다", reword("requiredStops이다"));
        assertEquals("설명이 없는 장소인 곳", reword("NONE_SELECTED인 곳"));
    }

    @Test
    void onlyWholeFieldNamesAreReplaced() {
        assertEquals("myrequiredStops와 candidatesList", reword("myrequiredStops와 candidatesList"));
        assertEquals("창경궁만 넣었어.", reword("창경궁만 넣었어."));
    }

    @Test
    void everythingUsersReadIsReworded_butQuotesStayExact() {
        var citation = new GeneratedPlan.SourceCitation("E378-0", "source", "requiredStops는 원문에 없는 말이지만 그대로 둔다");
        var plan = new GeneratedPlan("requiredStops 중심 일정", "candidates 중에서 골랐어",
                List.of(new GeneratedPlan.GeneratedPin(378L, 1, "requiredStops 둘러보기", "searchQuery와 맞음", List.of(citation))),
                List.of(new DialogueCut("requiredStops를 넣었어.", CharacterEmotion.HAPPY)));
        var reworded = PlanFieldWording.apply(plan);
        assertEquals("꼭 넣을 장소 중심 일정", reworded.plan().planTitle());
        assertEquals("후보 장소 중에서 골랐어", reworded.plan().planDescription());
        assertEquals("꼭 넣을 장소 둘러보기", reworded.plan().pins().get(0).activity());
        assertEquals("요청 내용과 맞음", reworded.plan().pins().get(0).reason());
        assertEquals("꼭 넣을 장소를 넣었어.", reworded.plan().dialogue().get(0).text());
        assertEquals(citation, reworded.plan().pins().get(0).citations().get(0), "a quote must match its original exactly");
        assertEquals(List.of("requiredStops", "candidates", "searchQuery"), reworded.replacedFields());
    }

    @Test
    void aPlanWithoutFieldNamesIsUnchanged() {
        var plan = new GeneratedPlan("창경궁 일정", "왕실 생활공간 중심",
                List.of(new GeneratedPlan.GeneratedPin(378L, 1, "둘러보기", "요청과 맞음")), null);
        var reworded = PlanFieldWording.apply(plan);
        assertEquals(plan, reworded.plan());
        assertTrue(reworded.replacedFields().isEmpty());
    }

    private static String reword(String text) {
        return PlanFieldWording.reword(text, new LinkedHashSet<>());
    }
}
