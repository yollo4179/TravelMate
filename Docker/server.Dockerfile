FROM eclipse-temurin:17-jdk-jammy AS build
WORKDIR /build
COPY Server/TravelMate/gradlew Server/TravelMate/build.gradle Server/TravelMate/settings.gradle ./
COPY Server/TravelMate/gradle ./gradle
COPY Server/TravelMate/src ./src
RUN --mount=type=cache,target=/root/.gradle \
    --mount=type=secret,id=java_cacerts \
    --mount=type=secret,id=gradle_properties \
    if [ -s /run/secrets/gradle_properties ]; then cp /run/secrets/gradle_properties /root/.gradle/gradle.properties; fi; \
    if [ -s /run/secrets/java_cacerts ]; then export JAVA_TOOL_OPTIONS=-Djavax.net.ssl.trustStore=/run/secrets/java_cacerts; fi; \
    sed -i 's/\r$//' gradlew && \
    bash gradlew --no-daemon --max-workers=2 bootJar

FROM eclipse-temurin:17-jdk-jammy AS runtime
WORKDIR /app
COPY --from=build --chown=10001:10001 /build/build/libs/TravelMate-*.jar /app/app.jar
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=4 \
  CMD curl --fail --silent --max-time 4 http://127.0.0.1:8080/v3/api-docs > /dev/null || exit 1
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=70.0", "-jar", "/app/app.jar"]
