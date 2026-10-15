# Plot Forge · 科研图表工坊

上传绘图代码、已整理的绘图 CSV 和已有图片，在项目图廊中选择目标，使用规范化 Skill 或 Chat 修改。新图先作为候选显示在 Chat，明确应用某版后才更新正式代码和中央图廊。

此整合版以 2026-10-14 的仓库版本为基础，保留原有的上传、拆图、单图代码建议和应用接口；新图廊与候选版 Chat 在首页使用。原单图页面仍可通过 [旧版工作台](http://127.0.0.1:8765/legacy) 打开，原版说明保存在 [docs/original-workflow.zh-CN.md](docs/original-workflow.zh-CN.md)。两版能力的取舍记录见 [docs/version-integration.zh-CN.md](docs/version-integration.zh-CN.md)。

## 启动

当前候选渲染使用 **macOS Seatbelt（`sandbox-exec`）**，需要 macOS 和能够启动该沙箱的本机终端。Python 3.10+、Matplotlib、NumPy、`keyring`（系统钥匙串接口）为基础依赖；绘图代码使用 Pandas、SciPy 等库时，也需要在同一 Python 环境中安装它们。当前环境可使用 `/opt/anaconda3/bin/python`。

默认只需启动工作台。两个 Agent 在进程内调用，仍分别加载自己的 Skill：

```bash
cd /path/to/GraphicEditing
/opt/anaconda3/bin/python server.py
```

浏览器打开 [本地工作台](http://127.0.0.1:8765/)，点击右上角 **“⚙ API 配置”**，填写 Chat Completions 兼容的 API 地址、模型名称和 API Key，然后点击“保存配置”。可再点击“测试已保存配置”；测试只发送一条简短消息，不发送项目代码或 CSV。保存后两个 Agent 立即使用新配置，无需重启。服务只绑定本机回环地址。

API Key 保存在这台 Mac 的系统钥匙串中；项目目录下的 `.model-api.json` 只保存地址、模型名称和视觉开关，并被 Git 忽略。页面只能查看“已配置”状态，不能读回完整密钥。API 地址需使用 HTTPS；本机模型服务允许 `http://127.0.0.1` 或 `http://localhost`。如需保留原有终端方式，仍可使用 `OPENAI_API_KEY`、`LLM_API_URL` 和 `LLM_MODEL` 环境变量。

### 机构内网模型

内网 HTTP API 地址不写入仓库。使用机构提供的地址时，在启动工作台的本机终端设置 `PLOT_FORGE_INTRANET_API_URL` 为完整的 Chat Completions 地址，必要时设置 `PLOT_FORGE_INTRANET_MODEL`，再启动服务。页面的 **“使用本机内网模型预设”** 按钮会填入这两个本机环境变量。请在页面输入 API Key、保存后点击连接测试；不要把密钥或内网地址提交到 Git。

内网 HTTP 连接会传输 API Key，请遵循本机构的网络与模型使用要求。页面的视觉选项可将当前图和只读参照图发给支持视觉的模型；关闭后只发送文本上下文。连接测试只发送短句，不发送项目文件。

Chat 提供目标图代码与相关绘图 CSV 的必要行；无关 CSV 只提供列名，过长的数据会截断并标明范围。Harness 仍完整保存只读数据快照以供版本与渲染检查。可在页面勾选视觉选项，向支持图片输入的模型同时提供可用的固定版本目标图、父候选图和参照图；没有图片时会标明视觉上下文缺失。未通过页面保存视觉选项时，仍可使用原有的 `CHAT_MODEL_VISION=1` 环境变量。密钥只在模型调用请求中使用，不写进候选代码或项目，也不传入候选 Python 的运行环境。

### 可选：分成三个端口

可将两个 Agent 部署为独立本机服务。Agent 启动后，仍通过工作台页面填写同一份模型配置：

```bash
/opt/anaconda3/bin/python normalizer_agent.py
```

```bash
/opt/anaconda3/bin/python chat_agent.py
```

再在运行工作台的终端设置：

```bash
export NORMALIZER_AGENT_URL='http://127.0.0.1:8766'
export CHAT_AGENT_URL='http://127.0.0.1:8767'
/opt/anaconda3/bin/python server.py
```

| 端口 | 角色 | 接口 |
| --- | --- | --- |
| 8765 | 页面、项目服务与 Harness | `/api/projects/.../chat/sessions/...` |
| 8766 | 规范化 Agent | `POST /v1/normalize` |
| 8767 | Chat 改图 Agent | `POST /v1/chat-edit` |

未设置相应 URL 时使用进程内 Agent。独立 Agent 只返回结构化方案，Harness 保存候选、检查和渲染；Agent 之间不直接覆盖项目文件。端口分别可通过 `NORMALIZER_AGENT_PORT`、`CHAT_AGENT_PORT` 调整。

只启动 8766/8767 并不会让工作台自动改用它们；启动 8765 时必须设置上面的两个 URL。模型连接测试只发送极短消息，不能代表完整绘图请求的延迟或输出质量。规范化会优先要求模型返回精确代码替换，并只在同一正式版本、同一 Skill 与配置下复用已通过检查的候选。

工作台在请求时将当前配置交给所选 Agent，密钥不会写入候选代码或发给候选 Python 进程。页面更换 API Key、模型或地址后，下一轮调用自动使用新配置。

分进程且使用图片输入时，在页面勾选视觉选项即可：工作台准备固定版本图片，Chat Agent 将它们传给支持视觉输入的模型。

## 改图流程

1. 在图廊选择一张或多张图，Chat 顶部显示固定目标；需要参照其他图时另外选择只读参照。
2. 输入修改要求，或点击批量标准化并选择 Skill。
3. Agent 返回原话、结构化修改意图和候选代码；Harness 检查目标、版本、允许路径与实际出图结果。
4. Chat 展示候选图、摘要、代码和检查报告。继续对话默认基于当前成功候选，失败保留之前的成功候选。
5. 点击“应用此版”后，复核正式代码和依赖是否仍为生成时的版本，再同时保存代码、图片和历史。

规范化也使用同一候选流程，**不会因为渲染成功自动保存为正式版**。每张批量目标独立保存结果；一张失败不会替另一张报告成功。检测到布局冲突时展示诊断图，用户明确接受已显示的冲突后可保留例外；布局或正式版本变化后，旧例外不能自动复用。

## 项目与代码结构

- `projects/<id>/charts/*.py`：正式绘图入口，脚本通过 `CHART_PROJECT_DIR` 读取项目数据，通过 `CHART_OUTPUT` 输出图。
- `projects/<id>/data/`：已保存均值、SD/SEM、p 值、分位数、坐标等绘图用数据。
- `projects/<id>/lib/`：共用函数，候选阶段只读。
- `projects/<id>/images/original/`、`previews/`：上传图片与正式预览缓存。
- `projects/<id>/history/`：逐图正式历史；当前代码保存在入口文件，历史代码保留最早版和上一轮版，图片保留所有版本。
- `projects/<id>/.chat/`：稳定身份映射、会话、原话、候选代码与图片、检查结果和固定参照图片；已从 Git 默认跟踪中排除。
- `chat_agent.py`：加载英文 Chat Skill，调用模型并核对结构化响应。
- `chat_harness.py`：会话、父候选、参照、上下文、状态、应用与冲突检查。
- `chat_runner.py`：macOS 隔离渲染、绘图对象比较、布局诊断。
- `normalizer_agent.py`：加载选择的规范化 Skill 和样式包。
- `studio_style.py`：规范化几何、导出与绘图数据辅助函数。
- `skills/chart-chat-edit/`、`skills/chart-normalization/`：英文执行规则；规范化样式包当前为 1.1。
- `llm_client.py`、`llm_workflows.py`、`skills/chart-code-*/`：合作者新增的兼容流程，用于项目导入时的拆图和旧版单图代码建议接口；新版 Chat 候选仍走 Harness 会话接口。

图片显示名称使用 `X轴组别1&X轴组别2_Y轴标题`，同一组别及顺序的图连续排列；连续数值 X 轴使用 `X轴标题_Y轴标题`。显示名称与后台图 ID 分开，图内部不新增顶部标题。

左上角“＋”新建或上传项目。标准化 Skill 可在左侧查看、上传和删除。图卡提供代码/数据、修改历史与“完成并清理”；清理保留当前图与代码，删除该图历史和 Chat 候选并结束相关会话，已有 Git 提交不受影响。项目上传仍保留本地 Git 记录；整合审阅期间默认不推送到 GitHub。确认发布后可在启动服务前明确设置 `PLOT_FORGE_PUSH_UPLOADS=1`，恢复原有的 `origin/main` 推送行为。新 Chat 候选不会自动推送。

## 检查与当前边界

[完整实施状态](docs/implementation-status.zh-CN.md)记录已接入内容、接口和限制。复查命令：

```bash
/opt/anaconda3/bin/python -m unittest discover -s tests -p 'test_chat_*.py' -v
node tests/test_chat_frontend.js
MPLCONFIGDIR=/tmp/plot-forge-mpl /opt/anaconda3/bin/python docs/acceptance/verify_style.py
```

真实渲染测试应在普通本机终端执行。嵌套在 Codex 外层沙箱中时，Seatbelt 可能无法启动；这时工作流明确拒绝执行候选，不退回无隔离运行。操作系统不支持时同样报告原因。

目前是单机协作原型，尚无多用户登录、权限认证、跨进程锁或生产部署保障。新 Chat/规范化候选路径使用隔离渲染；上传转换、已有预览和手动代码编辑仍有旧渲染路径，不能把全站宣称为沙箱执行。布局和数据检查覆盖常见 Matplotlib 元素，无法证明任意绘图脚本的科学语义完全正确，用户仍需审阅。当前自动化联调用模拟模型输出，尚未完成实际配置模型的端到端验收。
