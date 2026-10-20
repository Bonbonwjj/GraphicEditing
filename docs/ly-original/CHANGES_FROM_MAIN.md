# LY 分支相对初始版 main 的修改说明

比较基线：`main` 分支提交 `79f7c4e77c9585dce0a0ecd43f808eb97c94cead`。

本文只说明平台程序和工作流变化。本次上传没有加入本地实验数据、Group/Border Bundle、浏览器上传缓存或本地项目运行历史。

## 1. 总体定位变化

初始版主要围绕“小型 CSV + 单张 Python 图表”进行本地编辑。`LY` 分支扩展为数据源驱动的平台：

- 继续支持 CSV；
- 新增 TSV 和 JSON；
- 新增 `behavior_analysis` Group/Border Plot Bundle；
- 新增群晖/服务器共享路径；
- 新增共享绘图模块编辑；
- 把导入数据明确视为只读输入；
- Git 从必需依赖改为可选的尽力而为记录。

## 2. 数据源抽象

新增 `data_sources.py`：

- 使用 `DataSourceDescriptor` 统一描述数据源；
- 记录 `kind`、`mode`、`location`、`read_only`、`trusted` 和元数据；
- 支持数据源适配器注册和识别；
- 增加共享路径白名单解析；
- 解析真实路径后再次验证，拒绝 `..`、符号链接或其他方式越出允许根目录。

每个项目新增 `data_sources.json`，前端可显示数据源类型、分析类型、文件/图表数量和只读状态。

## 3. Plot Bundle 支持

新增：

- `bundle_importer.py`：检查并登记 Plot Bundle；
- `bundle_runtime.py`：按图延迟加载处理后 payload 并调用 Group/Border 可视化函数；
- `tests/test_bundle_importer.py`；
- `tests/test_bundle_runtime.py`；
- `tests/integration_verify_real_bundles.py`。

主要行为：

- 支持格式 `behavior-analysis-plot-bundle` 版本 1；
- 支持 `group` 和 `border`；
- 校验 manifest、plot_specs、文件长度和 SHA-256；
- 导入阶段不反序列化 pickle；
- 只允许导入用户确认可信的 Bundle；
- 每条 plot spec 生成一个独立的 `charts/*.py` 入口；
- 导入时把 `behavior_analysis` 代码复制到项目 `lib/`；
- Border 只加载当前图引用的 payload；
- Group 普通图与大型轨迹数据按需分开加载；
- 单图入口保留 `customize(context)` 钩子，用于局部覆盖默认绘图。

## 4. 大文件与共享目录

初始版主要依靠浏览器上传。`LY` 新增两种 Bundle 模式：

- 浏览器上传：保留 500 MB 总上限；
- 服务器路径：从 `CHART_STUDIO_SHARED_ROOTS` 白名单内直接读取，适合超过 500 MB 的 Bundle。

服务器路径模式不会复制大型 Bundle，也不会修改其文件。浏览器上传模式会把 Bundle 副本放入项目 `data/bundle/`。

## 5. 表格导入扩展

初始版主要处理根目录下的 CSV 和 Python 文件。`LY` 的 `generic_importer.py` 与 `upload_importer.py` 增加：

- CSV、TSV、JSON；
- 数据子目录保留；
- 上传路径穿越检查；
- `charts/` 与 `lib/` 显式目录约定；
- `charts/**/*.py` 生成独立图；
- `lib/**/*.py` 保留为共享代码；
- 没有显式目录时继续兼容旧的一文件一图方式；
- 项目新增 `lib/`、`outputs/` 和 `data_sources.json`。

## 6. 共享绘图模块

新增 `shared_modules.py` 和对应 API/UI：

- 项目树增加“共享绘图模块”；
- 普通表格项目显示 `lib/**/*.py`，隐藏 `__init__.py`；
- Group Bundle 只开放 `group/visualization.py`；
- Border Bundle 只开放 `border/visualization/*.py`；
- 处理、读取、导出和 Bundle 运行代码保持不可编辑；
- 模块 ID 使用不透明编码，后端每次重新校验路径和白名单；
- 拒绝绝对路径、目录穿越、非 Python 文件和项目外真实路径；
- 共享模块拥有独立历史目录；
- 支持 LLM 建议、手工编辑、代表图预览、SVG/PDF 和恢复历史。

保存方式采用事务式验证：

1. 复制项目 `lib/` 到临时目录；
2. 把候选模块写入临时副本；
3. 使用临时副本渲染一张代表图；
4. 成功后原子替换正式模块；
5. 失败时正式源码与历史均不变化。

共享模块源码上限为 500 KB，以容纳真实 Group `visualization.py`；普通单图代码继续使用 100 KB 上限。

## 7. 渲染与项目运行环境

`server.render()` 的变化：

- 项目 `lib/` 加入 `PYTHONPATH`；
- 共享模块验证可以把临时 `lib` 放在搜索路径首位；
- 渲染超时由固定 20 秒改为 `CHART_RENDER_TIMEOUT`，默认 120 秒；
- 保留 `CHART_PROJECT_DIR` 和 `CHART_OUTPUT`；
- 临时 Matplotlib 配置仍与项目隔离。

## 8. Git 行为变化

新增 `git_support.py`：

- 检测当前目录是否为 Git 仓库；
- 非 Git 目录不再阻断导入或保存；
- 只暂存当前操作涉及的路径；
- 没有变化时不创建空提交；
- 平台默认不推送远端；
- Git 失败作为状态返回，不影响主要平台操作。

这与初始版文档中“应用修改或导入后推送到 origin/main”的描述不同。`LY` 不会自动推送用户数据或代码。

## 9. LLM 工作流变化

这是需要注意的兼容性变化。

初始版：

- 使用 `llm_client.py`、`llm_workflows.py` 和多个 chart-code skill；
- 支持 `LLM_API_KEY` 和 `OPENAI_API_KEY` 兼容别名；
- 可对上传脚本执行 LLM 自动拆图、校验和修复重试；
- 可允许本机 HTTP OpenAI-compatible 服务。

`LY` 当前运行路径：

- `server.py` 直接调用 Chat Completions；
- 使用 `OPENAI_API_KEY`、`LLM_API_URL` 和 `LLM_MODEL`；
- `LLM_API_URL` 必须为 HTTPS；
- `generic_importer.py` 使用确定性的一文件一图或 `charts/` 目录导入，不自动调用 LLM 拆图；
- LLM 负责已选择图表或共享模块的候选代码修改；
- 共享模块请求不携带数据摘要。

初始版的 `llm_client.py`、`llm_workflows.py`、对应测试和 chart-code skill 仍保留在分支中作为历史参考，但 `LY` 的当前 `server.py` 与 `generic_importer.py` 不调用它们。

## 10. 前端变化

页面新增或调整：

- 数据源类型选择：表格或 Plot Bundle；
- Bundle 来源选择：共享目录或浏览器上传；
- 可信来源确认；
- 项目数据源状态卡片；
- 共享绘图模块树；
- 代表图选择器；
- 图表与共享模块统一使用代码编辑、LLM 建议、预览、导出和历史界面；
- Git 未启用时显示状态但不阻止操作；
- 大型 Bundle 提示使用共享路径。

## 11. 安全与权限变化

新增的防护包括：

- 共享根目录白名单；
- 上传相对路径检查；
- Bundle 内文件路径检查；
- 文件长度与 SHA-256 校验；
- pickle 可信来源确认；
- 数据源只读标记；
- 共享模块白名单和真实路径检查；
- 候选模块临时验证、失败回滚和原子替换；
- LLM 请求减少数据暴露。

平台仍不是安全沙箱：图表和模块代码是可执行 Python。最终的数据只读保证需要依赖群晖 ACL、只读挂载和受限服务账号。

## 12. 测试变化

`LY` 新增或扩展的测试覆盖：

- 数据源适配器与共享根目录；
- Bundle 格式、校验和、缺失 payload、路径逃逸和可信来源；
- Group/Border 延迟 payload 加载与绘图分发；
- CSV/TSV/JSON 与嵌套目录；
- `charts/`、`lib/` 和旧目录兼容；
- Git 可选行为；
- 共享模块白名单、ID/path 安全、临时验证、失败回滚、历史和大型模块；
- 前端 Bundle 与共享模块契约；
- 真实 Group/Border Bundle 端到端渲染。

## 13. 保留的初始功能

以下核心使用方式仍然保留：

- 本地浏览器界面；
- 创建项目和新图；
- 逐图 Python 编辑；
- Matplotlib 实时预览；
- 修改历史与恢复；
- SVG/PDF 导出；
- 统一绘图样式；
- 可选的大模型对话改图。
