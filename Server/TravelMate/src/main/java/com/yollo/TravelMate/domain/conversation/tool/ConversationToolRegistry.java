package com.yollo.TravelMate.domain.conversation.tool;

import java.util.Comparator;
import java.util.List;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import org.springframework.stereotype.Component;

@Component
public class ConversationToolRegistry {
    private final List<ConversationTool> tools;

    public ConversationToolRegistry(List<ConversationTool> tools) {
        this.tools = tools.stream().sorted(Comparator.comparing(tool -> tool.definition().name())).toList();
        if (this.tools.stream().map(tool -> tool.definition().name()).distinct().count() != this.tools.size()) {
            throw new IllegalStateException("중복된 대화 도구 이름이 있습니다.");
        }
    }

    public List<LlmTurn.ToolDefinition> definitions() {
        return tools.stream().map(ConversationTool::definition).toList();
    }

    public ConversationTool resolve(String name) {
        var matches = tools.stream().filter(tool -> tool.supports(name)).toList();
        if (matches.size() != 1) throw new IllegalArgumentException("등록되지 않은 도구입니다.");
        return matches.get(0);
    }
}
