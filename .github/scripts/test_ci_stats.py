"""Tests for ci_stats.py (KAN-239). Run: python -m unittest discover -s .github/scripts"""

import unittest

import ci_stats

PYTEST_XML = """<testsuites><testsuite name="pytest">
<testcase classname="tests.api.test_a.TestA" file="tests/api/test_a.py" name="t1" time="2.5"/>
<testcase classname="tests.api.test_a.TestA" file="tests/api/test_a.py" name="t2" time="1.5"/>
<testcase classname="tests.core.test_b" name="t3" time="0.2"/>
</testsuite></testsuites>"""

VITEST_XML = """<testsuites><testsuite name="src/__tests__/unit/x.test.ts" tests="1">
<testcase classname="src/__tests__/unit/x.test.ts" name="works" time="0.7"/></testsuite></testsuites>"""


class SlowestFiles(unittest.TestCase):
    def test_sums_time_per_file_slowest_first(self):
        rows = ci_stats.slowest_files(PYTEST_XML)
        self.assertEqual(rows[0], ("tests/api/test_a.py", 4.0, 2))
        self.assertEqual(rows[1][0], "tests.core.test_b")

    def test_limit_applies(self):
        self.assertEqual(len(ci_stats.slowest_files(PYTEST_XML, 1)), 1)

    def test_vitest_uses_classname(self):
        self.assertEqual(ci_stats.slowest_files(VITEST_XML)[0][0], "src/__tests__/unit/x.test.ts")

    def test_render_has_table_rows(self):
        out = ci_stats.render_slowest("Slowest", ci_stats.slowest_files(PYTEST_XML))
        self.assertIn("| `tests/api/test_a.py` | 4.0 | 2 |", out)


class Percentiles(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(ci_stats.percentile([], 50), 0.0)

    def test_nearest_rank(self):
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        self.assertEqual(ci_stats.percentile(values, 50), 50)
        self.assertEqual(ci_stats.percentile(values, 90), 90)


class JobTiming(unittest.TestCase):
    def test_skips_skipped_jobs_and_short_steps(self):
        jobs = [
            {
                "name": "Backend",
                "conclusion": "success",
                "started_at": "2026-10-17T10:00:00Z",
                "completed_at": "2026-10-17T10:05:00Z",
                "steps": [
                    {"name": "pytest", "started_at": "2026-10-17T10:00:10Z", "completed_at": "2026-10-17T10:04:10Z"},
                    {"name": "tiny", "started_at": "2026-10-17T10:00:00Z", "completed_at": "2026-10-17T10:00:01Z"},
                ],
            },
            {
                "name": "Frontend",
                "conclusion": "skipped",
                "started_at": "2026-10-17T10:00:00Z",
                "completed_at": "2026-10-17T10:00:00Z",
                "steps": [],
            },
        ]
        out = ci_stats.render_job_timing(jobs)
        self.assertIn("| **Backend** | **300** |", out)
        self.assertIn("pytest | 240 |", out)
        self.assertNotIn("tiny", out)
        self.assertNotIn("Frontend", out)


class Trend(unittest.TestCase):
    def test_only_successful_runs_are_counted(self):
        runs = [
            {"name": "CI", "conclusion": "success", "run_started_at": "2026-10-17T10:00:00Z", "updated_at": "2026-10-17T10:03:00Z"},
            {"name": "CI", "conclusion": "failure", "run_started_at": "2026-10-17T10:00:00Z", "updated_at": "2026-10-17T10:09:00Z"},
        ]
        durations = ci_stats.run_durations(runs)
        self.assertEqual(durations["CI"], [180.0])
        self.assertIn("| CI | 1 | 180 | 180 |", ci_stats.render_trend(durations))


if __name__ == "__main__":
    unittest.main()
