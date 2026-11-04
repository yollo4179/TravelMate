package com.yollo.TravelMate.ai.llm.derived;

/** Model capabilities are explicit configuration; never guessed from a model name. */
public enum ReasoningMode {
        DISABLED,     // Models supporting reasoning.effort=none.
        UNSUPPORTED   // Models without a reasoning parameter, such as GPT-4o-mini.
}
