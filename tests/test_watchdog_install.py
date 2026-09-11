from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops/macos"))
import configure_watchdog as setup


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.agents = self.root / "agents"
        self.agents.mkdir()
        (self.root / "scripts").mkdir()
        for name in ("job_runtime.py", "job_status.py", "job_watchdog.py", "refresh_session.py"):
            (self.root / "scripts" / name).write_text("# validated fixture\n")
        self.plist = self.agents / (setup.LABEL + ".plist")
        self.valid = patch.object(setup, "valid_plist", return_value=True)
        self.valid.start()
        self.addCleanup(self.valid.stop)

    def test_dry_run_cannot_modify_registration_or_files(self):
        with patch.object(setup, "launch_status", return_value={"loaded": False}), \
             patch.object(setup, "command") as command:
            result = setup.configure(self.root, self.agents)
        self.assertEqual(result["validated_collectors"], 8)
        self.assertFalse(self.plist.exists())
        command.assert_not_called()

    def test_bootstrap_failure_preserves_all_existing_jobs_and_proxy(self):
        with patch.object(setup, "launch_status", side_effect=[{"loaded": False}, {"loaded": True}]), \
             patch.object(setup, "command", return_value={"accepted": False}) as command:
            with self.assertRaisesRegex(RuntimeError, "existing collectors remain loaded"):
                setup.configure(self.root, self.agents, True, True)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args[0][0][0], "bootstrap")
        self.assertEqual(command.call_args[0][0][-1], str(self.plist))

    def test_existing_watchdog_runs_without_force_and_proxy_restart_is_explicit(self):
        with patch.object(setup, "launch_status", return_value={"loaded": True, "running": False}), \
             patch.object(setup, "command", return_value={"accepted": True}) as command:
            setup.configure(self.root, self.agents, True)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args[0][0][0], "kickstart")
        self.assertNotIn("-k", command.call_args[0][0])

    def test_unknown_launch_state_causes_no_writes(self):
        with patch.object(setup, "launch_status", return_value={"loaded": None}), \
             patch.object(setup, "command") as command:
            with self.assertRaisesRegex(RuntimeError, "no configuration changed"):
                setup.configure(self.root, self.agents, True)
        self.assertFalse(self.plist.exists())
        command.assert_not_called()

    def test_existing_different_plist_is_preserved(self):
        content = plistlib.dumps({"Label": setup.LABEL, "StartInterval": 60})
        self.plist.write_bytes(content)
        with patch.object(setup, "command") as command:
            with self.assertRaisesRegex(RuntimeError, "preserved for review"):
                setup.configure(self.root, self.agents, True)
        self.assertEqual(self.plist.read_bytes(), content)
        command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
