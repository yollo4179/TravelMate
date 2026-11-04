package com.yollo.TravelMate;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.util.List;
import java.util.Map;
import java.util.Set;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
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

/** Both plan paths save drafts through PlanRepository, so LiLi's cuts must survive validation and the insert. */
class PlanDialoguePersistenceTest {
    private static final long PLAN_ID = 77L;
    private static final List<DialogueCut> CUTS = List.of(
            new DialogueCut("왕실 생활공간 위주로 짜 봤어.", CharacterEmotion.EXCITED),
            new DialogueCut("어때, 마음에 들어?", CharacterEmotion.SHY)
    );
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void legacyValidatorKeepsTheCutsAfterDroppingHallucinatedPins() {
        String raw = """
                ```json
                {"planTitle":"t","planDescription":"d","dialogue":[{"text":"어때?","emotion":"AFFECTIONATE"}],"pins":[
                  {"placeId":1,"sequence":1,"activity":"a","reason":"r"},
                  {"placeId":999,"sequence":2,"activity":"x","reason":"invented"}]}
                ```""";
        var validated = new PlanValidator().validate(raw, Set.of(1L));
        assertEquals(1, validated.pins().size());
        assertEquals(CharacterEmotion.AFFECTIONATE, validated.dialogue().get(0).emotion());
    }

    @Test
    void commonDraftInsertStoresTheCutsAsOneJsonColumn() throws Exception {
        var inserted = insert(new GeneratedPlan("t", "d", List.of(), CUTS));
        assertTrue(inserted.sql().contains("character_dialogue"));
        var stored = ArgumentCaptor.forClass(String.class);
        verify(inserted.statement()).setString(eq(4), stored.capture());
        assertEquals(CUTS, List.of(mapper.readValue(stored.getValue(), DialogueCut[].class)));
    }

    @Test
    void draftWrittenWithoutModelCutsStoresNullSoTheReceiptDefaultApplies() throws Exception {
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
