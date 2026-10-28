"""MCP stdio client: initialize -> tools/list -> tools/call, real subprocess."""
from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

class MCPError(Exception):
    pass

class StdioMCPClient:
    def __init__(self, project_dir, workspace, config="mcp.json"):
        self.project_dir = Path(project_dir).resolve()
        self.workspace = Path(workspace).resolve()
        cfg = json.loads((self.project_dir / config).read_text(encoding="utf-8"))
        server = cfg["mcpServers"]["demo"]
        self.cmd = [v.replace("{python}", sys.executable)
                    .replace("{project}", str(self.project_dir)) for v in server["command"]]
        # Frozen applications cannot run a .py server via sys.executable:
        # it is the desktop binary, not a Python interpreter.
        if getattr(sys, "frozen", False):
            binary = "demo_mcp_server.exe" if os.name == "nt" else "demo_mcp_server"
            exe = Path(sys.executable).resolve()
            candidates = [exe.parent / binary]
            # macOS app layout: DesktopAgent.app/Contents/MacOS/DesktopAgent
            candidates.append(exe.parent.parent.parent.parent / binary)
            match = next((x for x in candidates if x.is_file()), None)
            if not match:
                raise MCPError("缺少外部 MCP 可执行文件：" + binary + "。请一起解压 Release 包。")
            self.cmd = [str(match)]
        # Make stdio output predictable across Windows interpreters.
        self.env = dict(os.environ, MCP_WORKSPACE=str(self.workspace),
                        PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        if not getattr(sys, "frozen", False) and len(self.cmd) > 1:
            self.cmd.insert(1, "-u")
        self.server_stderr = []
        self.process = None
        self.inbox = queue.Queue()
        self.id = 0
        self.lock = threading.Lock()
        self._tools = []

    def _pump(self):
        assert self.process is not None
        process = self.process
        for line in process.stdout:
            try:
                self.inbox.put(json.loads(line))
            except json.JSONDecodeError:
                continue
        self.inbox.put({"error": {"message": "MCP server 进程结束"}})

    def _pump_stderr(self):
        process = self.process
        if process is not None and process.stderr is not None:
            for line in process.stderr:
                self.server_stderr.append(line.rstrip()[-400:])
                self.server_stderr = self.server_stderr[-8:]

    def _send(self, obj):
        if self.process is None or self.process.poll() is not None:
            raise MCPError("MCP server 未运行")
        self.process.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def _request(self, method, params=None, timeout=15):
        with self.lock:
            self.id += 1
            rid = self.id
            self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                        "params": params or {}})
            stop = time.monotonic() + timeout
            while time.monotonic() < stop:
                try:
                    item = self.inbox.get(timeout=max(0.01, stop-time.monotonic()))
                except queue.Empty:
                    break
                if item.get("id") == rid:
                    if "error" in item:
                        raise MCPError(str(item["error"].get("message")))
                    return item.get("result", {})
                if "error" in item and "id" not in item:
                    raise MCPError(str(item["error"].get("message")))
            detail = " | ".join(self.server_stderr[-4:])
            state = self.process.poll() if self.process is not None else None
            self.close()
            raise MCPError(f"MCP {method} 超时（server exit={state}; stderr={detail or '无'}）")

    def connect(self):
        if self.process is not None and self.process.poll() is None:
            return self._tools
        self.process = subprocess.Popen(
            self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            cwd=str(self.project_dir), env=self.env, bufsize=1)
        self.inbox = queue.Queue()
        self.server_stderr = []
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        self._request("initialize", {"protocolVersion": "2024-11-05",
                  "capabilities": {}, "clientInfo": {"name": "desktop-agent", "version": "1.0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        results = self._request("tools/list")
        self._tools = results.get("tools", [])
        return self._tools

    def tools(self):
        return self.connect()

    def call(self, name, arguments):
        self.connect()
        if name not in [x["name"] for x in self._tools]:
            raise MCPError("MCP 工具不存在：" + name)
        response = self._request("tools/call", {"name": name, "arguments": arguments})
        texts = [x.get("text", "") for x in response.get("content", []) if x.get("type") == "text"]
        return {"ok": not response.get("isError", False),
                "summary": "外部 MCP 调用：" + name, "content": "\n".join(texts),
                "server": "demo", "mcp_external": True}

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=1)
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except OSError:
                        pass
            self.process = None
