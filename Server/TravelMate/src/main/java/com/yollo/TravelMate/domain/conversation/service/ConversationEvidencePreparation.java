package com.yollo.TravelMate.domain.conversation.service;

import java.util.List;
import java.util.UUID;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.yollo.TravelMate.domain.conversation.data.ConversationRequest;
import com.yollo.TravelMate.domain.conversation.data.ConversationResponse.ResultType;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.conversation.tool.ConversationToolRegistry;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class ConversationEvidencePreparation {
    private final List<ConversationEvidenceStrategy> strategies;

    public enum State { SKIPPED, READY, EMPTY, FAILED }
    private enum FailureCode { EVIDENCE_PREPARATION_FAILED }

    public record Prepared(State state, ConversationTool.Name source, ConversationTool.Result result) {
        public int retrievalCalls() {
            return state == State.SKIPPED ? 0 : 1;
        }
    }

    public Prepared prepare(
            String userUid,
            UUID turnKey,
            ConversationRequest request,
            ConversationToolRegistry registry
    ) {
        var applicable = strategies.stream().filter(strategy -> strategy.supports(registry)).toList();
        if (applicable.isEmpty()) return new Prepared(State.SKIPPED, null, null);
        if (applicable.size() != 1) throw new IllegalStateException("대화 근거 준비 전략은 하나만 선택되어야 합니다.");
        var strategy = applicable.get(0);
        try {
            var result = strategy.prepare(userUid, turnKey, request, registry);
            if (result == null || result.type() != ResultType.PLACES || result.publicData() == null
                    || !result.publicData().isArray() || result.modelData() == null || !result.modelData().isObject()) {
                throw new IllegalStateException("장소 검색 근거 준비 결과가 올바르지 않습니다.");
            }
            return new Prepared(result.publicData().isEmpty() ? State.EMPTY : State.READY, strategy.source(), result);
        } catch (RuntimeException exception) {
            var failure = JsonNodeFactory.instance.objectNode()
                    .put("code", FailureCode.EVIDENCE_PREPARATION_FAILED.name())
                    .put("message", "장소 검색 근거를 준비하지 못했습니다. 빈 검색 결과로 처리하지 않습니다.");
            return new Prepared(State.FAILED, strategy.source(), ConversationTool.Result.builder()
                    .type(ResultType.ERROR)
                    .publicData(failure)
                    .modelData(failure)
                    .build());
        }
    }
}
