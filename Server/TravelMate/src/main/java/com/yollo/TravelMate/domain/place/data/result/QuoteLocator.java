package com.yollo.TravelMate.domain.place.data.result;

import java.util.Optional;
import java.util.regex.Pattern;

/**
 * Finds where a model's quote sits in the original text and returns the original's own characters.
 * Two differences are forgiven, each on its own terms, because neither changes what the source says:
 * <ul>
 *     <li>whitespace: a run of spaces or line breaks may be copied as a single space, never added or removed;</li>
 *     <li>a Hanja gloss such as "(昌慶宮)" may be left out, since it repeats the preceding name in another script.</li>
 * </ul>
 * A bracket that holds Hangul, digits or other words is content, so it must be copied exactly: "(성인)" can neither
 * be dropped nor become "(어린이)". Brackets in the quote itself are never removed before matching.
 */
public final class QuoteLocator {
    private static final int MAX_GLOSS_LENGTH = 30;
    private static final Pattern WHITESPACE_RUN = Pattern.compile("\\s+");
    private static final String WHITESPACE = "\\s+";
    private static final String OMITTED_GLOSS =
            "(?:\\s*[(（]\\p{IsHan}[\\p{IsHan}·・,、\\s]{0," + (MAX_GLOSS_LENGTH - 1) + "}[)）])?";

    private QuoteLocator() {}

    public static Optional<String> locate(String original, String quote) {
        if (original == null || quote == null || quote.isBlank()) return Optional.empty();
        if (original.contains(quote)) return Optional.of(quote);
        var match = pattern(quote).matcher(original);
        if (!match.find()) return Optional.empty();
        return Optional.of(original.substring(match.start(), match.end()));
    }

    // Every quote character is literal; only between two characters may the original hold extra whitespace or a gloss.
    private static Pattern pattern(String quote) {
        String compact = WHITESPACE_RUN.matcher(quote.strip()).replaceAll(" ");
        var regex = new StringBuilder();
        compact.codePoints().forEach(codePoint -> {
            if (!regex.isEmpty()) regex.append(OMITTED_GLOSS);
            regex.append(codePoint == ' ' ? WHITESPACE : Pattern.quote(Character.toString(codePoint)));
        });
        return Pattern.compile(regex.toString());
    }
}
