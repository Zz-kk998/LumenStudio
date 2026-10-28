"""Minimal external MCP stdio server (JSON-RPC 2.0, line-delimited transport).

Run this as a separate process. No internal agent imports required.
Provides a count_lines tool; access is limited to a configured workspace root.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys

ROOT = Path(os.environ.get("MCP_WORKSPACE", ".")).resolve()
TOOL = {"name": "count_lines",
        "description": "统计工作区中指定 UTF-8 文本文件的行数（外部 MCP 服务）。",
        "inputSchema": {"type": "object", "properties": {
            "path": {"type": "string", "description": "工作区内的相对文件路径"}
        }, "required": ["path"], "additionalProperties": False}}


def respond(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req):
    method, params = req.get("method"), req.get("params", {})
    if method == "initialize":
        return {"protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "desktop-agent-demo", "version": "1.0"}}
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "tools/call":
        if params.get("name") != "count_lines":
            raise ValueError("unknown tool")
        path = params.get("arguments", {}).get("path", "")
        if not isinstance(path, str) or not path:
            raise ValueError("path required")
        p = (ROOT / path).resolve()
        try:
            p.relative_to(ROOT)
        except ValueError:
            raise ValueError("路径越界") from None
        if not p.is_file() or p.stat().st_size > 1_000_000:
            raise ValueError("文件不存在或过大")
        lines = len(p.read_text(encoding="utf-8").splitlines())
        return {"content": [{"type": "text", "text": f"{path} 共 {lines} 行（由外部 MCP server 计算）"}],
                "isError": False}
    raise ValueError("method not found")


if __name__ == "__main__":
    for raw in sys.stdin:
        try:
            req = json.loads(raw)
            if "id" not in req:  # notifications/initialized
                continue
            result = handle(req)
            respond({"jsonrpc": "2.0", "id": req["id"], "result": result})
        except Exception as exc:
            ident = req.get("id") if isinstance(locals().get("req"), dict) else None
            if ident is not None:
                respond({"jsonrpc": "2.0", "id": ident,
                         "error": {"code": -32000, "message": str(exc)}})
