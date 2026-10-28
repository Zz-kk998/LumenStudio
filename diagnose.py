"""运行 `py diagnose.py` 检查当前环境与 MCP 连接。"""
import os
from pathlib import Path
import shutil
import sys

from agent.mcp_client import StdioMCPClient
from agent.workspace import Workspace

base = Path(__file__).resolve().parent
print("Python 当前解释器:", sys.executable)
print("终端 python 命令:", shutil.which("python") or "未找到（可由程序自动补 PATH）")
print("工作目录:", os.getcwd())
print("MCP server 文件存在:", (base / "server/demo_mcp_server.py").is_file())
ws = Workspace(base / "examples/workspace")
print("shell 中调用 Python:")
print(ws.bash("python --version", timeout=8))
print("MCP 连接测试:")
client = StdioMCPClient(base, ws.root)
try:
    tools = client.tools()
    print("MCP tools/list:", [t["name"] for t in tools])
    print("MCP tools/call:", client.call("count_lines", {"path": "stats.py"}))
except Exception as e:
    print("MCP 连接失败:", type(e).__name__, str(e))
finally:
    client.close()
