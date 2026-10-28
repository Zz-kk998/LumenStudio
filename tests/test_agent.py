import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest

from agent.loop import AgentRunner, ScriptedDemoModel, ToolManager
from agent.trace import Tracer
from agent.workspace import Workspace

PROJECT = Path(__file__).resolve().parents[1]

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(PROJECT / "examples/workspace", self.root / "workspace")
        self.trace = Tracer(self.root / "trace.jsonl")
        self.ws = Workspace(self.root / "workspace")
        self.mgr = ToolManager(self.ws, self.trace, PROJECT,
                               approval=lambda command: command == "python -m unittest test_stats -v")

    def tearDown(self):
        self.mgr.close()
        self.temp.cleanup()

    def events(self):
        return [json.loads(x) for x in (self.root / "trace.jsonl").read_text().splitlines()]

    def test_failure_recovery_and_external_mcp(self):
        names = [x["function"]["name"] for x in self.mgr.specifications()]
        self.assertEqual(names[:4], ["read", "write", "edit", "bash"])
        self.assertIn("mcp_demo_count_lines", names)
        result = AgentRunner(ScriptedDemoModel("recovery"), self.mgr, self.trace).run(
            "修复 mean 并测试")
        self.assertEqual(result["status"], "done", result)
        self.assertIn("测试已通过", result["answer"])
        self.assertIn("MCP 调用成功", result["answer"])
        self.assertEqual(self.ws.resolve("stats.py").read_text().count(
            "return total / len(nums)"), 1)
        self.assertTrue(self.ws.resolve("notes/fix_log.md").exists())
        events = self.events()
        tools = [e for e in events if e["type"] == "tool"]
        self.assertTrue(any(e["name"] == "edit" and not e["result"]["ok"] for e in tools))
        self.assertTrue(any(e["name"] == "bash" and e["result"]["exit_code"] == 1
                            for e in tools))
        self.assertTrue(any(e["name"] == "bash" and e["result"]["exit_code"] == 0
                            for e in tools))
        self.assertTrue(any(e["name"] == "mcp_demo_count_lines" and
                            e["result"].get("mcp_external") for e in tools))

    def test_access_boundary_and_recovery(self):
        result = AgentRunner(ScriptedDemoModel("boundary"), self.mgr, self.trace).run(
            "读文件")
        self.assertEqual(result["status"], "done")
        tools = [e for e in self.events() if e["type"] == "tool"]
        self.assertFalse(tools[0]["result"]["ok"])
        self.assertTrue(tools[1]["result"]["ok"])

    def test_finite_steps_genuine_stop(self):
        runner = AgentRunner(ScriptedDemoModel("interrupt"), self.mgr, self.trace,
                             max_steps=1)
        result = runner.run("持续检查")
        self.assertEqual(result["status"], "stopped")
        self.assertIn("上限", result["answer"])
        self.assertTrue(any(x["type"] == "stopped" for x in self.events()))


    def test_stop_during_slow_model_request(self):
        entered = threading.Event()
        hold = threading.Event()
        class SlowBackend:
            def complete(self, messages, tools):
                entered.set()
                hold.wait(3)
                return {"content": "不应被当作已完成", "tool_calls": []}
        runner = AgentRunner(SlowBackend(), self.mgr, self.trace, max_steps=2)
        output = {}
        worker = threading.Thread(target=lambda: output.update(runner.run("请执行长请求")),
                                  daemon=True)
        worker.start()
        self.assertTrue(entered.wait(3), "模型应该已开始处理")
        runner.stop()
        worker.join(timeout=2)
        hold.set()
        self.assertFalse(worker.is_alive(), "停止后不应继续等待模型")
        self.assertEqual(output["status"], "stopped")
        self.assertTrue(any(e["type"] == "interrupt" for e in self.events()))

    def test_bash_user_denial(self):
        denied = ToolManager(self.ws, self.trace, PROJECT, approval=lambda cmd: False)
        try:
            result = denied.call("bash", {"command": "python -V"})
            self.assertFalse(result["ok"])
            self.assertIn("拒绝", result["summary"])
        finally:
            denied.close()

if __name__ == "__main__":
    unittest.main()
