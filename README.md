# ◈ Lumen Studio — 可运行的桌面智能编程助手

**Python 智能体大作业 · 四个内置工具 · 三栏原生桌面窗口 · 外部 MCP · 可停止 · 可打包**

这是一个**真正的 Tkinter 原生桌面程序**，不是 localhost 网页。左侧是文件资源管理器，中间是可编辑代码区，右侧是 AI 对话和真实工具调用日志。代码采用 Python 标准库，开发时不需要安装界面框架。

> 项目附带可复现的「离线演示模型」，**无需 API Key** 就能实际读文件、失败测试、编辑失败、恢复修复、再次测试、写报告和调用独立 MCP server。连接自己的模型 API 后，可作为通用的代码智能体使用。离线模型仅按预设剧本发出调用，不具备自由规划能力。

## 1. 三步启动

### 开发运行（跨 Windows / macOS / Linux）

1. 安装 **Python 3.10+**（Linux 需要 `python3-tk`）。
2. 解压源码，在项目目录运行 `python main.py`（Windows 也可以双击 `main.pyw`）。
3. 在窗口中点 **「▶ 离线演示」**。每次会创建独立临时工作区，不会改坏提交的样例文件。看到两次 `bash` 确认时，只批准 `python -m unittest test_stats -v` 这条已知测试命令。

### 最终用户双击启动（无需预装 Python）

从 GitHub **Releases** 下载自己操作系统的 ZIP，**完整解压**后：
- Windows：双击 `DesktopAgent.exe`。
- Linux：给 `DesktopAgent` 执行权限后双击，或 `./DesktopAgent`。
- macOS：打开 `DesktopAgent.app`（首次可能需要系统安全设置允许该未签名程序）。

请保留 Release 包中第二个可执行文件 `demo_mcp_server` / `demo_mcp_server.exe`，**它是独立运行的外部 MCP 服务器**。打包产物使用 `build.py`/`.github/workflows/release.yml` 生成，源码 ZIP 本身不是打包好的可执行文件。

## 2. 用真实模型

点击 **「⚙ 模型设置」**，填入：
- Chat Completions 兼容地址，如 `https://api.openai.com/v1`
- 支持函数工具调用的模型名称
- 用户自己合法持有的 API Key

也可以把 `.env.example` **复制为 `.env`** 填入对应字段，或设置环境变量 `CHAT_BASE_URL`、`CHAT_MODEL`、`CHAT_API_KEY`。`.env` 已加入 `.gitignore`；API Key 不会写进 `trace`。不同服务的兼容程度和图像输入能力可能不同，请根据所用服务调整。

任务示例：`检查当前工作区的 stats.py，修复 mean() 的错误，运行单元测试并报告结果。`

> 安全提示：`bash` 具有当前系统用户权限，**不是操作系统级安全沙箱**。每次执行模型发起的 shell 命令都会弹窗，用户可拒绝。请不要在含机密材料的目录中让不可信模型运行任意命令；仅处理可信工作区。

## 3. 四个内置工具

| 工具 | 输入 | 可观察语义 |
| --- | --- | --- |
| `read` | `path`, `offset?`, `limit?` | UTF-8 文本按行编号分页；1.5MB 以下图片产生多模态 data URL；越界路径拒绝 |
| `write` | `path`, `content` | 自动建目录；临时文件 + `os.replace` 原子写入；输出行数与 unified diff |
| `edit` | `path`, `old`, `new` | 只做精确替换，**必须唯一命中**；0 次/多次命中均报错，文件保持不变；返回 diff |
| `bash` | `command`, `timeout?` | 用户确认后执行；返回 `stdout`、`stderr`、`exit_code`、超时、中断、耗时；支持结束进程组 |

这些工具都在 `agent/workspace.py`；`ToolManager` 统一捕获错误并将结果喂回模型。另有 `mcp_demo_count_lines` 来自**外部进程**，不算作第五个内置文件工具。

## 4. MCP（不是模拟文字）

配置在 `mcp.json`：
```json
{
  "mcpServers": {
    "demo": {
      "command": ["{python}", "{project}/server/demo_mcp_server.py"]
    }
  }
}
```

实际交互顺序：
`spawn external process → initialize → notifications/initialized → tools/list → tools/call`。

服务端 `server/demo_mcp_server.py` 完全独立运行，使用标准 MCP stdio 的逐行 JSON-RPC 交互，暴露 `count_lines` 工具。打包版本会改为启动与主程序一同分发的第二个二进制文件。

## 5. 可见的智能体循环

`agent/loop.py` 实现：

`用户请求 → 调用模型 → 模型返回 tool_calls → 本地/外部工具执行 → 结果反馈模型 → 下一步决策 → 最终回复或停止`。

每轮和每个工具调用写入 `~/.desktop_agent/runs/trace_*.jsonl`，可以在右侧「工具调用 / Trace」实时查看。支持：
- 最大 15 轮，防止无限执行；
- 「■ 停止」按钮与工具调用/模型等待期间的停止检查；
- `edit` 失败后可 read 文件再修复；
- shell 运行超时/非零退出码原样反馈，而非伪装成功；
- 工作区读写路径越界防护，符号链接经解析检查；
- 连接并调用一个真实的外部 MCP 工具。

真实模型发出错误参数时会得到可读错误结果，而不是崩溃。

## 6. 可复现测试与演示

在项目根目录执行：

```bash
python -m unittest discover -s tests -v
python demo.py --mode recovery
python demo.py --mode boundary
python demo.py --mode interrupt
```

三种离线场景：
1. `recovery`：测试失败 → edit 0 次命中 → read 确认 → edit 成功 → 测试通过 → write 文档 → 外部 MCP 调用。
2. `boundary`：尝试越界读取，工具拒绝 → 读取工作区合法文件，任务恢复。
3. `interrupt`：把最大步数设为 1，工具调用后立即中断，`status=stopped`，没有虚假的“已完成”。

命令行演示用于重复测试，**最终课程展示仍应双击桌面可执行文件**，并在真实窗口中操作。`docs/trace_*.jsonl` 是可检查的运行记录。

## 7. 构建桌面安装包 / 发布 Release

在目标操作系统上：
```bash
python -m pip install -r requirements-build.txt
python build.py
python package_release.py
```

Windows 可双击 `build_windows.bat`。构建生成两个原生程序：
- `dist/DesktopAgent[.exe]`（macOS 为 `.app`）
- `dist/demo_mcp_server[.exe]`

**跨平台编译限制**：通常必须在 Windows 上构建 Windows `.exe`，在 macOS 上构建 `.app`，在 Linux 上构建 Linux 可执行文件。GitHub Actions 配置 `.github/workflows/release.yml` 可在推送 `v1.0.0` tag 时分别构建三个平台的 Release 压缩包。

示例发布命令（需在**你自己的 GitHub 账户**操作）：
```bash
git init
git add .
git commit -m "feat: add native desktop UI and agent backend"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/desktop-agent.git
git push -u origin main
git tag v1.0.0
git push origin v1.0.0
```
之后核对 Actions 构建通过、GitHub Releases 有三个操作系统的附件，并用**全新机器或环境**测试下载、解压、双击启动。

## 8. 提交清单（按老师提供的课件）

**必要**：公开 GitHub 仓库 / 至少 15 次真实 commit、跨越至少 7 天 / `.env` 不能入库 / README 三步启动 / 至少一个 `v1.0.0` Tag 和 Release 安装包 / `report.md` / `demo.mp4` / 群里填写学号、姓名、仓库链接、Release 链接。

**不能替你完成**：不掌握 GitHub 账户凭据，无法创建公开仓库、积累跨 7 天的真实提交、正式上传 Release 或拍摄本人现场讲解。不要用一次提交或改 commit 时间来伪造历史。用 `docs/demo_guide.md` 的流程录屏，并根据实际结果填写 `report.md` 最后一节。

## 9. 文件说明

```text
desktop-agent/
├── main.py                     # Tkinter 三栏桌面 UI
├── main.pyw                    # Windows 有 Python 时双击入口
├── demo.py                     # 离线可复现脚本
├── agent/
│   ├── workspace.py            # read / write / edit / bash
│   ├── loop.py                 # 模型-工具-观察的有界循环
│   ├── llm.py                  # Chat Completions 适配器
│   ├── mcp_client.py           # 真正的 stdio JSON-RPC MCP 客户端
│   └── trace.py                # JSONL 可追踪证据
├── server/demo_mcp_server.py   # 独立外部 MCP 服务端
├── examples/workspace/        # 演示故障代码及测试
├── tests/                     # 14 个单元/集成测试
├── docs/                      # 三个重现轨迹与演示引导
├── mcp.json                   # MCP 配置
├── .env.example               # API 设置模板，没有真实密钥
├── report.md                  # 大作业报告
├── build.py                   # 双二进制 PyInstaller 打包
└── .github/workflows/release.yml
```

**限制说明**：这是一份课程作业范围内的桌面开发代理原型。Shell 并非完全隔离，真实模型需要可用的服务和密钥，MCP 目前只提供一个自带外部服务，无法保证所有模型/OS 的兼容性；不要对互联网未知代码开启无监督执行。

## Windows 出现 9009 或 MCP 超时的诊断

在 VS Code 项目根目录执行 `py diagnose.py`。`bash` 会优先将当前 Python 解释器目录加入子进程 PATH，以免 VS Code 解释器可用但 Windows 系统 PATH 找不到 `python`。MCP 采用 `-u` 无缓冲启动，若失败会反馈外部 server 的 stderr 摘要。离线演示结论根据实际退出码生成，失败不再冒充成功。
