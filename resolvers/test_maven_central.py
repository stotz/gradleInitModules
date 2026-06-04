"""Standalone tests for the Maven Central resolver.

Run with: python resolvers/test_maven_central.py
No network access or third-party dependencies are required; _is_prerelease is a
pure function and the resolver is instantiated without running __init__.
"""

import importlib.util
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("maven_central", str(_HERE / "maven_central.py"))
maven_central = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(maven_central)

_RESOLVER_CLS = next(
    cls for cls in vars(maven_central).values()
    if isinstance(cls, type) and hasattr(cls, "_is_prerelease")
)


class TestIsPrerelease(unittest.TestCase):
    """Stable versions must never be classified as pre-releases, and every
    milestone/RC/snapshot/etc. must be detected (including M4+ and dotted M1)."""

    def setUp(self):
        # Skip __init__ (it creates cache directories); _is_prerelease is pure.
        self.r = _RESOLVER_CLS.__new__(_RESOLVER_CLS)

    def test_stable_versions(self):
        for v in ("4.0.6", "4.0.2", "26.0.1", "6.1.0", "2.4.0", "9.5.1",
                  "3.1.5", "1.14.11", "11.2.3", "0.6.3", "1.5.34", "1.2.3.RELEASE",
                  "1.2.3.Final"):
            self.assertFalse(self.r._is_prerelease(v), v)

    def test_prerelease_versions(self):
        for v in ("4.1.0-M4", "4.1.0-M3", "7.0.0-RC1", "1.0-beta", "2.0.0-alpha1",
                  "3.0-SNAPSHOT", "27-ea+5", "1.0.0.M1", "6.0.0-rc.1",
                  "1.0-milestone-2"):
            self.assertTrue(self.r._is_prerelease(v), v)

    def test_latest_stable_below_milestone(self):
        # Regression: 4.1.0-M4 must not shadow the latest stable 4.0.6.
        versions = ["4.1.0-M4", "4.0.6", "4.0.5", "4.0.2", "3.5.10"]
        stable = [v for v in versions if not self.r._is_prerelease(v)]
        self.assertEqual(stable[0], "4.0.6")


if __name__ == "__main__":
    unittest.main(verbosity=2)
