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

/** Quotes are matched forgiving only an omitted Hanja gloss and whitespace length, and are stored as the original's span. */
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

    // The r3 plan draft cited this sentence with the original's double space after the comma reduced to one.
    @Test
    void theLivePlanQuoteWithACollapsedDoubleSpaceKeepsTheOriginalSpan() {
        String original = "창경궁은 창덕궁과 경계 없이 동궐(東闕)이라는 하나의 궁궐 영역이었으며,  주로 왕실 가족들의 생활공간으로 사용하였다.";
        String cited = "창경궁은 창덕궁과 경계 없이 동궐(東闕)이라는 하나의 궁궐 영역이었으며, 주로 왕실 가족들의 생활공간으로 사용하였다.";
        assertEquals(Optional.of(original), QuoteLocator.locate("관광지. 고궁. \n" + original + " 창경궁은", cited));
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

    // Review counterexamples: the old matcher removed every short bracket on both sides, so a changed condition passed.
    @Test
    void aChangedConditionInBracketsIsRejected() {
        assertTrue(QuoteLocator.locate("입장료(성인)는 5000원입니다.", "입장료(어린이)는 5000원입니다.").isEmpty());
        assertTrue(QuoteLocator.locate("주차(주말 불가) 안내입니다.", "주차(주말 가능) 안내입니다.").isEmpty());
    }

    @Test
    void aDroppedConditionIsRejectedBecauseOnlyHanjaGlossesMayBeLeftOut() {
        assertTrue(QuoteLocator.locate("입장료(성인)는 5000원입니다.", "입장료는 5000원입니다.").isEmpty());
        assertTrue(QuoteLocator.locate("주차(주말 불가) 안내입니다.", "주차 안내입니다.").isEmpty());
        assertTrue(QuoteLocator.locate("정궁(1392~1910) 기록", "정궁 기록").isEmpty());
    }

    @Test
    void aChangedOrInventedGlossIsRejected() {
        assertTrue(QuoteLocator.locate(ORIGINAL, "창경궁(昌德宮)은 성종이").isEmpty());
        assertTrue(QuoteLocator.locate("창경궁은 성종이", "창경궁(昌慶宮)은 성종이").isEmpty());
    }

    @Test
    void whitespaceIsForgivenOnlyInLengthNotAddedOrRemoved() {
        assertTrue(QuoteLocator.locate("정문과정전이", "정문과 정전이").isEmpty());
        assertTrue(QuoteLocator.locate("정문과 정전이", "정문과정전이").isEmpty());
    }

    @Test
    void aSpacedGlossIsLeftOutWithItsLeadingSpace() {
        String original = "경복궁 (景福宮) 근정전은 정전이다.";
        assertEquals(Optional.of(original), QuoteLocator.locate(original, "경복궁 근정전은 정전이다."));
        assertEquals(Optional.of("창경궁（昌慶宮）은"), QuoteLocator.locate("창경궁（昌慶宮）은", "창경궁은"));
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
