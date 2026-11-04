package com.yollo.TravelMate.domain.conversation.service;

/** Reasons the server could not run the branch LiLi chose; LiLi phrases them in the follow-up line. */
public enum LiliServerCode {
        PLANNING_CONDITIONS_MISSING,  // GENERATE_PLAN without a planningRequest envelope.
        JOB_ID_NOT_FOUND               // GET_PLANNING_JOB without exactly one job UUID in the user's message.
}
