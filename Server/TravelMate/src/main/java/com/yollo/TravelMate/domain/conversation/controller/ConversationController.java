package com.yollo.TravelMate.domain.conversation.controller;

import java.util.UUID;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse;
import com.yollo.TravelMate.domain.conversation.service.ConversationService;
import com.yollo.TravelMate.domain.user.entity.User;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/conversation")
@RequiredArgsConstructor
public class ConversationController {
    private final ConversationService conversation;

    @PostMapping("/turns")
    public ConversationResponse respond(
            @AuthenticationPrincipal User user,
            @RequestHeader("Idempotency-Key") UUID turnKey,
            @Valid @RequestBody ConversationRequest request
    ) {
        return conversation.respond(user.getUid(), turnKey, request);
    }
}
