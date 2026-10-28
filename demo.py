"""Reproduce demo traces without an API key: python demo.py --mode recovery."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import sys
import tempfile

from agent.loop import AgentRunner, ScriptedDemoModel, ToolManager
from agent.trace import Tracer
from agent.workspace import Workspace

PROJECT = Path(__file__).resolve().parent

def run(mode="recovery", output=None, max_steps=None, callback=None):
    root = Path(tempfile.mkdtemp(prefix="desktop_agent_example_"))
    shutil.copytree(PROJECT / "examples" / "workspace", root, dirs_exist_ok=True)
    dest = Path(output or PROJECT / "docs" / f"trace_{mode}.jsonl")
    if dest.exists():
        dest.unlink()
    tracer = Tracer(dest, callback=callback)
    ws = Workspace(root)
    # ONLY scripted offline test commands get this permission; GUI always prompts the user.
    def approve(cmd):
        return cmd == "python -m unittest test_stats -v"
    manager = ToolManager(ws, tracer, PROJECT, approval=approve)
    runner = AgentRunner(ScriptedDemoModel(mode), manager, tracer,
                         max_steps=max_steps or (1 if mode == "interrupt" else 12))
    try:
        result = runner.run("检查 stats.py 的 mean 函数，复现失败，修复并运行测试，再调用一次 MCP。")
    finally:
        manager.close()
    if callback:
        callback({"type": "info", "message": "示例工作区：" + str(root)})
    return {"result": result, "workspace": str(root), "trace": str(dest)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["recovery", "boundary", "interrupt"],
                        default="recovery")
    parser.add_argument("--output")
    parser.add_argument("--max-steps", type=int)
    args = parser.parse_args()
    info = run(args.mode, args.output, args.max_steps,
               callback=lambda e: print(f"[{e['type']}] {e['message']}"))
    print("RESULT:", info["result"])
    print("WORKSPACE:", info["workspace"])
    print("TRACE:", info["trace"])
    sys.exit(0 if info["result"]["status"] in ("done", "stopped") else 1)
