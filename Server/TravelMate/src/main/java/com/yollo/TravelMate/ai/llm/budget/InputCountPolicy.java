package com.yollo.TravelMate.ai.llm.budget;

/** Whether a request may be bounded locally before the provider is asked for its exact input-token count. */
public enum InputCountPolicy {
    // Every call waits for the provider's count: the behaviour every run before 2026-11-05 measured.
    PROVIDER_ALWAYS,
    // A request whose byte length already fits the input window skips the count request. That request took
    // about 0.5 s of each first LiLi line (19.7 s once) and failed one plan job outright as COUNT_UNAVAILABLE.
    LOCAL_BOUND_FIRST
}
