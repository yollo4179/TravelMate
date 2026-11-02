package com.yollo.TravelMate.domain.place.source.tourapi.support;

import java.util.regex.Pattern;
import java.util.stream.Collectors;

import org.springframework.web.util.HtmlUtils;

public final class TourPlaceTextNormalizer {

    private static final Pattern HTML_LINE_BREAK = Pattern.compile(
            "(?i)<br\\s*/?>|</(?:p|div|li|tr|h[1-6])\\s*>"
    );
    private static final Pattern HTML_TAG = Pattern.compile("<[^>]+>");
    private static final Pattern HORIZONTAL_SPACE = Pattern.compile("[\\h\\u200B\\uFEFF]+");
    private static final Pattern ALL_SPACE = Pattern.compile("[\\s\\p{Z}\\u200B\\uFEFF]+");

    private TourPlaceTextNormalizer() {
    }

    public static String normalize(String source) {
        if (source == null || source.isBlank()) {
            return "";
        }
        String decoded = HtmlUtils.htmlUnescape(source);
        String separated = HTML_LINE_BREAK.matcher(decoded).replaceAll("\n");
        return HTML_TAG.matcher(separated).replaceAll("").lines()
                .map(line -> HORIZONTAL_SPACE.matcher(line).replaceAll(" ").strip())
                .filter(line -> !line.isBlank())
                .collect(Collectors.joining("\n"));
    }

    public static String normalizeHeading(String source) {
        return ALL_SPACE.matcher(normalize(source)).replaceAll("");
    }
}
