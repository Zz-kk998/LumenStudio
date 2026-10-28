"""Native Tkinter desktop agent: file tree | code editor | chat and tool traces.

Use python main.py during development. Distribute a real desktop executable with
build.py and the GitHub Actions workflow; users can then double-click the binary.
"""
from __future__ import annotations
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# On Windows, explicitly use Windows Credential Manager. Also makes the
# Windows backend discoverable when packaging with PyInstaller.
try:
    import keyring
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring
        CREDENTIAL_STORE = WinVaultKeyring()
    else:
        CREDENTIAL_STORE = keyring.get_keyring()
except Exception:
    CREDENTIAL_STORE = None

from agent.llm import ChatProvider, ProviderError, read_env
from agent.loop import AgentRunner, ScriptedDemoModel, ToolManager
from agent.trace import Tracer
from agent.workspace import Workspace, ToolError


BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DATA_DIR = Path.home() / ".desktop_agent"
DATA_DIR.mkdir(parents=True, exist_ok=True)
MODEL_CONFIG_PATH = DATA_DIR / "model_config.json"
KEYRING_SERVICE = "LumenStudio"
KEYRING_ACCOUNT = "model_api_key"


def load_model_preferences():
    """Read non-secret preferences; API keys are NEVER stored in this file."""
    try:
        data = json.loads(MODEL_CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def load_saved_api_key():
    """Load a secret only from the OS credential store."""
    if CREDENTIAL_STORE is None:
        return ""
    try:
        return CREDENTIAL_STORE.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT) or ""
    except Exception:
        return ""


def save_model_preferences(base_url, model, api_key):
    """Persist key securely; write only the URL/model to a local JSON file."""
    if CREDENTIAL_STORE is None:
        raise RuntimeError("无法使用系统凭据存储；请确认已安装 keyring 并重新打包。")

    # Store the secret first. If this fails, don't claim that saving succeeded.
    if api_key:
        CREDENTIAL_STORE.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, api_key)
    else:
        # An empty key intentionally clears the previously saved credential.
        current = CREDENTIAL_STORE.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        if current is not None:
            CREDENTIAL_STORE.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)

    config = {"base_url": base_url, "model": model}
    temporary = MODEL_CONFIG_PATH.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        temporary.replace(MODEL_CONFIG_PATH)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


PALETTE = {
    "bg": "#0e1726", "panel": "#172337", "sidebar": "#111e30",
    "text": "#e6edf8", "muted": "#95a6bd", "line": "#2a3b53",
    "accent": "#51b6a4", "accent2": "#4489ec", "warning": "#f4b96a",
    "danger": "#e87985", "field": "#0b1421"
}


class DesktopAgentUI:
    def __init__(self, root):
        self.root = root
        root.title("Lumen Studio  ·  智能编程桌面助手")
        root.geometry("1390x815")
        root.minsize(1060, 630)
        root.configure(bg=PALETTE["bg"])
        self.bus = queue.Queue()
        self.runner = None
        self.manager = None
        self.running = False
        self.active_path = None
        self.treepaths = {}
        self.env = read_env(BASE / ".env")
        saved = load_model_preferences()
        self.base_url = tk.StringVar(value=(
            saved.get("base_url") or os.environ.get("CHAT_BASE_URL")
            or self.env.get("CHAT_BASE_URL") or "https://api.openai.com/v1"))
        self.model = tk.StringVar(value=(
            saved.get("model") or os.environ.get("CHAT_MODEL")
            or self.env.get("CHAT_MODEL") or "gpt-4o-mini"))
        self.api_key = tk.StringVar(value=(
            load_saved_api_key() or os.environ.get("CHAT_API_KEY")
            or self.env.get("CHAT_API_KEY") or ""))
        self.workspace = Workspace(BASE / "examples" / "workspace")
        self.status = tk.StringVar(value="就绪 · 离线演示无需 API Key")
        self._style()
        self._build_ui()
        self._refresh_tree()
        self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _style(self):
        theme = ttk.Style(self.root)
        theme.theme_use("clam")
        theme.configure(".", font=("Microsoft YaHei UI", 10),
                        foreground=PALETTE["text"], background=PALETTE["bg"])
        theme.configure("Treeview", background=PALETTE["sidebar"],
                        fieldbackground=PALETTE["sidebar"],
                        foreground=PALETTE["text"], rowheight=29,
                        bordercolor=PALETTE["sidebar"])
        theme.map("Treeview", background=[("selected", "#234b6f")],
                  foreground=[("selected", "#ffffff")])
        theme.configure("Treeview.Heading", background=PALETTE["panel"],
                        foreground=PALETTE["text"])
        theme.configure("TNotebook", background=PALETTE["bg"], borderwidth=0)
        theme.configure("TNotebook.Tab", padding=(16, 8),
                        background=PALETTE["panel"], foreground=PALETTE["muted"])
        theme.map("TNotebook.Tab",
                  background=[("selected", PALETTE["sidebar"])],
                  foreground=[("selected", PALETTE["text"])])
        theme.configure("TPanedwindow", background=PALETTE["line"])
        theme.configure("TFrame", background=PALETTE["bg"])
        theme.configure("TLabel", background=PALETTE["bg"],
                        foreground=PALETTE["text"])
        theme.configure("TScrollbar", background=PALETTE["panel"])
        theme.configure("Accent.TButton", background=PALETTE["accent"],
                        foreground="#052529", padding=(12, 8), borderwidth=0)
        theme.map("Accent.TButton", background=[("active", "#79d0bd")])
        theme.configure("Alt.TButton", background=PALETTE["panel"],
                        foreground=PALETTE["text"], padding=(12, 8), borderwidth=0)
        theme.map("Alt.TButton", background=[("active", "#294765")])
        theme.configure("Stop.TButton", background="#7a3348",
                        foreground="#fff", padding=(12, 8), borderwidth=0)

    def _label(self, parent, text, size=10, fg=None, bold=False, **kw):
        return tk.Label(parent, text=text, bg=PALETTE["bg"],
                        fg=fg or PALETTE["text"],
                        font=("Microsoft YaHei UI", size, "bold" if bold else "normal"),
                        **kw)

    def _build_ui(self):
        header = tk.Frame(self.root, bg=PALETTE["bg"])
        header.pack(fill="x", padx=22, pady=(15, 10))
        tk.Label(header, text="◈  LUMEN STUDIO", bg=PALETTE["bg"],
                 fg=PALETTE["accent"], font=("Arial", 18, "bold")).pack(side="left")
        tk.Label(header, text="   WORKSPACE  /  AGENT  /  MCP",
                 bg=PALETTE["bg"], fg=PALETTE["muted"],
                 font=("Consolas", 10)).pack(side="left", padx=14)
        ttk.Button(header, text="⚙ 模型设置", style="Alt.TButton",
                   command=self._settings).pack(side="right", padx=5)
        ttk.Button(header, text="▶ 离线演示", style="Accent.TButton",
                   command=self._demo).pack(side="right", padx=5)
        ttk.Button(header, text="📁 打开工作区", style="Alt.TButton",
                   command=self._pick_workspace).pack(side="right", padx=5)

        pathbar = tk.Frame(self.root, bg=PALETTE["panel"], height=38)
        pathbar.pack(fill="x", padx=20)
        tk.Label(pathbar, text="  工作区  ", bg=PALETTE["panel"],
                 fg=PALETTE["accent"], font=("Arial", 10, "bold")).pack(side="left")
        self.path_label = tk.Label(pathbar, text=str(self.workspace.root),
                                   bg=PALETTE["panel"], fg=PALETTE["muted"],
                                   anchor="w", font=("Consolas", 10))
        self.path_label.pack(side="left", fill="x", expand=True, padx=8)

        paned = ttk.Panedwindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=20, pady=(10, 12))
        left = tk.Frame(paned, bg=PALETTE["sidebar"])
        center = tk.Frame(paned, bg=PALETTE["panel"])
        right = tk.Frame(paned, bg=PALETTE["panel"])
        paned.add(left, weight=1)
        paned.add(center, weight=3)
        paned.add(right, weight=3)

        self._panel_title(left, "01  文件资源管理器", "双击查看文件")
        self.filetree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.filetree.pack(fill="both", expand=True, padx=6, pady=9)
        self.filetree.bind("<<TreeviewSelect>>", self._select_file)
        tk.Button(left, text="↻ 刷新文件树", command=self._refresh_tree,
                  bg=PALETTE["sidebar"], fg=PALETTE["muted"],
                  activebackground=PALETTE["panel"], relief="flat",
                  bd=0, cursor="hand2").pack(anchor="w", padx=13, pady=7)

        editorhead = tk.Frame(center, bg=PALETTE["panel"])
        editorhead.pack(fill="x", padx=12, pady=(11, 8))
        self.editor_title = tk.Label(editorhead, text="02  代码编辑器  /  未选择文件",
                                     fg=PALETTE["text"], bg=PALETTE["panel"],
                                     font=("Consolas", 11, "bold"), anchor="w")
        self.editor_title.pack(side="left", fill="x", expand=True)
        ttk.Button(editorhead, text="保存  Ctrl+S", style="Alt.TButton",
                   command=self._save_file).pack(side="right")
        self.editor = tk.Text(center, bg=PALETTE["field"], fg=PALETTE["text"],
                              insertbackground=PALETTE["accent"], undo=True,
                              selectbackground="#305c79", wrap="none",
                              relief="flat", borderwidth=0, padx=18, pady=16,
                              font=("Consolas", 11), tabs=("2c",))
        self.editor.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.editor.bind("<Control-s>", self._on_save)
        self.editor.config(state="disabled")

        righttop = tk.Frame(right, bg=PALETTE["panel"])
        righttop.pack(fill="x", padx=12, pady=(10, 5))
        tk.Label(righttop, text="03  智能体协作", bg=PALETTE["panel"],
                 fg=PALETTE["text"], font=("Consolas", 11, "bold")).pack(side="left")
        self.stopbtn = ttk.Button(righttop, text="■ 停止", style="Stop.TButton",
                                  command=self._stop, state="disabled")
        self.stopbtn.pack(side="right")
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 5))
        chatframe = tk.Frame(self.tabs, bg=PALETTE["sidebar"])
        logsframe = tk.Frame(self.tabs, bg=PALETTE["sidebar"])
        self.tabs.add(chatframe, text="  会话  ")
        self.tabs.add(logsframe, text="  工具调用 / Trace  ")
        self.chat = scrolledtext.ScrolledText(
            chatframe, bg=PALETTE["sidebar"], fg=PALETTE["text"],
            insertbackground=PALETTE["text"], state="disabled", wrap="word",
            relief="flat", borderwidth=0, padx=14, pady=14,
            font=("Microsoft YaHei UI", 10))
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_config("user", foreground=PALETTE["accent"])
        self.chat.tag_config("success", foreground=PALETTE["accent"])
        self.chat.tag_config("error", foreground=PALETTE["danger"])
        self.chat.tag_config("muted", foreground=PALETTE["muted"])
        self.log = scrolledtext.ScrolledText(
            logsframe, bg=PALETTE["field"], fg=PALETTE["muted"],
            insertbackground=PALETTE["text"], state="disabled", wrap="word",
            relief="flat", padx=12, pady=12, font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)
        self._write(self.chat, "◈ 欢迎使用 Lumen Studio\n\n"
                    "左侧是工作区，中间可以直接编辑和保存代码，右侧展示 AI 会话与真实工具调用。\n\n"
                    "• 点击「离线演示」可复现测试失败 → 编辑恢复 → MCP 调用。\n"
                    "• 配置 API Key 后可发送任意编程任务。\n"
                    "• bash 执行前会征求你的许可。\n\n", "muted")
        bottom = tk.Frame(right, bg=PALETTE["panel"])
        bottom.pack(fill="x", padx=10, pady=(2, 10))
        self.prompt = tk.Text(bottom, height=4, bg=PALETTE["field"],
                              fg=PALETTE["text"], insertbackground=PALETTE["accent"],
                              relief="flat", padx=10, pady=8,
                              font=("Microsoft YaHei UI", 10), wrap="word")
        self.prompt.pack(fill="x", pady=(0, 7))
        self.prompt.insert("1.0", "修复 stats.py 中 mean 函数的错误，并运行测试。")
        ttk.Button(bottom, text="➤ 发送任务", style="Accent.TButton",
                   command=self._send).pack(side="right")

        foot = tk.Frame(self.root, bg=PALETTE["bg"])
        foot.pack(fill="x", padx=22, pady=(0, 10))
        tk.Label(foot, textvariable=self.status, bg=PALETTE["bg"],
                 fg=PALETTE["muted"], anchor="w",
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Label(foot, text="4 内置工具  ·  MCP stdio  ·  可中断  ·  JSONL Trace",
                 bg=PALETTE["bg"], fg=PALETTE["muted"],
                 font=("Consolas", 9)).pack(side="right")

    def _panel_title(self, parent, title, subtitle):
        tk.Label(parent, text=title, bg=PALETTE["sidebar"],
                 fg=PALETTE["text"], font=("Consolas", 11, "bold"),
                 anchor="w").pack(fill="x", padx=12, pady=(15, 4))
        tk.Label(parent, text=subtitle, bg=PALETTE["sidebar"],
                 fg=PALETTE["muted"], font=("Microsoft YaHei UI", 9),
                 anchor="w").pack(fill="x", padx=12)

    @staticmethod
    def _write(widget, content, tag=None):
        widget.config(state="normal")
        widget.insert("end", content, tag or ())
        widget.see("end")
        widget.config(state="disabled")

    def _refresh_tree(self):
        if not hasattr(self, "filetree"):
            return
        self.filetree.delete(*self.filetree.get_children())
        self.treepaths = {}
        root = self.workspace.root
        def add(parent, folder, depth=0):
            if depth > 6:
                return
            try:
                items = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except PermissionError:
                return
            for p in items[:160]:
                if p.name in {".git", "__pycache__", ".venv", "node_modules", "dist",
                              ".DS_Store"} or p.is_symlink():
                    continue
                iid = self.filetree.insert(parent, "end",
                        text=("📁 " if p.is_dir() else "  ") + p.name,
                        open=depth < 1)
                self.treepaths[iid] = p
                if p.is_dir():
                    add(iid, p, depth + 1)
        add("", root)

    def _select_file(self, event=None):
        selection = self.filetree.selection()
        if not selection:
            return
        p = self.treepaths.get(selection[0])
        if p is not None and p.is_file():
            self._load_file(p)

    def _load_file(self, p):
        try:
            if p.stat().st_size > 600_000:
                raise ToolError("文件过大，编辑器只打开 600KB 以下文本")
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ToolError) as e:
            self.status.set("无法在编辑器中打开：" + str(e))
            return
        self.active_path = p
        self.editor.config(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", content)
        self.editor.edit_modified(False)
        self.editor_title.config(text="02  代码编辑器  /  " +
                                 str(p.relative_to(self.workspace.root)))

    def _on_save(self, event):
        self._save_file()
        return "break"

    def _save_file(self):
        if not self.active_path:
            return
        try:
            rel = str(self.active_path.relative_to(self.workspace.root))
            self.workspace.write(rel, self.editor.get("1.0", "end-1c"))
            self.editor.edit_modified(False)
            self.status.set("已保存 " + rel)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _pick_workspace(self):
        if self.running:
            messagebox.showinfo("请稍候", "任务运行时不能切换工作区。")
            return
        value = filedialog.askdirectory(title="选择代码工作区")
        if value:
            self._set_workspace(value)

    def _set_workspace(self, value):
        self.workspace = Workspace(value)
        self.path_label.config(text=str(self.workspace.root))
        self.active_path = None
        self.editor.config(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.config(state="disabled")
        self.editor_title.config(text="02  代码编辑器  /  未选择文件")
        self._refresh_tree()

    def _settings(self):
        window = tk.Toplevel(self.root)
        window.title("模型连接设置")
        window.geometry("530x335")
        window.configure(bg=PALETTE["bg"])
        window.transient(self.root)
        window.grab_set()

        # Draft values: closing with Esc or X does not change active settings.
        url_var = tk.StringVar(value=self.base_url.get())
        model_var = tk.StringVar(value=self.model.get())
        key_var = tk.StringVar(value=self.api_key.get())
        options = [
            ("Chat Completions 地址", url_var, False),
            ("模型名称", model_var, False),
            ("API Key（保存到 Windows 凭据管理器）", key_var, True),
        ]
        for label, var, secret in options:
            tk.Label(window, text=label, bg=PALETTE["bg"], fg=PALETTE["text"],
                     anchor="w").pack(fill="x", padx=24, pady=(14, 3))
            entry = tk.Entry(window, textvariable=var, show="●" if secret else "",
                             bg=PALETTE["field"], fg=PALETTE["text"],
                             insertbackground=PALETTE["text"], relief="flat")
            entry.pack(fill="x", padx=24, ipady=7)

        def save_and_close():
            url = url_var.get().strip().rstrip("/")
            model = model_var.get().strip()
            api_key = key_var.get().strip()
            if not url or not model:
                messagebox.showwarning("配置不完整", "请填写模型地址和模型名称。",
                                       parent=window)
                return
            # Don't accidentally send a credential to an unencrypted endpoint.
            if not (url.startswith("https://") or
                    url.startswith("http://localhost:") or
                    url.startswith("http://127.0.0.1:")):
                messagebox.showwarning("地址不安全", "请使用 HTTPS API 地址（本地 localhost 可使用 HTTP）。",
                                       parent=window)
                return
            try:
                save_model_preferences(url, model, api_key)
            except Exception as e:
                messagebox.showerror("保存失败", "模型配置未能保存到系统凭据存储或配置文件：\n"
                                     + str(e), parent=window)
                return
            self.base_url.set(url)
            self.model.set(model)
            self.api_key.set(api_key)
            self.status.set("模型配置已安全保存，下次启动自动加载")
            window.destroy()

        ttk.Button(window, text="保存并关闭", style="Accent.TButton",
                   command=save_and_close).pack(pady=16)
        window.bind("<Escape>", lambda e: window.destroy())

    def _start(self, backend, prompt):
        if self.running:
            return
        self.running = True
        self.stopbtn.config(state="normal")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        trace_path = DATA_DIR / "runs" / ("trace_" + stamp + ".jsonl")
        tracer = Tracer(trace_path, callback=lambda e: self.bus.put(("trace", e)))
        approval = self._request_approval
        self.manager = ToolManager(self.workspace, tracer, BASE, approval=approval)
        self.runner = AgentRunner(backend, self.manager, tracer, max_steps=15)
        self.status.set("运行中 · Trace：" + str(trace_path))
        self._write(self.chat, "\n你： " + prompt + "\n", "user")
        def job():
            try:
                result = self.runner.run(prompt)
                self.bus.put(("done", result))
            finally:
                self.manager.close()
        threading.Thread(target=job, daemon=True).start()

    def _send(self):
        if self.running:
            return
        prompt = self.prompt.get("1.0", "end-1c").strip()
        if not prompt:
            messagebox.showwarning("任务为空", "请输入要完成的编程任务。")
            return
        try:
            backend = ChatProvider(self.base_url.get(), self.api_key.get(),
                                   self.model.get())
        except ProviderError as e:
            messagebox.showinfo("请设置模型", str(e))
            return
        self._start(backend, prompt)

    def _demo(self):
        if self.running:
            return
        root = Path(tempfile.mkdtemp(prefix="lumen_demo_"))
        shutil.copytree(BASE / "examples" / "workspace", root, dirs_exist_ok=True)
        self._set_workspace(root)
        self._write(self.chat, "\n◈ 创建独立演示工作区：" + str(root) + "\n", "muted")
        self._start(ScriptedDemoModel("recovery"),
                    "读取并修复 mean 的错误，展示失败恢复、测试、write 和 MCP 调用。")

    def _request_approval(self, command):
        permit = threading.Event()
        answer = {"ok": False}
        self.bus.put(("approval", (command, permit, answer)))
        # Stop does not rely on Tk's modal approval dialog returning.
        while not permit.wait(0.1):
            if self.runner is not None and self.runner.cancel.is_set():
                return False
        return answer["ok"]

    def _stop(self):
        if self.runner:
            self.runner.stop()
            self.status.set("已请求停止，正在终止当前执行的工具…")

    def _poll(self):
        try:
            for _ in range(100):
                kind, value = self.bus.get_nowait()
                if kind == "trace":
                    row = value
                    self._write(self.log,
                        f"[{row['time']}] {row['type']} · {row['message']}\n")
                    if row["type"] == "tool":
                        good = row.get("result", {}).get("ok", False)
                        self._write(self.chat,
                            ("✓ " if good else "✗ ") + row["message"] + "\n",
                            "success" if good else "error")
                        info = row.get("result", {})
                        if "diff" in info and info["diff"]:
                            self._write(self.log, info["diff"] + "\n")
                        if "stderr" in info and info["stderr"]:
                            self._write(self.log, "stderr:\n" + info["stderr"] + "\n")
                        self._refresh_tree()
                        if self.active_path and self.active_path.exists():
                            if not self.editor.edit_modified():
                                self._load_file(self.active_path)
                    elif row["type"] in ("error", "stopped", "mcp_error"):
                        self._write(self.chat, row["message"] + "\n", "error")
                elif kind == "approval":
                    command, permit, answer = value
                    answer["ok"] = messagebox.askyesno(
                        "确认执行 Shell 命令",
                        "模型想执行这条命令：\n\n" + command +
                        "\n\n⚠  Shell 拥有当前用户权限，不是安全沙箱。"
                        "\n只允许你信任的命令。")
                    permit.set()
                elif kind == "done":
                    self.running = False
                    self.stopbtn.config(state="disabled")
                    tag = "success" if value["status"] == "done" else "error"
                    self._write(self.chat, "\n助手： " + value["answer"] + "\n\n", tag)
                    self.status.set("已完成 · " + value["status"] + " · 可查看 Trace")
                    self._refresh_tree()
        except queue.Empty:
            pass
        self.root.after(90, self._poll)

    def _close(self):
        if self.runner:
            self.runner.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    DesktopAgentUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
