package com.yollo.TravelMate.domain.conversation.controller;

import java.util.UUID;
import com.yollo.TravelMate.domain.conversation.data.RecommendationJobResponse;
import com.yollo.TravelMate.domain.conversation.service.RecommendationJobService;
import com.yollo.TravelMate.domain.user.entity.User;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/recommendation-jobs")
@RequiredArgsConstructor
public class RecommendationJobController {
    private final RecommendationJobService recommendations;

    @GetMapping("/{jobId}")
    public RecommendationJobResponse job(@AuthenticationPrincipal User user, @PathVariable("jobId") UUID jobId) {
        return recommendations.get(jobId, user.getUid());
    }
}
