"""근거 수 비교에서 한쪽 실행 누락이나 중복을 성공으로 세지 않는다."""
from __future__ import annotations

import unittest
from Evaluation.tracks.contextual.audit_multi import check_coverage


class MultiEvidenceAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = {'queries': [{'id': 'Q01'}, {'id': 'Q02'}]}
        self.rows = [{'query_id': query['id'], 'evidence_count': count, 'repetition': repetition}
                     for query in self.cases['queries'] for count in (1, 2, 3) for repetition in range(3)]

    def test_missing_repetition_or_variant_is_rejected(self) -> None:
        check_coverage(self.rows, self.cases, 3)
        with self.assertRaises(ValueError):
            check_coverage(self.rows[:-1], self.cases, 3)

    def test_duplicate_execution_cannot_replace_a_missing_partner(self) -> None:
        replaced = self.rows[:-1] + [self.rows[0]]
        with self.assertRaises(ValueError):
            check_coverage(replaced, self.cases, 3)


if __name__ == '__main__':
    unittest.main()
