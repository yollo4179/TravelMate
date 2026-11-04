package com.yollo.TravelMate;

import java.util.List;
import java.util.Optional;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.MessageSource;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.Termination;
import com.yollo.TravelMate.domain.conversation.pipeline.LiliFixedLines;
import com.yollo.TravelMate.domain.conversation.service.ConversationAnswerRenderer;
import com.yollo.TravelMate.domain.place.data.result.QuoteLocator;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Quotes are matched forgiving only glosses and whitespace, and are always stored as the original's own span. */
class QuoteLocatorTest {
    // The live palaces-01 original and the model's copy that dropped the Hanja gloss.
    private static final String ORIGINAL = "관광지. 고궁. 창경궁(昌慶宮)은 성종이 세 명의 대비를 위해 옛 수강궁에 창건한 궁이다. 창경궁은 원래";
    private static final String WITHOUT_GLOSS = "창경궁은 성종이 세 명의 대비를 위해 옛 수강궁에 창건한 궁이다.";

    @Test
    void aDroppedGlossIsFoundAndReplacedWithTheOriginalSpan() {
        assertEquals(Optional.of("창경궁(昌慶宮)은 성종이 세 명의 대비를 위해 옛 수강궁에 창건한 궁이다."),
                QuoteLocator.locate(ORIGINAL, WITHOUT_GLOSS));
    }

    @Test
    void anExactQuoteIsReturnedUnchanged() {
        String exact = "창경궁(昌慶宮)은 성종이";
        assertEquals(Optional.of(exact), QuoteLocator.locate(ORIGINAL, exact));
    }

    @Test
    void whitespaceRunsAreForgivenButKeepTheOriginalSpacing() {
        String original = "정문과  정전이\n동향으로 배치되어 있다.";
        assertEquals(Optional.of(original), QuoteLocator.locate(original, "정문과 정전이 동향으로 배치되어 있다."));
    }

    @Test
    void changedWordsOrPunctuationAreStillRejected() {
        assertTrue(QuoteLocator.locate(ORIGINAL, "창경궁은 성종이 세 명의 대비를 위해 새로 창건한 궁이다.").isEmpty());
        assertTrue(QuoteLocator.locate(ORIGINAL, "창경궁은 성종이 세 명의 대비를 위해 옛 수강궁에 창건한 궁이다!").isEmpty());
        assertTrue(QuoteLocator.locate(ORIGINAL, "   ").isEmpty());
    }

    @Test
    void aLongBracketedClauseIsContentNotAGloss() {
        String original = "창경궁(조선 성종 때 세 명의 대비를 모시기 위해 수강궁 터에 새로 지은 궁)은 동궐이다.";
        assertTrue(QuoteLocator.locate(original, "창경궁은 동궐이다.").isEmpty());
    }

    @Test
    void liliPathsFallBackWithHerLineAndKeepTheServerFallbackSource() {
        var renderer = new ConversationAnswerRenderer(new ObjectMapper());
        var response = renderer.liliFallback(null, Termination.INVALID_RESPONSE, 1, List.of());
        assertEquals(LiliFixedLines.line(LiliFixedLines.Line.REPLY_UNAVAILABLE).text(), response.message());
        assertEquals(List.of(LiliFixedLines.line(LiliFixedLines.Line.REPLY_UNAVAILABLE)), response.dialogue());
        assertEquals(MessageSource.SERVER_FALLBACK, response.messageSource(), "a fixed line is not presented as LiLi's model output");
        assertFalse(response.message().contains("서버"));
    }
}
