"""Cross-platform backend selection and container boundary tests."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import chat_runner
import model_config


class PlatformTests(unittest.TestCase):
    def test_windows_automatically_uses_local_python(self):
        with patch.dict(os.environ, {"PLOT_FORGE_RENDER_BACKEND": "auto"}), patch.object(chat_runner.sys, "platform", "win32"), patch.object(chat_runner.shutil, "which", return_value="docker.exe"):
            self.assertEqual(chat_runner.isolation_backend(), "local-python")

    def test_missing_windows_backend_never_runs_directly(self):
        with patch.dict(os.environ, {"PLOT_FORGE_RENDER_BACKEND": "docker"}), patch.object(chat_runner.sys, "platform", "win32"), patch.object(chat_runner.shutil, "which", return_value=None):
            with self.assertRaises(chat_runner.CandidateRenderError) as error:
                chat_runner.render_candidate(".", "charts/a.py", {}, "unused")
            self.assertEqual(error.exception.code, "sandbox_unavailable")

    def test_macos_retains_seatbelt(self):
        with patch.dict(os.environ, {"PLOT_FORGE_RENDER_BACKEND": "seatbelt"}), patch.object(chat_runner.sys, "platform", "darwin"), patch.object(Path, "is_file", return_value=True):
            self.assertEqual(chat_runner.isolation_backend(), "macos-seatbelt")

    def test_docker_has_only_snapshot_and_output_mounts(self):
        with tempfile.TemporaryDirectory(prefix="platform space ") as directory:
            root = Path(directory).resolve()
            command = chat_runner._docker_command(root, root / "packages/projects/demo", {"CHART_OUTPUT": "/work/runtime/figure.png"}, "test-container")
        for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pull=never", "--pids-limit=64"):
            self.assertIn(flag, command)
        mounts = [command[i+1] for i, item in enumerate(command) if item == "--mount"]
        self.assertEqual(len(mounts), 2)
        self.assertTrue(mounts[0].endswith("target=/work,readonly"))
        self.assertTrue(mounts[1].endswith("target=/work/runtime"))
        self.assertNotIn("OPENAI_API_KEY", " ".join(command))
        self.assertEqual(command[-1], "/work/config.json")

    def test_snapshot_override_bytes_match_candidate_hash_on_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            (project / "charts").mkdir(parents=True)
            (project / "charts/a.py").write_bytes(b"# original\r\n")
            source = "# 中文 candidate\nprint(1)\n"
            snapshot = root / "snapshot"
            chat_runner._snapshot(project, snapshot, {"charts/a.py": source}, entry="charts/a.py")
            self.assertEqual((snapshot / "charts/a.py").read_bytes(), source.encode("utf-8"))

    def test_preferences_write_without_unix_fchmod(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(model_config, "CONFIG_PATH", Path(directory) / "settings.json"):
            # Windows has no os.fchmod. Exercise the real platform branch.
            model_config._write_preferences("https://example.com/v1/chat/completions", "model", False, 16384)
            self.assertEqual(model_config._preferences()["model"], "model")


if __name__ == "__main__":
    unittest.main()
