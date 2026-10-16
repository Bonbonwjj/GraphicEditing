import subprocess
import tempfile
import unittest
from pathlib import Path

from git_support import git_status, record_change


class GitSupportTests(unittest.TestCase):
    def test_non_repository_is_reported_without_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = git_status(Path(tmp))

        self.assertFalse(status["enabled"])
        self.assertEqual("not-a-repository", status["reason"])

    def test_record_change_is_a_noop_outside_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = record_change(Path(tmp), [Path(tmp) / "anything"], "message")

        self.assertFalse(result["enabled"])
        self.assertFalse(result["committed"])
        self.assertEqual("not-a-repository", result["reason"])

    def test_record_change_commits_inside_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            source = repo / "note.txt"
            source.write_text("hello", encoding="utf-8")

            result = record_change(repo, [source], "Add note")

            self.assertTrue(result["enabled"])
            self.assertTrue(result["committed"])
            count = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual("1", count.stdout.strip())


if __name__ == "__main__":
    unittest.main()
