from __future__ import annotations

import json
from pathlib import Path
import unittest

suite = unittest.defaultTestLoader.discover("/workspace/embedding-server/tests")
with Path("/output/server-tests.log").open("w", encoding="utf-8") as stream:
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
report = {
    "tests_run": result.testsRun,
    "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
    "failures": [{"test": str(case), "traceback": trace} for case, trace in result.failures],
    "errors": [{"test": str(case), "traceback": trace} for case, trace in result.errors],
    "skipped": [{"test": str(case), "reason": reason} for case, reason in result.skipped],
    "successful": result.wasSuccessful(),
}
Path("/output/tests.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False), flush=True)
raise SystemExit(0 if result.wasSuccessful() else 1)
