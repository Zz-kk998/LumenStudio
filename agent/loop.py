"""Observable agent loop with finite steps, failures, cancellation, and MCP."""
from __future__ import annotations
import json
import threading
import uuid

from .workspace import ToolError


SYSTEM_PROMPT = """你是工作区内的智能编程助手。你可以使用 read、write、edit、bash 四个内置工具，
以及名称以 mcp_ 开头的外部 MCP 工具。
规则：
1. 动手前先 read 相关文件；不确定的地方先查看、再修改。
2. 优先使用 edit 精确替换小范围文本，检查 diff；失败要解释并重新读取修正。
3. 改代码后必须运行测试（bash），认真检查 stdout、stderr、exit_code，不能把失败当成功。
4. 只能操作工作区内的目标文件；bash 将请求人类确认。
5. 不要声称执行过未执行的工具，也不得声称没有通过的测试已通过。
6. 任务结束请用中文简短描述改动、测试结果、尚存风险。
7. 不能确定时请停止并请求人工介入，不要无限循环。"""


def tool_spec(name, description, fields, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": fields,
                       "required": required, "additionalProperties": False}}}

S = lambda desc, typ="string": {"type": typ, "description": desc}
BUILTINS = [
    tool_spec("read", "读取工作区文件，按行返回；支持图像读取多模态内容。",
              {"path": S("相对路径"), "offset": S("从第几行开始，默认1", "integer"),
               "limit": S("读取行数上限，默认180", "integer")}, ["path"]),
    tool_spec("write", "原子写入 UTF-8 文件，自动创建目录并返回 diff。",
              {"path": S("相对路径"), "content": S("完整的新文件内容")}, ["path", "content"]),
    tool_spec("edit", "严格唯一命中的精确字符串替换；0次或多次命中会拒绝写入并返回错误。",
              {"path": S("相对路径"), "old": S("必须精确匹配且唯一的原文"),
               "new": S("要替换的新文本")}, ["path", "old", "new"]),
    tool_spec("bash", "在工作区内执行命令，返回 stdout、stderr、exit_code；支持超时和停止。需要人工批准。",
              {"command": S("Shell 命令"), "timeout": S("1..30 秒", "integer")}, ["command"]),
]


class ToolManager:
    def __init__(self, workspace, tracer, project_dir, approval=None):
        from .mcp_client import StdioMCPClient
        self.workspace = workspace
        self.tracer = tracer
        self.approval = approval or (lambda command: False)
        self.mcp = StdioMCPClient(project_dir, workspace.root)

    def specifications(self):
        tools = list(BUILTINS)
        try:
            for tool in self.mcp.tools():
                tools.append({"type": "function", "function": {
                    "name": "mcp_demo_" + tool["name"],
                    "description": "外部 MCP server: " + tool.get("description", ""),
                    "parameters": tool["inputSchema"]}})
        except Exception as e:
            self.tracer.emit("mcp_error", "MCP 服务未连接：" + str(e))
        return tools

    def call(self, name, args, cancel=None):
        try:
            if name == "read":
                result = self.workspace.read(**args)
            elif name == "write":
                result = self.workspace.write(**args)
            elif name == "edit":
                result = self.workspace.edit(**args)
            elif name == "bash":
                if not self.approval(args["command"]):
                    raise ToolError("用户拒绝执行 shell 命令")
                result = self.workspace.bash(
                    args["command"], args.get("timeout", 10), cancel=cancel)
            elif name.startswith("mcp_demo_"):
                result = self.mcp.call(name[len("mcp_demo_"):], args)
            else:
                raise ToolError("未知工具：" + name)
        except (ToolError, TypeError, KeyError, ValueError, OSError, Exception) as e:
            result = {"ok": False, "summary": str(e), "error_type": type(e).__name__}
        # Do not put potentially sensitive file contents or base64 in trace JSONL.
        safe = {k: v for k, v in result.items()
                if k in ("ok", "summary", "diff", "stderr", "stdout", "exit_code",
                         "timeout", "interrupted", "duration_seconds", "mcp_external", "content")}
        self.tracer.emit("tool", f"{name}: {result.get('summary', '')}",
                         name=name, args=self._safe_args(name, args), result=safe)
        return result

    @staticmethod
    def _safe_args(name, args):
        if name == "write":
            return {"path": args.get("path"), "content_length": len(str(args.get("content", "")))}
        if name == "edit":
            return {"path": args.get("path"), "old_length": len(str(args.get("old", ""))),
                    "new_length": len(str(args.get("new", "")))}
        return args

    def close(self):
        self.mcp.close()


class AgentRunner:
    def __init__(self, backend, manager, tracer, max_steps=12):
        self.backend = backend
        self.manager = manager
        self.tracer = tracer
        self.max_steps = max_steps
        self.cancel = threading.Event()

    def stop(self):
        self.cancel.set()
        self.tracer.emit("interrupt", "用户发出停止请求")

    def run(self, prompt):
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}]
        specifications = self.manager.specifications()
        self.tracer.emit("user", prompt)
        try:
            for step in range(1, self.max_steps + 1):
                if self.cancel.is_set():
                    return self._stop("用户中断：智能体已停止。")
                self.tracer.emit("step", f"第 {step}/{self.max_steps} 轮决策")
                reply_box, ready = {}, threading.Event()
                def ask_model():
                    try:
                        reply_box["reply"] = self.backend.complete(messages, specifications)
                    except Exception as exc:
                        reply_box["error"] = exc
                    finally:
                        ready.set()
                threading.Thread(target=ask_model, daemon=True).start()
                while not ready.wait(0.12):
                    if self.cancel.is_set():
                        return self._stop("用户中断：不再等待模型响应。")
                if self.cancel.is_set():
                    return self._stop("用户中断：模型返回后已停止。")
                if "error" in reply_box:
                    raise reply_box["error"]
                reply = reply_box["reply"]
                content = reply.get("content") or ""
                calls = reply.get("tool_calls") or []
                if not calls:
                    answer = content or "模型未提供最终回复。"
                    self.tracer.emit("final", answer)
                    return {"status": "done", "answer": answer, "steps": step}
                calls = calls[:8]
                assistant_calls = []
                for call in calls:
                    func = call.get("function", {})
                    assistant_calls.append({
                        "id": call.get("id") or "call_" + uuid.uuid4().hex[:10],
                        "type": "function",
                        "function": {"name": func.get("name", ""),
                                     "arguments": func.get("arguments", "{}")}})
                messages.append({"role": "assistant", "content": content,
                                 "tool_calls": assistant_calls})
                for call in assistant_calls:
                    if self.cancel.is_set():
                        return self._stop("工具调用前已被用户停止。")
                    name = call["function"]["name"]
                    try:
                        arguments = json.loads(call["function"]["arguments"])
                        if not isinstance(arguments, dict):
                            raise ValueError("arguments 不是 JSON object")
                        result = self.manager.call(name, arguments, cancel=self.cancel)
                    except (ValueError, json.JSONDecodeError) as e:
                        result = {"ok": False, "summary": "工具参数解析失败：" + str(e)}
                        self.tracer.emit("tool_error", result["summary"], name=name)
                    image_url = result.pop("image_data_url", None)
                    text = json.dumps(result, ensure_ascii=False, default=str)
                    messages.append({"role": "tool", "tool_call_id": call["id"],
                                     "content": text[:18000]})
                    if image_url:
                        messages.append({"role": "user", "content": [
                            {"type": "text", "text": "这是刚才 read 工具读取的图片："},
                            {"type": "image_url", "image_url": {"url": image_url}}]})
            return self._stop(f"已达到 {self.max_steps} 轮上限，任务未完成；请人工检查。")
        except Exception as e:
            message = f"智能体意外停止：{type(e).__name__}: {e}"
            self.tracer.emit("error", message)
            return {"status": "error", "answer": message}

    def _stop(self, reason):
        self.tracer.emit("stopped", reason)
        return {"status": "stopped", "answer": reason}


def demo_call(name, arguments):
    return {"id": "call_" + uuid.uuid4().hex[:8], "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}


class ScriptedDemoModel:
    """Offline deterministic mock *model*: real tools still execute."""
    def __init__(self, mode="recovery"):
        if mode == "recovery":
            self.plan = [
                ("read", {"path": "stats.py"}),
                ("bash", {"command": "python -m unittest test_stats -v", "timeout": 10}),
                ("edit", {"path": "stats.py", "old": "return total / missing_length",
                          "new": "return total / len(nums)"}),
                ("read", {"path": "stats.py"}),
                ("edit", {"path": "stats.py", "old": "return total",
                          "new": "return total / len(nums)"}),
                ("bash", {"command": "python -m unittest test_stats -v", "timeout": 10}),
                ("write", {"path": "notes/fix_log.md",
                           "content": "# 修复记录\n\nmean 函数此前返回总和，现返回平均值。\n测试：python -m unittest test_stats -v\n"}),
                ("mcp_demo_count_lines", {"path": "stats.py"}),
            ]
        elif mode == "boundary":
            self.plan = [
                ("read", {"path": "../../etc/passwd"}),
                ("read", {"path": "stats.py"}),
            ]
        elif mode == "interrupt":
            self.plan = [("read", {"path": "stats.py"})] * 30
        else:
            raise ValueError("unknown demo mode")
        self.mode = mode
        self.index = 0

    def complete(self, messages, tools):
        if self.index < len(self.plan):
            name, args = self.plan[self.index]
            self.index += 1
            return {"content": "", "tool_calls": [demo_call(name, args)]}
        if self.mode == "boundary":
            summary = "边界演示结束：越界读取已被拒绝，随后成功读取合法工作区文件。没有执行修改。"
        else:
            # Derive results from actual tool messages. Never claim a failing
            # test or a timed-out MCP call succeeded just because it was attempted.
            results = []
            for message in messages:
                if message.get("role") == "tool":
                    try:
                        results.append(json.loads(message.get("content", "{}")))
                    except (ValueError, TypeError):
                        pass
            passed = any(r.get("ok") and r.get("exit_code") == 0 for r in results)
            mcp_ok = any(r.get("ok") and r.get("mcp_external") for r in results)
            edit_ok = any(r.get("ok") and "精确修改" in r.get("summary", "") for r in results)
            write_ok = any(r.get("ok") and "原子写入" in r.get("summary", "") for r in results)
            summary = ("修复演示结束：编辑" + ("成功" if edit_ok else "失败") +
                       "；测试" + ("已通过" if passed else "未通过或未执行成功") +
                       "；写入" + ("成功" if write_ok else "失败") +
                       "；MCP 调用" + ("成功" if mcp_ok else "失败或超时") + "。")
        return {"content": summary, "tool_calls": []}
