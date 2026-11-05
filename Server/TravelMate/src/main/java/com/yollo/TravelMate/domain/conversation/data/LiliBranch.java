package com.yollo.TravelMate.domain.conversation.data;

/** What LiLi decides to do next, before any place evidence is seen. */
public enum LiliBranch {
        CHAT,              // Reply only: small talk, thanks, unsupported requests.
        CLARIFY,           // Ask back with 2-3 choices instead of guessing.
        SEARCH_PLACES,     // Queue a recommendation job with LiLi's search query.
        GENERATE_PLAN,     // Queue a draft job when planning conditions were provided.
        GET_PLANNING_JOB;  // Look up a job whose ID the server finds in the user's message.

        public boolean requiresSearchQuery() {
            return this == SEARCH_PLACES || this == GENERATE_PLAN;
        }

        /** A job lookup needs a job ID the server found in the message; without one the branch is not offered at all. */
        public boolean requiresJobId() {
            return this == GET_PLANNING_JOB;
        }

        /** Branches where the user is after places by what they said; a plan's area comes from the app's map instead. */
        public boolean asksForPlacesInWords() {
            return this == SEARCH_PLACES || this == CLARIFY;
        }
}
