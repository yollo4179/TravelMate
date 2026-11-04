package com.yollo.TravelMate.domain.conversation.data;

import java.util.Objects;

/** One visual-novel cut: a short line shown with exactly one LiLi expression. */
public record DialogueCut(
        String text,
        CharacterEmotion emotion
) {
    public static final int MIN_RESULT_CUTS = 2;
    public static final int MAX_RESULT_CUTS = 4;
    public static final int MAX_TEXT_LENGTH = 200;

    public DialogueCut {
        Objects.requireNonNull(text);
        emotion = emotion == null ? CharacterEmotion.NEUTRAL : emotion;
    }
}
