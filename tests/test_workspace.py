import os
from pathlib import Path
import tempfile
import threading
import unittest

from agent.workspace import ToolError, Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_read_numbered_and_paginated(self):
        self.ws.write("foo/a.txt", "one\ntwo\nthree\n")
        value = self.ws.read("foo/a.txt", offset=2, limit=1)
        self.assertTrue(value["has_more"])
        self.assertEqual(value["total_lines"], 3)
        self.assertIn("2 | two", value["content"])

    def test_path_traversal_and_absolute_paths_blocked(self):
        for value in ["../outside.txt", "../../etc/passwd",
                      str(Path(self.temp.name).parent / "outside.txt")]:
            with self.assertRaisesRegex(ToolError, "越界"):
                self.ws.read(value)

    def test_symlink_escaping_workspace_is_blocked(self):
        other = tempfile.TemporaryDirectory()
        try:
            (Path(other.name) / "secret.txt").write_text("secret")
            try:
                (Path(self.temp.name) / "link").symlink_to(other.name, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("OS disallows symlinks")
            with self.assertRaisesRegex(ToolError, "越界"):
                self.ws.read("link/secret.txt")
        finally:
            other.cleanup()

    def test_atomic_write_creates_parent_and_reports_diff(self):
        data = self.ws.write("nested/hello.py", "x = 1\n")
        self.assertTrue(data["ok"])
        self.assertEqual(self.ws.resolve("nested/hello.py").read_text(), "x = 1\n")
        change = self.ws.write("nested/hello.py", "x = 2\n")
        self.assertIn("-x = 1", change["diff"])
        self.assertIn("+x = 2", change["diff"])

    def test_edit_requires_single_exact_match_without_partial_write(self):
        self.ws.write("file.txt", "apple apple\n")
        with self.assertRaisesRegex(ToolError, "2 次"):
            self.ws.edit("file.txt", "apple", "pear")
        with self.assertRaisesRegex(ToolError, "0 次"):
            self.ws.edit("file.txt", "banana", "pear")
        self.assertEqual(self.ws.resolve("file.txt").read_text(), "apple apple\n")
        change = self.ws.edit("file.txt", "apple apple", "pear")
        self.assertIn("+pear", change["diff"])
        self.assertEqual(self.ws.resolve("file.txt").read_text(), "pear\n")

    def test_bash_returns_stderr_and_nonzero_exit(self):
        res = self.ws.bash("python -c \"import sys; print('bad', file=sys.stderr); sys.exit(3)\"")
        self.assertFalse(res["ok"])
        self.assertEqual(res["exit_code"], 3)
        self.assertIn("bad", res["stderr"])

    def test_bash_timeout_is_real(self):
        res = self.ws.bash("python -c \"import time; time.sleep(3)\"", timeout=1)
        self.assertFalse(res["ok"])
        self.assertTrue(res["timeout"])

    def test_bash_already_cancelled(self):
        flag = threading.Event()
        flag.set()
        res = self.ws.bash("python -c \"import time; time.sleep(3)\"", cancel=flag)
        self.assertFalse(res["ok"])
        self.assertTrue(res["interrupted"])


if __name__ == "__main__":
    unittest.main()
