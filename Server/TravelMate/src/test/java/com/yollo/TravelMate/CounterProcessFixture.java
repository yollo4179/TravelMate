package com.yollo.TravelMate;

public final class CounterProcessFixture {
    public enum Scenario { TIMEOUT, FAILURE, INVALID }
    private CounterProcessFixture() {}

    public static void main(String[] arguments) throws InterruptedException {
        switch (Scenario.valueOf(arguments[0])) {
            case TIMEOUT -> Thread.sleep(10000);
            case FAILURE -> System.exit(1);
            case INVALID -> System.out.println("invalid JSON");
        }
    }
}
