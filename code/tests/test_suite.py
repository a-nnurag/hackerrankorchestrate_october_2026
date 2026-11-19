"""unittest wrapper around the offline evaluation suites (one test method per suite).

    python -m unittest discover -s code/tests -t code        # from the repository root
    python -m unittest tests.test_suite -v                   # from inside code/

Each test runs the suite as a subprocess with the same command line run_all.py uses (evaluation/run_all.py
holds the suite table) and asserts return code 0.  The set is the quick set plus metamorphic.  The pipeline
is run once in setUpClass because the validator, metamorphic and provenance suites read output.csv.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "evaluation"))

import run_all  # noqa: E402


class OfflineSuites(unittest.TestCase):
    """One test per offline suite; each asserts that the suite's subprocess exits with code 0."""

    @classmethod
    def setUpClass(cls) -> None:
        """Run the pipeline once so output.csv exists."""
        # output.csv must exist and be fresh before the suites that read it
        rc, _, out = run_all.run_suite(run_all.PIPELINE)
        if rc != 0:
            raise RuntimeError(f"pipeline run failed (exit {rc}):\n{out[-2000:]}")

    def assert_suite_passes(self, name: str) -> None:
        """Run one suite from the run_all table and assert exit code 0."""
        rc, _, out = run_all.run_suite(run_all.BY_NAME[name])
        self.assertEqual(rc, 0, f"{name} exited {rc}; last output:\n{out[-2000:]}")

    def test_golden_check(self) -> None:
        """Runs golden_check as a subprocess."""
        self.assert_suite_passes("golden_check")

    def test_validate_output(self) -> None:
        """Runs validate_output as a subprocess."""
        self.assert_suite_passes("validate_output")

    def test_validate_gold(self) -> None:
        """Runs validate_gold as a subprocess."""
        self.assert_suite_passes("validate_gold")

    def test_synthetic_cases(self) -> None:
        """Runs synthetic_cases as a subprocess."""
        self.assert_suite_passes("synthetic_cases")

    def test_metamorphic(self) -> None:
        """Runs metamorphic as a subprocess."""
        self.assert_suite_passes("metamorphic")

    def test_classifier_offline(self) -> None:
        """Runs classifier_offline as a subprocess."""
        self.assert_suite_passes("test_classifier")

    def test_condition_llm_offline(self) -> None:
        """Runs condition_llm_offline as a subprocess."""
        self.assert_suite_passes("test_condition_llm")

    def test_groq_client(self) -> None:
        """Runs groq_client as a subprocess."""
        self.assert_suite_passes("test_groq_client")

    def test_groq_limits(self) -> None:
        """Runs groq_limits as a subprocess."""
        self.assert_suite_passes("test_groq_limits")

    def test_provenance_check(self) -> None:
        """Runs provenance_check as a subprocess."""
        self.assert_suite_passes("provenance_check")

    def test_main_eval(self) -> None:
        """Runs main_eval as a subprocess."""
        self.assert_suite_passes("main_eval")


if __name__ == "__main__":
    unittest.main()
