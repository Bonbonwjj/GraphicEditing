# 数据源与 Plot Bundle 更新说明

## 这次更新解决了什么

平台不再只认识 CSV。现在统一支持：

- CSV、TSV、JSON + Python 绘图代码；
- behavior-analysis group Plot Bundle；
- behavior-analysis border Plot Bundle；
- 小 Bundle 浏览器上传；
- 大 Bundle / 群晖数据通过服务器路径只读注册。

真实示例验证结果：group Bundle 注册 15 个图表入口，border Bundle 注册 93 个图表入口；两类 Bundle 的代表图均已实际渲染为 PNG。

## Bundle 如何工作

平台导入时读取并验证 `manifest.json` 和 `plot_specs.json`。每条 plot spec 会生成一个 `charts/*.py` 文件。导入阶段不会解压和反序列化 `.pkl.gz` 数据。

- Border：只在打开某张图时校验并加载它自己的 payload。
- Group：普通图加载共享的小型 `metrics.pkl.gz`；只有 reconstructed tracks 图会加载大型轨迹 payload。

源 Bundle 仍位于共享目录，平台只保存绝对只读引用。绘图代码及可修改运行时位于项目自己的 `charts/` 和 `lib/`，输出位于 `outputs/`。

每个生成的图表脚本包含独立的 `customize(context)` 钩子。保持 `return None` 时使用原 renderer，数值和默认输出不变；需要单图改样式或重写绘图时，可以读取 `context.artifact`（border）或 `context.result`（group），把自定义图写入 `context.output_dir` 并返回该文件路径。这样不会修改 Bundle，也不会影响其他图表脚本。

## 群晖 / 共享目录配置

推荐把群晖共享目录以只读权限挂载给运行平台的系统账户，再设置白名单：

```powershell
$env:CHART_STUDIO_SHARED_ROOTS = '\\NAS\research\behavior-data'
$env:BEHAVIOR_ANALYSIS_CODE_ROOT = 'D:\shared-code\behavior-analysis-refactor'
```

Linux 示例：

```bash
export CHART_STUDIO_SHARED_ROOTS='/mnt/nas/behavior-data:/mnt/nas/other-approved-data'
export BEHAVIOR_ANALYSIS_CODE_ROOT='/opt/behavior-analysis-refactor'
python server.py
```

`BEHAVIOR_ANALYSIS_CODE_ROOT` 应指向包含 `behavior_analysis/` 包的目录。导入时该包会复制到项目 `lib/`，之后修改平台项目代码不会改动共享代码或输入数据。

服务会解析真实路径，并拒绝不在白名单内的路径、`..` 越界和指向白名单外的链接。没有配置白名单时，服务器路径导入默认关闭。

## 页面使用步骤

### 表格数据

1. 点击“导入数据源”。
2. 选择“CSV / TSV / JSON + Python”。
3. 新建项目或更新已有项目。
4. 分别选择代码目录和数据目录。
5. 点击“开始导入”。

### 小型 Plot Bundle

1. 数据源类型选择“Plot Bundle”。
2. Bundle 来源选择“浏览器上传”。
3. 选择整个 Bundle 文件夹。
4. 勾选可信来源确认并导入。

浏览器上传总量限制为 500 MB。超过限制请使用共享目录路径。

### 大型 Plot Bundle

1. 数据源类型选择“Plot Bundle”。
2. Bundle 来源选择“共享目录路径”。
3. 输入 `manifest.json` 所在的 Bundle 目录。
4. 勾选可信来源确认并导入。

这条路径不上传原数据，因此 661 MB 的 border 示例不会受到浏览器 500 MB 上限影响。

## HTTP API

查看能力与白名单：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/api/data-sources/capabilities'
```

检查服务器 Bundle：

```powershell
$body = @{
  source_path = 'D:\data\group_plot_bundle'
  trusted = $true
} | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:8765/api/data-sources/inspect' `
  -Method Post -ContentType 'application/json' -Body $body
```

导入服务器 Bundle：

```powershell
$body = @{
  project_id = 'group_demo'
  name = 'Group demo'
  source_path = 'D:\data\group_plot_bundle'
  trusted = $true
} | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:8765/api/data-sources/import' `
  -Method Post -ContentType 'application/json' -Body $body
```

## Git 行为变化

Git 现在是可选能力：

- 当前目录是 Git 仓库时，平台会尝试记录本地提交；
- 不是 Git 仓库时，接口返回 `git.enabled=false`，但功能继续；
- 平台不再自动执行 `git push`，避免未经选择把代码或数据发送到未知远端。

## 大模型隐私边界

LLM 修改请求不会自动读取或上传 Plot Bundle 数据。请求内容限于当前图表脚本、用户指令以及小型表格预览。共享目录绝对路径、Bundle manifest 与 payload 元数据不会附带给外部模型。

## 已知限制

- Bundle 是可信 pickle 格式，不适合接收未知来源文件。
- 一个 group plot spec 可能由旧版 renderer 产生多个文件；平台当前在单图预览中选择该规格生成的第一个 PNG。
- reconstructed tracks 可能包含多页；当前单图预览显示第一张，原 renderer 仍可在项目输出流程中生成全部页面。
- Bundle 图的 SVG/PDF 导出由渲染后的 PNG 转换，不是原生矢量输出。
- 平台目前仍是本地/受信任内网工具，没有多用户身份与任务级容器隔离。

## 验证命令

```powershell
& 'D:\conda\envs\WBI_LY\python.exe' -m unittest discover -v
node --check static/app.js
& 'D:\conda\envs\WBI_LY\python.exe' tests\integration_verify_real_bundles.py `
  --bundle-root 'D:\codex\behavior analysis_pure\plot_bundles_demo' `
  --code-root 'D:\codex\behavior analysis_pure\.worktrees\behavior-analysis-refactor'
```
