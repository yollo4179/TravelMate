package com.yollo.TravelMate.domain.conversation.tool;

import java.util.Comparator;
import java.util.List;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;
import com.yollo.TravelMate.ai.llm.base.LlmTurn;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;

@Component
public class ConversationToolRegistry {
    private final List<ConversationTool> tools;

    public ConversationToolRegistry(List<ConversationTool> tools) {
        this.tools = tools.stream().sorted(Comparator.comparing(tool -> tool.definition().name())).toList();
        if (this.tools.stream().map(tool -> tool.definition().name()).distinct().count() != this.tools.size()) {
            throw new IllegalStateException("중복된 대화 도구 이름이 있습니다.");
        }
    }

    @Autowired
    public ConversationToolRegistry(
            List<ConversationTool> tools,
            @Value("${travelmate.conversation.allowed-tools:SEARCH_PLACES,GENERATE_PLAN,GET_PLANNING_JOB}") String allowedTools
    ) {
        this(select(tools, allowedTools));
    }

    private static List<ConversationTool> select(List<ConversationTool> tools, String allowedTools) {
        Set<String> allowed = Arrays.stream(allowedTools.split(","))
                .map(String::trim).map(ConversationTool.Name::valueOf).map(ConversationTool.Name::wireName).collect(Collectors.toSet());
        var selected = tools.stream().filter(tool -> allowed.contains(tool.definition().name()))
                .sorted(Comparator.comparing(tool -> tool.definition().name())).toList();
        if (selected.size() != allowed.size()) throw new IllegalStateException("Configured tool is missing or duplicated");
        return selected;
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
