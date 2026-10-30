# Plot Forge（LY 分支）完整使用说明

本文适用于 GitHub 仓库 `Bonbonwjj/GraphicEditing` 的 `LY` 分支。该分支面向两类工作流：

1. Python 绘图代码配合 CSV、TSV 或 JSON；
2. `behavior_analysis` 生成的 Group/Border Plot Bundle。

平台在本地或受信任内网中运行。导入的数据用于渲染，代码和历史写入平台项目目录；大型 Bundle 可以从只读共享目录直接引用，不需要上传到浏览器或复制进平台。

## 1. 获取代码

```powershell
git clone -b LY https://github.com/Bonbonwjj/GraphicEditing.git
cd GraphicEditing
```

如果已经克隆仓库：

```powershell
git fetch origin
git switch LY
git pull --ff-only origin LY
```

## 2. 运行环境

### 2.1 基础要求

- Python 3.9 或更高版本；
- Matplotlib；
- 绘图代码自身使用的 NumPy、Pandas、SciPy、Seaborn 等依赖；
- 可选：Git。没有 Git 时平台仍可导入、编辑、预览和恢复历史；
- 可选：兼容 OpenAI Chat Completions 的 HTTPS 大模型 API。

平台服务器本身主要使用 Python 标准库。实际绘图依赖取决于所导入的图表代码和 `behavior_analysis` 环境。建议直接使用能够运行原分析代码的 Conda 环境。

### 2.2 Windows 启动示例

```powershell
cd 'D:\path\to\GraphicEditing'

# 允许平台读取的共享数据根目录。多个目录用分号分隔。
$env:CHART_STUDIO_SHARED_ROOTS = 'X:\behavior-data;D:\plot-bundles'

# 导入 Plot Bundle 时复制 behavior_analysis 运行时代码的来源。
$env:BEHAVIOR_ANALYSIS_CODE_ROOT = 'D:\path\to\behavior-analysis-refactor'

# 可选：渲染超时秒数，默认 120。
$env:CHART_RENDER_TIMEOUT = '180'

# 可选：端口，默认 8765。
$env:CHART_STUDIO_PORT = '8765'

& 'D:\conda\envs\WBI_LY\python.exe' server.py
```

浏览器打开：<http://127.0.0.1:8765>

请在普通 PowerShell 中启动服务。受限沙箱中的进程可能无法写入 `projects/`，并出现 `[WinError 5] 拒绝访问`。

### 2.3 Linux/群晖启动示例

```bash
cd /volume1/apps/GraphicEditing
export CHART_STUDIO_SHARED_ROOTS='/volume1/research/behavior-data:/volume1/research/plot-bundles'
export BEHAVIOR_ANALYSIS_CODE_ROOT='/volume1/apps/behavior-analysis-refactor'
export CHART_RENDER_TIMEOUT='180'
export CHART_STUDIO_PORT='8765'
python server.py
```

当前服务固定绑定 `127.0.0.1`。如果需要从其他电脑访问群晖上的服务，应通过受控的反向代理、SSH 隧道或后续增加的认证网关暴露服务，不建议直接把无认证服务绑定到公网。

## 3. 环境变量

| 变量 | 是否必需 | 作用 |
|---|---:|---|
| `CHART_STUDIO_SHARED_ROOTS` | 使用服务器路径导入时必需 | 允许读取的共享目录白名单；Windows 用 `;`，Linux 用 `:` 分隔多个目录 |
| `BEHAVIOR_ANALYSIS_CODE_ROOT` | 导入 Plot Bundle 时建议设置 | 指向包含 `behavior_analysis/` 包的代码根目录，导入时复制运行时代码到项目 `lib/` |
| `CHART_RENDER_TIMEOUT` | 否 | 单次渲染超时秒数，默认 120 |
| `CHART_STUDIO_PORT` | 否 | 本地 HTTP 端口，默认 8765 |
| `OPENAI_API_KEY` | 使用 LLM 时必需 | 大模型 API 密钥，仅从进程环境读取 |
| `LLM_API_URL` | 使用 LLM 时必需 | Chat Completions 接口，必须使用 HTTPS |
| `LLM_MODEL` | 使用 LLM 时必需 | 服务商提供的模型名称 |

## 4. 接入大模型 API

PowerShell 示例：

```powershell
$env:OPENAI_API_KEY = '你的密钥'
$env:LLM_API_URL = 'https://api.siliconflow.cn/v1/chat/completions'
$env:LLM_MODEL = 'Qwen/Qwen3.5-4B'
& 'D:\conda\envs\WBI_LY\python.exe' server.py
```

注意：

- 必须先设置环境变量，再启动服务；已经运行的服务不会自动读取新变量；
- 当前 `LY` 代码只读取 `OPENAI_API_KEY`，不是初始版使用的 `LLM_API_KEY`；
- `LLM_API_URL` 必须是 HTTPS；
- 密钥不会写入项目文件或浏览器存储；
- 模型输出先进入代码预览，用户确认后才会验证并保存；
- 逐图修改会发送当前图表代码和小型表格的列名/前三行预览；
- 共享绘图模块修改只发送模块代码、相对路径、代表图名称和用户指令，不发送数据摘要、Bundle 路径或 payload。

## 5. 项目目录结构

```text
projects/<project_id>/
  project.json              # 项目名称、说明、数据源类型
  data_sources.json         # 数据源登记、只读状态、Bundle 图表映射
  data/                     # 浏览器上传的数据或小型 Bundle 副本
  charts/                   # 一张图一个 Python 入口
  lib/                      # 项目本地共享代码和 behavior_analysis 副本
  outputs/                  # 平台输出目录
  history/                  # 逐图和共享模块历史
```

外部共享目录中的大型 Bundle 不会复制到 `projects/<id>/data/`。`data_sources.json` 只登记其解析后的路径和必要元数据。

## 6. 导入 CSV、TSV 或 JSON 项目

### 6.1 推荐代码目录

```text
my_plot_code/
  charts/
    summary.py
    distribution.py
  lib/
    plot_helpers/
      __init__.py
      colors.py
      labels.py
```

数据目录可以保留子文件夹：

```text
my_data/
  group_a/values.csv
  group_b/values.tsv
  metadata.json
```

导入规则：

- `charts/**/*.py` 转换成独立图表入口；
- `lib/**/*.py` 保留相对路径，成为共享绘图模块；
- `__init__.py` 会保留包结构，但不会显示为可编辑共享模块；
- 如果代码文件夹没有顶层 `charts/` 或 `lib/`，平台沿用旧行为，把找到的 Python 文件分别转换为独立图表；
- 数据文件支持 `.csv`、`.tsv` 和对象/对象数组形式的 `.json`；
- 文件夹上传总大小上限为 500 MB。

### 6.2 页面操作

1. 点击左下角“导入数据源”；
2. 数据源类型选择“CSV / TSV / JSON + Python”；
3. 选择新建项目或更新已有项目；
4. 选择代码文件夹和数据文件夹；
5. 点击“开始导入”；
6. 导入完成后，从左侧“绘图代码”打开图表；存在 `lib/` 时会出现“共享绘图模块”。

页面中的“↑ 表格”适合给当前项目增加单个小型表格，单文件限制为 250 KB。大型或多文件数据应使用“导入数据源”。

## 7. 导入 Plot Bundle

### 7.1 准备 Bundle

先在 `behavior_analysis` 项目中完成处理并导出 Plot Bundle。平台需要的中间结果通常包含：

```text
group_plot_bundle/
  manifest.json
  plot_specs.json
  payloads/*.pkl.gz

border_plot_bundle/
  manifest.json
  plot_specs.json
  payloads/*.pkl.gz
```

Bundle 应包含生成最终图片所需的处理后数据和绘图规格，而不是全部原始实验数据。

### 7.2 大型 Bundle：共享路径导入（推荐）

1. 把 Bundle 放入群晖或服务器共享目录；
2. 以只读方式把共享目录挂载到运行平台的机器；
3. 把其上级目录加入 `CHART_STUDIO_SHARED_ROOTS`；
4. 启动服务时设置 `BEHAVIOR_ANALYSIS_CODE_ROOT`；
5. 页面点击“导入数据源”；
6. 类型选择“Plot Bundle”；
7. 来源选择“共享目录路径”；
8. 填写 Bundle 目录的服务器实际路径；
9. 勾选“来自受信任来源”；
10. 开始导入。

共享路径必须位于白名单根目录内。平台会解析真实路径并拒绝目录穿越。

### 7.3 小型 Bundle：浏览器上传

选择“浏览器上传”并选择整个 Bundle 文件夹。总大小不能超过 500 MB。上传模式会把 Bundle 副本放入项目 `data/bundle/`。

### 7.4 Bundle 安全检查

- 只支持 `behavior-analysis-plot-bundle` 格式版本 1；
- 只支持 `group` 和 `border`；
- 检查 manifest、plot_specs、payload 文件长度和 SHA-256；
- 拒绝超出 Bundle 根目录的文件路径；
- Bundle 中包含 gzip pickle，必须仅导入受信任来源；
- 导入检查阶段不反序列化 payload；
- Border 渲染时只加载当前图对应的 payload；
- Group 普通图只加载 metrics，需要重建轨迹的图才加载轨迹 payload。

## 8. 编辑单张图

1. 在左侧“绘图代码”选择图表；
2. “图像预览”显示当前结果；
3. “绘图代码”可直接编辑完整 Python 入口；
4. “数据源”查看已登记数据源和小型表格预览；
5. 右侧可以输入修改要求，让 LLM 生成候选代码；
6. 检查候选代码后点击“应用修改”，或手工编辑后点击“保存代码”；
7. 平台会先执行语法检查和试渲染，成功后再写入源文件和历史；
8. 可以导出 SVG 或 PDF；
9. “修改历史”可恢复旧版本，恢复操作本身会形成新历史。

图表代码通过以下环境变量访问项目和输出：

```python
import os
from pathlib import Path

project = Path(os.environ["CHART_PROJECT_DIR"])
output = Path(os.environ["CHART_OUTPUT"])
```

## 9. 编辑共享绘图模块

共享模块用于一次调整多张图共同调用的绘图逻辑。

### 9.1 Bundle 项目开放范围

- Group：`lib/behavior_analysis/group/visualization.py`；
- Border：`lib/behavior_analysis/border/visualization/*.py`；
- 不开放 `__init__.py`；
- 不开放 `processing`、`loading`、`service`、`exporting`、`plot_bundle` 和 `bundle_runtime.py`。

### 9.2 保存流程

1. 从“共享绘图模块”选择文件；
2. 在预览上方选择一张代表图；
3. 手工编辑或让 LLM 生成候选模块；
4. 点击保存；
5. 平台检查语法；
6. 平台把项目 `lib/` 复制到临时目录；
7. 候选源码只写入临时副本；
8. 使用临时副本渲染代表图；
9. 成功后原子替换正式模块并记录历史；
10. 失败时删除临时副本，正式模块和历史保持不变。

只在保存时验证代表图。其他引用该模块的图会在下次打开、刷新或导出时加载新版本。

## 10. 群晖权限建议

建议使用两个独立位置：

```text
/volume1/research/behavior-input/   # 数据和 Bundle，只读挂载
/volume1/apps/GraphicEditing/       # 平台代码和 projects，可写
```

运行平台的服务账号：

- 对输入目录只有读取权限；
- 对平台代码、`projects/`、临时目录和日志目录具有写权限；
- 不使用管理员账号运行服务；
- 不把 API 密钥写入仓库、项目 JSON 或启动脚本的公开部分。

`CHART_STUDIO_SHARED_ROOTS` 是应用层路径白名单，不能替代操作系统或群晖 ACL。要确保数据真正不可修改，必须同时把输入共享目录设置为只读。

## 11. Git 行为

- Git 是可选项；
- 如果平台目录位于 Git 仓库中，保存代码或导入项目时会尝试对相关路径创建本地提交；
- Git 操作失败不会阻止平台主要功能；
- 平台默认不会自动执行 `git push`；
- 导入共享目录 Bundle 时，不应把 Bundle 或原始数据加入版本控制。

## 12. 测试

运行全部自动化测试：

```powershell
& 'D:\conda\envs\WBI_LY\python.exe' -m unittest discover -s tests -p 'test_*.py' -v
```

检查前端 JavaScript 语法：

```powershell
node --check static\app.js
```

使用真实 Bundle 做端到端验证：

```powershell
& 'D:\conda\envs\WBI_LY\python.exe' tests\integration_verify_real_bundles.py `
  --bundle-root 'D:\plot_bundles_demo' `
  --code-root 'D:\behavior-analysis-refactor'
```

`--bundle-root` 下应包含 `group_plot_bundle/` 和 `border_plot_bundle/`。

## 13. 常见问题

### `[WinError 5] 拒绝访问 projects/...`

在普通 PowerShell 中启动服务，并确认当前账号对平台目录具有写权限。不要从限制写入权限的沙箱进程启动。

### PowerShell 提示不支持 `from` 关键字

这是把 Python 代码直接粘贴到了 PowerShell。应保存为 `.py` 后运行：

```powershell
& 'D:\conda\envs\WBI_LY\python.exe' your_script.py
```

### 大于 500 MB 无法上传

把 Bundle 放到共享目录，配置 `CHART_STUDIO_SHARED_ROOTS`，然后使用“共享目录路径”模式。平台只读取处理后的 Bundle，不需要上传原始数据。

### 导入 Bundle 后没有共享绘图模块

确认导入时已设置正确的 `BEHAVIOR_ANALYSIS_CODE_ROOT`，并且该目录下存在 `behavior_analysis/group/visualization.py` 或 `behavior_analysis/border/visualization/`。修改环境变量后，需要重新导入项目才能复制新的运行时代码。

### LLM 功能显示未配置

确认设置的是 `OPENAI_API_KEY`，并在同一个 PowerShell 窗口中启动服务。检查 `LLM_API_URL` 是否为 HTTPS、模型名称是否正确。

### 代表图验证超时

选择计算较轻的代表图，或适当增加 `CHART_RENDER_TIMEOUT`。共享模块只验证所选图，不会自动重绘项目中的全部图。

### 图表修改会不会改变处理结果

平台只开放指定的可视化模块，处理和数据读取模块不会出现在共享模块接口中。但图表代码本身是可执行 Python，仍应审核手工或 LLM 生成的代码，并使用只读数据权限作为最终保护。

## 14. 当前限制

- 服务没有用户登录、权限分组或容器级代码隔离；
- 服务固定监听本机回环地址；
- 运行图表意味着执行 Python 代码，只应导入可信代码；
- Bundle 使用 pickle，只应导入可信来源；
- 共享模块保存只验证一张代表图，不保证其他所有图都能成功渲染；
- 平台不会自动识别任意第三方分析项目的处理/可视化边界，Bundle 白名单目前针对 Group 和 Border。
