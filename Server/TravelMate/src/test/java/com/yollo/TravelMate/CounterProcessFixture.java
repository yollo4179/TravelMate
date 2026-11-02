package com.yollo.TravelMate;

public final class CounterProcessFixture {
    public enum Scenario { TIMEOUT, FAILURE, INVALID, RESIDENT, WRONG_ID, CRASH_COUNT, SLOW_COUNT, REJECT_IDENTITY }
    private CounterProcessFixture() {}

    public static void main(String[] arguments) throws Exception {
        Scenario scenario = Scenario.valueOf(arguments[0]);
        switch (scenario) {
            case TIMEOUT -> Thread.sleep(10000);
            case FAILURE -> System.exit(1);
            case INVALID -> System.out.println("invalid JSON");
            default -> serve(scenario);
        }
    }

    private static void serve(Scenario scenario) throws Exception {
        String sessionId = java.util.UUID.randomUUID().toString();
        var idPattern = java.util.regex.Pattern.compile("\"requestId\":\"([^\"]+)\"");
        var reader = new java.io.BufferedReader(new java.io.InputStreamReader(System.in, java.nio.charset.StandardCharsets.UTF_8));
        var writer = new java.io.PrintWriter(new java.io.OutputStreamWriter(System.out, java.nio.charset.StandardCharsets.UTF_8), true);
        long sequence = 0;
        for (String line; (line = reader.readLine()) != null;) {
            var matched = idPattern.matcher(line);
            if (!matched.find()) throw new IllegalArgumentException("Missing mock request ID");
            String requestId = matched.group(1);
            boolean initialize = line.contains("\"operation\":\"INIT\"");
            if (!initialize && scenario == Scenario.CRASH_COUNT) System.exit(1);
            if (!initialize && scenario == Scenario.SLOW_COUNT) Thread.sleep(1500);
            if (!initialize && scenario == Scenario.REJECT_IDENTITY) {
                writer.println("{\"requestId\":\"" + requestId + "\",\"status\":\"ERROR\",\"errorCode\":\"ASSET_CHANGED\"}");
                continue;
            }
            if (!initialize && scenario == Scenario.WRONG_ID) requestId = "different-request";
            String status = initialize ? "READY" : "COUNTED";
            if (!initialize) sequence++;
            writer.println("{\"requestId\":\"" + requestId + "\",\"sessionId\":\"" + sessionId + "\",\"status\":\"" + status
                    + "\",\"payload\":{\"workerSessionId\":\"" + sessionId + "\",\"workerPid\":" + ProcessHandle.current().pid()
                    + ",\"initializationCount\":1,\"sequence\":" + sequence + ",\"inputTokens\":10,\"echo\":" + line + "}}");
        }
    }
}
