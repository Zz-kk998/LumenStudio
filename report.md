# Python 智能体大作业报告

## 一、项目简介

**项目名称**：Lumen Studio — 桌面智能编程助手  
**项目类别**：原生桌面窗口 + 智能体 + 四个工具 + 外部 MCP  
**技术栈**：Python 标准库、Tkinter、JSON-RPC stdio、OpenAI-compatible Chat Completions、PyInstaller  
**作者 / 学号**：〔提交前由本人填写〕  
**个人公开仓库 / Release**：〔创建后填写真实链接〕

### 设计目标

从“终端里能跑”转变为“真实用户能用”：一个可双击打开的三栏编程助手，可以查看工作区文件、编辑代码、发起自然语言编程任务、观察每次工具调用，还能主动停止异常任务。核心设计原则是：**模型负责提出动作，工具负责真实执行和返回可核查证据；错误不能被吞掉。**

## 二、系统架构与职责

```text
┌─────────────────────────── Tkinter 桌面 UI ───────────────────────────┐
│ 文件树 (workspace)  │ 代码编辑器 (Text) │ 对话 + Tool Trace + 停止按钮 │
└─────────────────────┬────────────────────────────────────────────────┘
                      │ 用户任务
          ┌───────────▼───────────┐
          │ AgentRunner 有界循环  │←── ChatProvider / 离线 ScriptedDemoModel
          │ 决策 → 工具 → 观察    │
          └───────────┬───────────┘
                      │ JSON function calls
         ┌────────────▼────────────────────────┐
         │ ToolManager / Tracer                │
         │ read / write / edit / bash          │──→ Workspace 路径约束
         │ mcp_demo_count_lines                │──→ 外部 stdio MCP 进程
         └─────────────────────────────────────┘
```

真实模型用 Chat Completions 工具调用接口；离线演示使用可重复的预设决策序列，**但每个工具动作都是真实执行**。离线演示不是语言模型，不能代替实测模型的泛化能力。

## 三、四个工具的语义与防错

| 功能 | 关键保证 | 返回结果 |
|:--|:--|:--|
| `read` | 工作区 `resolve()` + `relative_to()`，限制路径和单次行数；图片可转 data URL | 编号文本/图片输入、总行数、是否有下一页 |
| `write` | 自动创建目录，在同目录临时写入、`fsync`、`os.replace` 原子替换 | 写入前后行数、unified diff |
| `edit` | 严格检查 `before.count(old) == 1`；0 / 多次都拒绝 | 修改前后 unified diff 或失败原因 |
| `bash` | 显式用户确认，1～30 秒超时，读 `stdout`、`stderr`、`exit_code`；超时/取消终止 | 正常/失败/超时/已中断及耗时 |

这里将路径限制应用于 Python 文件工具。**Shell 的权限不会被工作区路径逻辑约束**，因此设计中必须人工确认，并明确告知用户不是安全沙箱。

## 四、MCP 实接入

`agent/mcp_client.py` 启动 `server/demo_mcp_server.py` **独立子进程**，经过 `initialize`、`notifications/initialized`、`tools/list`、`tools/call` 交互。`count_lines` 是外部进程提供的能力，不把代码偷偷放进内置工具来冒充 MCP。`mcp.json` 写死了示例 server 启动命令，并避免读取仓库之外的文件。

## 五、两次受控失败与错误恢复

1. **测试失败**：示例 `mean([2,4,6])` 本应返回 4，初始代码却返回 12。首次 `bash` 返回非零退出码和测试错误输出，代理看到失败证据。
2. **编辑失败**：第一次 `edit` 的 `old` 文本故意不存在，工具报告“命中 0 次，未修改”；随后再次 `read`，使用正确精确匹配并在 diff 中确认修复。

恢复后，第二次运行单测通过，`write` 创建 `notes/fix_log.md`，`mcp_demo_count_lines` 成功返回真实外部 MCP 统计结果。细节查看 `docs/trace_recovery.jsonl`。

另提供两个安全场景：`docs/trace_boundary.jsonl` 有真实越界访问拒绝；`docs/trace_interrupt.jsonl` 达到步数上限，明确显示 `status=stopped`，未伪称任务成功。

## 六、桌面 UI 与运行方式

使用 Tkinter 原生顶层窗口和系统标题栏，不启动网页服务。窗口左侧树状展示文件，中间打开可编辑文本并用 Ctrl+S 保存，右侧提供会话、工具轨迹、任务输入与停止按钮。后台线程执行模型/工具、事件队列回到 Tk 主线程更新界面，避免耗时任务卡死。

使用 `python main.py` 仅是开发方式。面向验收的可双击发行版使用 `build.py` 构建 `DesktopAgent` 主程序和 `demo_mcp_server` 独立 MCP 程序。GitHub Actions 自动化构建三个操作系统的附件（需本人创建并发布 tag）。

## 七、测试结果（本地可核查）

运行命令：`python -m unittest discover -s tests -v`

覆盖项：工作区越界/符号链接、行号分页、原子写入、编辑唯一命中、shell 非零退出/超时/取消、人工拒绝、智能体限步中断、失败后恢复、MCP 子进程连接/拒绝越界。

离线演示命令：

```bash
python demo.py --mode recovery
python demo.py --mode boundary
python demo.py --mode interrupt
```

提交时请在本机再次执行以上命令，核对显示 `OK`，再由本人将最后一次本机日志或截图附在报告中。相应 JSONL 轨迹为脚本自动生成，无须手工编造。

## 八、过程与取舍

- 选择 Tkinter 而不是 WebView，满足“真正桌面窗口”且无额外运行时依赖。
- 只做四个内置工具，降低模型工具选择复杂度，shell 代替 N 个专用小工具。
- `edit` 失败绝不容忍“差不多匹配”，避免改错代码。
- 用明确退出码和失败轨迹证明“可观察、可恢复、可停止”。
- 另起子进程做 MCP server，避免纯装饰性协议调用。
- 用两份二进制分别打包 UI 与外部 MCP，解决冻结程序无法通过 `sys.executable` 运行 `.py` 的问题。

## 九、限制与后续改进

本项目不是全权限安全沙箱：如果用户批准危险 shell 命令仍可能影响工作区之外的文件。下一步可增加容器隔离、命令白名单、改动前审批、多文件事务、代码语法高亮、更丰富的 MCP server 连接器，以及真实 LLM 的端到端人工演示。

### 正式交付状态（发布前核实）

- [x] 桌面窗口源码、四工具、有界智能体循环、外部 MCP、自动测试、报告和打包流水线
- [x] 无真实 API Key 提交；提供 `.env.example`
- [ ] 本人的 **公开 GitHub** 仓库地址
- [ ] **至少 15 次**真实提交，跨越 **至少 7 天**
- [ ] GitHub **v1.0.0 Release** 内真实可双击的安装包（至少交付自己展示平台）
- [ ] 自己的 `demo.mp4` 录屏 / 五分钟现场演示
- [ ] 学号、姓名、仓库链接和 Release 链接已真实填入

> 请只勾选实际完成的项目。不能将预置的源码 ZIP 误称为已经发布的 GitHub Release。
