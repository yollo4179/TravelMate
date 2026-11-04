package com.yollo.TravelMate;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.util.List;
import java.util.Map;
import java.util.Set;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.repository.PlanRepository;
import com.yollo.TravelMate.domain.plan.validator.PlanValidator;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.PreparedStatementCreator;
import org.springframework.jdbc.support.KeyHolder;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/** Both plan paths save drafts through PlanRepository, so the model's emotion must survive validation and the insert. */
class PlanEmotionPersistenceTest {
    private static final long PLAN_ID = 77L;

    @Test
    void legacyValidatorKeepsTheModelEmotionAfterDroppingHallucinatedPins() {
        String raw = """
                ```json
                {"planTitle":"t","planDescription":"d","emotion":"AFFECTIONATE","pins":[
                  {"placeId":1,"sequence":1,"activity":"a","reason":"r"},
                  {"placeId":999,"sequence":2,"activity":"x","reason":"invented"}]}
                ```""";
        var validated = new PlanValidator().validate(raw, Set.of(1L));
        assertEquals(1, validated.pins().size());
        assertEquals(CharacterEmotion.AFFECTIONATE, validated.emotion());
    }

    @Test
    void commonDraftInsertStoresTheEmotionColumn() throws Exception {
        var inserted = insert(new GeneratedPlan("t", "d", List.of(), CharacterEmotion.SHY));
        assertTrue(inserted.sql().contains("character_emotion"));
        verify(inserted.statement()).setString(4, CharacterEmotion.SHY.name());
    }

    @Test
    void draftWrittenWithoutModelTagStoresNullSoTheReceiptDefaultApplies() throws Exception {
        var inserted = insert(new GeneratedPlan("t", "d", List.of()));
        verify(inserted.statement()).setString(4, null);
    }

    private Inserted insert(GeneratedPlan plan) throws Exception {
        var jdbc = mock(JdbcTemplate.class);
        var connection = mock(Connection.class);
        var statement = mock(PreparedStatement.class);
        var sql = ArgumentCaptor.forClass(String.class);
        when(connection.prepareStatement(sql.capture(), any(String[].class))).thenReturn(statement);
        when(jdbc.update(any(PreparedStatementCreator.class), any(KeyHolder.class))).thenAnswer(invocation -> {
            invocation.getArgument(0, PreparedStatementCreator.class).createPreparedStatement(connection);
            invocation.getArgument(1, KeyHolder.class).getKeyList().add(Map.of("plan_id", PLAN_ID));
            return 1;
        });
        assertEquals(PLAN_ID, new PlanRepository(jdbc).saveDraft(plan, List.of(), "owner"));
        verify(connection).prepareStatement(anyString(), any(String[].class));
        return new Inserted(sql.getValue(), statement);
    }

    private record Inserted(
            String sql,
            PreparedStatement statement
    ) {}
}
