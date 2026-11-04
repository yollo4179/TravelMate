package com.yollo.TravelMate.domain.conversation.controller;

import java.util.Arrays;
import java.util.Map;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.ConversationIntent;
import com.yollo.TravelMate.domain.place.data.request.SearchRadius;
import com.yollo.TravelMate.domain.place.enums.PlaceSearchCategories;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** UI choices derive from the same enums as storage and the model contract. */
@RestController
public class ConversationOptionsController {
    @GetMapping("/api/v1/conversation/options")
    public Map<String, Object> options() {
        return Map.of("categories", PlaceSearchCategories.allowedValues(),
                "intents", Arrays.stream(ConversationIntent.values()).map(Enum::name).toList(),
                "emotions", Arrays.stream(CharacterEmotion.values()).map(Enum::name).toList(),
                "radiusMeters", SearchRadius.bounds());
    }
}
