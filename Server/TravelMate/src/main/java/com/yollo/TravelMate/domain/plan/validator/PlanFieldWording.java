package com.yollo.TravelMate.domain.plan.validator;

import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;

/**
 * Replaces the plan prompt's input field names in what users read with plain words. The prompt already forbids them,
 * yet a live core run showed "requiredStops를 그대로 반영" in a saved description; the prompt itself names the field,
 * so the server rewrites it deterministically instead of adding another rule. Quotes are left alone: they must match
 * the original text exactly.
 */
public final class PlanFieldWording {
    private PlanFieldWording() {}

    /** Input fields of the plan prompt and the words users see instead. */
    enum InputField {
        REQUIRED_STOPS("requiredStops", "꼭 넣을 장소"),
        CANDIDATES("candidates", "후보 장소"),
        SEARCH_QUERY("searchQuery", "요청 내용"),
        SELECTED_EVIDENCE("selectedEvidence", "장소 설명"),
        EVIDENCE_AVAILABILITY("evidenceAvailability", "장소 설명 유무"),
        NONE_SELECTED("NONE_SELECTED", "설명이 없는 장소"),
        SELECTED_UNASSESSED("SELECTED_UNASSESSED", "설명이 있는 장소"),
        GENERATED_SUPPLEMENT("generatedSupplement", "보충 설명"),
        PLACE_ID("placeId", "장소"),
        STAY_MINUTES("stayMinutes", "머무는 시간"),
        START_AT("startAt", "시작 시간"),
        END_AT("endAt", "종료 시간"),
        TRANSPORT_MODE("transportMode", "이동 방법"),
        UNKNOWN_HOURS_POLICY("unknownHoursPolicy", "운영시간 미확인 장소 처리"),
        ADDITIONAL_REQUEST("additionalRequest", "추가 요청"),
        BUDGET_KRW("budgetKrw", "예산");

        private final String field;
        private final String words;
        private final Pattern pattern;

        InputField(
                String field,
                String words
        ) {
            this.field = field;
            this.words = words;
            // The field as a whole ASCII word, with the Korean particle the model attached to it, if any.
            this.pattern = Pattern.compile("(?<![A-Za-z0-9_])" + Pattern.quote(field) + "(?![A-Za-z0-9_])(을|를|은|는|과|와|이|가)?");
        }
    }

    /** The plan users will see, and which field names were replaced, for the draft record. */
    public record Reworded(
            GeneratedPlan plan,
            List<String> replacedFields
    ) {}

    public static Reworded apply(GeneratedPlan plan) {
        Set<String> replaced = new LinkedHashSet<>();
        // Read in the order users see it, so the record lists fields in that order too.
        String title = reword(plan.planTitle(), replaced);
        String description = reword(plan.planDescription(), replaced);
        var pins = plan.pins().stream().map(pin -> new GeneratedPlan.GeneratedPin(
                pin.placeId(),
                pin.sequence(),
                reword(pin.activity(), replaced),
                reword(pin.reason(), replaced),
                pin.citations()
        )).toList();
        var dialogue = plan.dialogue() == null ? null : plan.dialogue().stream()
                .map(cut -> new DialogueCut(reword(cut.text(), replaced), cut.emotion())).toList();
        var reworded = new GeneratedPlan(
                title,
                description,
                pins,
                dialogue
        );
        return new Reworded(reworded, List.copyOf(replaced));
    }

    static String reword(
            String text,
            Set<String> replaced
    ) {
        if (text == null) return null;
        String result = text;
        for (InputField field : InputField.values()) {
            result = replace(result, field, replaced);
        }
        return result;
    }

    private static String replace(
            String text,
            InputField field,
            Set<String> replaced
    ) {
        Matcher matcher = field.pattern.matcher(text);
        if (!matcher.find()) return text;
        replaced.add(field.field);
        matcher.reset();
        var built = new StringBuilder();
        while (matcher.find()) {
            String particle = matcher.group(1);
            String next = matcher.end() < text.length() ? text.substring(matcher.end(), matcher.end() + 1) : "";
            matcher.appendReplacement(built, Matcher.quoteReplacement(field.words + Particle.after(field.words, particle, next)));
        }
        matcher.appendTail(built);
        return built.toString();
    }

    /** Korean particles that change with the final consonant of the word before them. */
    enum Particle {
        OBJECT("을", "를"),
        TOPIC("은", "는"),
        WITH("과", "와"),
        SUBJECT("이", "가");

        private final String afterConsonant;
        private final String afterVowel;

        Particle(
                String afterConsonant,
                String afterVowel
        ) {
            this.afterConsonant = afterConsonant;
            this.afterVowel = afterVowel;
        }

        static String after(
                String word,
                String particle,
                String next
        ) {
            if (particle == null) return "";
            var matched = Arrays.stream(values())
                    .filter(candidate -> candidate.afterConsonant.equals(particle) || candidate.afterVowel.equals(particle))
                    .findFirst();
            if (matched.isEmpty()) return particle;
            // "이" before more Hangul is usually the copula (이다, 이고), which does not change with the word.
            if (matched.get() == SUBJECT && !next.isEmpty() && isHangul(next.charAt(0))) return particle;
            return endsWithConsonant(word) ? matched.get().afterConsonant : matched.get().afterVowel;
        }

        private static boolean isHangul(char character) {
            return character >= '가' && character <= '힣';
        }

        private static boolean endsWithConsonant(String word) {
            char last = word.charAt(word.length() - 1);
            return isHangul(last) && (last - '가') % 28 != 0;
        }
    }
}
