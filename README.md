# Plot Forge · 科研图表工坊

Plot Forge 是本地运行的 Python 图表编辑平台。它支持两类数据源：

- Python 绘图代码 + CSV、TSV 或 JSON；
- behavior-analysis Plot Bundle（当前重点支持 group 和 border）。

Plot Bundle 会按 `plot_specs.json` 为每条绘图规格建立独立图表。大型 Bundle 可以直接引用群晖或服务器共享目录，不经过浏览器上传，也不会复制或修改原始数据。

## 启动

需要 Python 3.9+ 以及绘图代码本身使用的依赖。Git 是可选的；目录没有初始化 Git 时，导入、编辑和渲染仍可正常工作。

PowerShell 示例：

```powershell
cd 'D:\codex\GraphicEditing-main'
$env:CHART_STUDIO_SHARED_ROOTS = 'D:\codex\behavior analysis_pure\plot_bundles_demo'
$env:BEHAVIOR_ANALYSIS_CODE_ROOT = 'D:\codex\behavior analysis_pure\.worktrees\behavior-analysis-refactor'
& 'D:\conda\envs\WBI_LY\python.exe' server.py
```

浏览器打开 <http://127.0.0.1:8765>。服务默认只绑定本机回环地址。

群晖部署时，把 `CHART_STUDIO_SHARED_ROOTS` 设置为只读挂载点。多个允许根目录用操作系统的路径分隔符连接：Windows 使用 `;`，Linux 使用 `:`。例如 Windows UNC 路径可以配置为 `\\NAS\research\behavior-data`。

## 大模型 API

对话改图需要兼容 Chat Completions 的 HTTPS API；不配置时仍可手动改代码。

```powershell
$env:OPENAI_API_KEY = '你的密钥'
$env:LLM_MODEL = 'Qwen/Qwen3.5-4B'
$env:LLM_API_URL = 'https://api.siliconflow.cn/v1/chat/completions'
```

密钥只从启动进程的环境变量读取。逐图修改会发送当前绘图脚本、用户指令和小型表格的列名/前三行预览；共享绘图模块修改只发送模块源码、模块相对路径、代表图名称和用户指令，不发送数据摘要。Plot Bundle 路径、manifest 和 payload 元数据不会自动发送给模型服务。

## 项目结构

```text
projects/<id>/
  project.json
  data_sources.json
  data/
  charts/
  lib/
  outputs/
  history/
```

- `data_sources.json`：数据源类型、模式、只读状态和图表登记信息；
- `data/`：上传的数据或小 Bundle 副本；
- `charts/*.py`：每张图的独立入口；
- `lib/`：项目本地运行时和 `behavior_analysis` 代码副本；
- `outputs/`：平台生成的输出；
- `history/`：逐图和共享绘图模块的代码版本。

### 共享绘图模块

项目树会把可修改的共享绘图代码显示在“共享绘图模块”下。Plot Bundle 项目严格限制为：

- Group：`lib/behavior_analysis/group/visualization.py`；
- Border：`lib/behavior_analysis/border/visualization/*.py`，不包含 `__init__.py`。

处理、数据读取、导出和 `bundle_runtime.py` 不会显示，也不能通过共享模块接口修改。保存共享模块前需要选择一张代表图；平台在临时 `lib` 副本中渲染该图，成功后才原子替换正式文件。验证失败时，正式模块和历史不会变化。

## 导入方式

在页面点击“导入数据源”：

1. 表格工作流：选择 Python 代码文件夹及 CSV/TSV/JSON 数据文件夹。需要共享代码时，在代码文件夹中使用 `charts/` 和 `lib/` 两个顶层目录；没有这两个目录时沿用旧行为，把 Python 文件作为独立图表导入。
2. 小型 Plot Bundle：选择 Bundle 文件夹，浏览器上传上限为 500 MB。
3. 大型 Plot Bundle：选择“共享目录路径”，填写白名单根目录下的 Bundle 路径。

Bundle 含 gzip pickle，必须确认来源可信。服务端会验证格式版本、文件长度和 SHA-256；导入阶段只读取 manifest/spec，不反序列化 payload。渲染 border 单图时只加载该图对应的 payload；group 普通图只加载 metrics，重建轨迹图才加载大型轨迹 payload。

更完整的部署、接口和更新说明见 [docs/data-source-and-plot-bundle-update.md](docs/data-source-and-plot-bundle-update.md) 和 [docs/UPDATE_SHARED_MODULES.md](docs/UPDATE_SHARED_MODULES.md)。

完整文档：

- [LY 分支完整使用说明](docs/USER_GUIDE.md)
- [LY 分支相对初始版 main 的修改说明](docs/CHANGES_FROM_MAIN.md)

## 安全边界

- 共享目录路径必须位于 `CHART_STUDIO_SHARED_ROOTS` 下，并会在解析后再次检查，拒绝路径穿越。
- 平台把输入数据视为只读，所有输出写入项目目录。
- 平台不会自动向 Git 远端推送代码或数据。
- Plot Bundle 使用 pickle，只能导入受信任来源。
- 当前服务没有多用户登录或容器隔离，定位为受信任内网或单机工作台。
