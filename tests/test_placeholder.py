from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from caasys.engine import ContinuousEngine
from caasys.models import Feature


class EngineSmokeTests(unittest.TestCase):
    def _workspace_temp_root(self) -> Path:
        base = Path(__file__).resolve().parent / ".tmp"
        base.mkdir(parents=True, exist_ok=True)
        root = base / f"case-{uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def test_initialize_and_successful_iteration(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Ship MVP")

        engine.add_feature(
            Feature(
                id="F-001",
                category="smoke",
                description="Run success commands",
                priority=1,
                implementation_commands=['python -c "print(\'implement\')"'],
                verification_command='python -c "print(\'verify\')"',
            )
        )

        report = engine.run_iteration()
        self.assertTrue(report.success)
        self.assertEqual(report.feature_id, "F-001")
        self.assertIn("Iteration 1: completed F-001", engine.get_status().done)
        self.assertTrue(engine.list_features()[0].passes)
        self.assertTrue((root / "AGENT_STATUS.md").exists())

    def test_failed_iteration_records_blocker(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Handle failures")

        engine.add_feature(
            Feature(
                id="F-ERR",
                category="smoke",
                description="Fail implementation command",
                priority=1,
                implementation_commands=['python -c "import sys; sys.exit(2)"'],
                verification_command='python -c "print(\'should not run\')"',
            )
        )

        report = engine.run_iteration()
        status = engine.get_status()
        self.assertFalse(report.success)
        self.assertFalse(engine.list_features()[0].passes)
        self.assertTrue(any("F-ERR" in blocker for blocker in status.blockers))

    def test_feature_without_commands_is_not_marked_done(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Reject empty features")

        engine.add_feature(
            Feature(
                id="F-EMPTY",
                category="smoke",
                description="No implementation or verification commands",
                priority=1,
            )
        )

        report = engine.run_iteration()
        status = engine.get_status()
        self.assertFalse(report.success)
        self.assertFalse(engine.list_features()[0].passes)
        self.assertTrue(any("F-EMPTY" in blocker for blocker in status.blockers))


if __name__ == "__main__":
    unittest.main(verbosity=2)
