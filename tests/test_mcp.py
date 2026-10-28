from pathlib import Path
import tempfile
import unittest

from agent.mcp_client import MCPError, StdioMCPClient

PROJECT = Path(__file__).resolve().parents[1]

class MCPTests(unittest.TestCase):
    def test_external_server_tools_list_and_call(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "file.txt").write_text("alpha\nbeta\n")
            client = StdioMCPClient(PROJECT, root)
            try:
                names = [t["name"] for t in client.tools()]
                self.assertIn("count_lines", names)
                self.assertIsNotNone(client.process.pid)
                output = client.call("count_lines", {"path": "file.txt"})
                self.assertTrue(output["ok"])
                self.assertIn("2 行", output["content"])
                with self.assertRaises(MCPError):
                    client.call("count_lines", {"path": "../../etc/passwd"})
            finally:
                client.close()

if __name__ == "__main__":
    unittest.main()
