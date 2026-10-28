"""Workspace-limited read/write/edit and observable shell execution."""
from __future__ import annotations

import base64
import difflib
import mimetypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any


class ToolError(Exception):
    """A tool failed safely. Return this failure to the model."""


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str) -> Path:
        if not isinstance(path, str) or not path.strip():
            raise ToolError("path 必须是非空字符串")
        candidate = (self.root / path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise ToolError("路径越界：禁止访问工作区外的文件") from None
        return candidate

    def _regular_file(self, path: str) -> Path:
        p = self.resolve(path)
        if not p.is_file():
            raise ToolError("文件不存在或不是普通文件：" + path)
        if p.stat().st_size > 3 * 1024 * 1024:
            raise ToolError("文件超过 3MB，请缩小读取范围或拆分")
        return p

    def read(self, path: str, offset: int = 1, limit: int = 180) -> dict[str, Any]:
        p = self._regular_file(path)
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            if p.stat().st_size > 1_500_000:
                raise ToolError("图片超过 1.5MB")
            mime = mimetypes.guess_type(p.name)[0] or "image/png"
            url = "data:" + mime + ";base64," + base64.b64encode(p.read_bytes()).decode("ascii")
            return {"ok": True, "summary": f"读取图片 {path} ({p.stat().st_size} bytes)",
                    "image_data_url": url}
        if offset < 1 or limit < 1 or limit > 500:
            raise ToolError("offset 必须 ≥1，limit 必须在 1..500 范围内")
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            raise ToolError("不是 UTF-8 文本文件；图片可按多模态图片读取") from None
        selected = lines[offset - 1:offset - 1 + limit]
        numbered = "\n".join(f"{offset+i:>4} | {line}" for i, line in enumerate(selected))
        return {"ok": True, "summary": f"{path}: 共 {len(lines)} 行，显示 {len(selected)} 行",
                "content": numbered, "total_lines": len(lines),
                "has_more": offset - 1 + limit < len(lines)}

    def _atomic_write(self, p: Path, content: str) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=str(p.parent),
                prefix=".agent_", delete=False
            ) as fp:
                tmp_name = fp.name
                fp.write(content)
                fp.flush()
                os.fsync(fp.fileno())
            if p.exists():
                os.chmod(tmp_name, p.stat().st_mode)
            os.replace(tmp_name, p)
        finally:
            if tmp_name and os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def write(self, path: str, content: str) -> dict[str, Any]:
        if not isinstance(content, str):
            raise ToolError("content 必须是字符串")
        if len(content.encode("utf-8")) > 1_000_000:
            raise ToolError("单次写入不能超过 1MB")
        p = self.resolve(path)
        if p.is_dir():
            raise ToolError("目标是目录，不能写入")
        before = p.read_text(encoding="utf-8") if p.exists() and p.stat().st_size < 1_000_000 else ""
        self._atomic_write(p, content)
        return {"ok": True, "summary": f"已原子写入 {path}",
                "old_lines": len(before.splitlines()), "new_lines": len(content.splitlines()),
                "diff": self._diff(before, content, path)}

    @staticmethod
    def _diff(before: str, after: str, path: str) -> str:
        return "".join(list(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}"
        ))[:130])

    def edit(self, path: str, old: str, new: str) -> dict[str, Any]:
        if not isinstance(old, str) or not old:
            raise ToolError("old 必须是非空精确匹配字符串")
        if not isinstance(new, str):
            raise ToolError("new 必须是字符串")
        p = self._regular_file(path)
        try:
            before = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ToolError("只能编辑 UTF-8 文本文件") from None
        n = before.count(old)
        if n != 1:
            raise ToolError(f"精确替换要求唯一命中，实际命中 {n} 次；没有修改文件")
        after = before.replace(old, new, 1)
        self._atomic_write(p, after)
        return {"ok": True, "summary": f"已精确修改 {path}（命中 1 次）",
                "diff": self._diff(before, after, path),
                "old_lines": len(before.splitlines()), "new_lines": len(after.splitlines())}

    def bash(self, command: str, timeout: int = 10,
             cancel: threading.Event | None = None) -> dict[str, Any]:
        if not isinstance(command, str) or not command.strip():
            raise ToolError("命令不能为空")
        if not isinstance(timeout, int) or not (1 <= timeout <= 30):
            raise ToolError("timeout 必须是 1..30 秒")
        # WARNING: Working directory is restricted, but shell is NOT sandboxed.
        # GUI always asks the user before executing model-requested commands.
        # VS Code can run a valid interpreter which is not on the Windows PATH.
        # Add its directory for child shell commands (e.g. `python -m unittest`).
        child_env = os.environ.copy()
        if not getattr(sys, "frozen", False):
            interpreter_dir = str(Path(sys.executable).resolve().parent)
            child_env["PATH"] = interpreter_dir + os.pathsep + child_env.get("PATH", "")
        kwargs = {"cwd": str(self.root), "stdout": subprocess.PIPE,
                  "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8",
                  "errors": "replace", "shell": True, "env": child_env}
        if os.name != "nt":
            kwargs["start_new_session"] = True
        else:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        start = time.monotonic()
        proc = subprocess.Popen(command, **kwargs)
        stdout, stderr = "", ""
        timed_out = False
        interrupted = False
        while True:
            if cancel and cancel.is_set():
                interrupted = True
                break
            if time.monotonic() - start >= timeout:
                timed_out = True
                break
            try:
                stdout, stderr = proc.communicate(timeout=0.12)
                break
            except subprocess.TimeoutExpired:
                pass
        if timed_out or interrupted:
            try:
                if os.name != "nt":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        max_chars = 7000
        return {"ok": proc.returncode == 0 and not timed_out and not interrupted,
                "summary": "命令完成" if proc.returncode == 0 and not (timed_out or interrupted)
                           else ("命令已中断" if interrupted else "命令超时" if timed_out
                                 else f"非零退出码：{proc.returncode}"),
                "stdout": stdout[-max_chars:], "stderr": stderr[-max_chars:],
                "exit_code": proc.returncode, "timeout": timed_out,
                "interrupted": interrupted,
                "duration_seconds": round(time.monotonic() - start, 2)}
