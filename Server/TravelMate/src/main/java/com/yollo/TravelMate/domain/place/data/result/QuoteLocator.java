package com.yollo.TravelMate.domain.place.data.result;

import java.util.Optional;

/**
 * Finds where a model's quote sits in the original text and returns the original's own characters.
 * Only two differences are forgiven, because they do not change what the source says: a short parenthetical
 * gloss such as "(昌慶宮)" and runs of whitespace. Anything else, including other punctuation, is not a match.
 */
public final class QuoteLocator {
    private static final int MAX_GLOSS_LENGTH = 30;
    private static final char SPACE = ' ';

    private QuoteLocator() {}

    public static Optional<String> locate(String original, String quote) {
        if (original == null || quote == null || quote.isBlank()) return Optional.empty();
        if (original.contains(quote)) return Optional.of(quote);
        var text = Normalized.of(original);
        String wanted = Normalized.of(quote).text().strip();
        if (wanted.isEmpty()) return Optional.empty();
        int start = text.text().indexOf(wanted);
        if (start < 0) return Optional.empty();
        int end = start + wanted.length() - 1;
        return Optional.of(original.substring(text.originalIndex()[start], text.originalIndex()[end] + 1));
    }

    /** The text without glosses and with single spaces, plus where each kept character came from. */
    private record Normalized(String text, int[] originalIndex) {
        static Normalized of(String source) {
            var kept = new StringBuilder(source.length());
            int[] positions = new int[source.length()];
            int index = 0;
            while (index < source.length()) {
                int glossEnd = glossEnd(source, index);
                if (glossEnd > index) {
                    index = glossEnd;
                    continue;
                }
                char character = source.charAt(index);
                if (Character.isWhitespace(character)) {
                    if (kept.isEmpty() || kept.charAt(kept.length() - 1) != SPACE) {
                        positions[kept.length()] = index;
                        kept.append(SPACE);
                    }
                    index++;
                    continue;
                }
                positions[kept.length()] = index;
                kept.append(character);
                index++;
            }
            return new Normalized(kept.toString(), positions);
        }

        // A gloss is one bracketed run without nesting, short enough to be an annotation rather than a clause.
        private static int glossEnd(String source, int start) {
            char open = source.charAt(start);
            char close = open == '(' ? ')' : open == '（' ? '）' : 0;
            if (close == 0) return start;
            int end = source.indexOf(close, start + 1);
            if (end < 0 || end - start - 1 > MAX_GLOSS_LENGTH) return start;
            String inside = source.substring(start + 1, end);
            if (inside.indexOf(open) >= 0) return start;
            return end + 1;
        }
    }
}
