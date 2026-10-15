# 共享绘图模块更新说明

## 本次新增

平台现在能分别编辑“单张图入口”和“共享绘图模块”。共享模块的一次修改可以影响所有引用它的图，但保存时只运行用户选择的一张代表图，以控制 Group/Border 大项目的等待时间。

## Bundle 项目

Group 项目开放：

```text
lib/behavior_analysis/group/visualization.py
```

Border 项目开放：

```text
lib/behavior_analysis/border/visualization/counts.py
lib/behavior_analysis/border/visualization/eta.py
lib/behavior_analysis/border/visualization/fate.py
lib/behavior_analysis/border/visualization/roaming_dwell.py
```

实际列表以导入代码副本中存在的文件为准。平台不会开放 `processing`、`loading`、`service`、`exporting`、`plot_bundle`、`bundle_runtime.py` 或 `__init__.py`。

## CSV/TSV/JSON 项目目录

推荐把上传的代码目录整理为：

```text
my_plot_code/
  charts/
    group_summary.py
    group_distribution.py
  lib/
    plot_helpers/
      colors.py
      group_style.py
```

- `charts/**/*.py` 转换为可单独运行的图表入口；
- `lib/**/*.py` 保持相对目录并显示为共享绘图模块；
- `lib/**/__init__.py` 作为包结构保留，但不显示为可编辑模块；
- 旧代码目录如果没有顶层 `charts` 或 `lib`，仍按原方式把所有 Python 文件转换为图表。

## 使用步骤

1. 启动平台并导入 Bundle，或导入含 `charts/`、`lib/` 的表格代码包。
2. 展开项目，在“共享绘图模块”下选择一个文件。
3. 在图像预览上方选择代表图。
4. 手工修改源码，或在右侧描述修改要求让大模型生成候选代码。
5. 点击“保存代码”或“应用修改”。
6. 平台先检查语法，再复制项目 `lib` 到临时目录，把候选源码写入临时副本并渲染代表图。
7. 只有渲染成功后，正式模块才会被替换并写入模块历史。其他相关图在下次打开、刷新或导出时使用新版本。

## 数据与失败保护

- 验证过程不复制、覆盖或写入原始数据、外部共享目录或 Plot Bundle payload；
- 候选代码语法错误、导入失败、绘图异常或超时均不会覆盖正式模块；
- 共享模块历史位于项目的 `history/modules/`，与逐图历史分开；
- 恢复旧版本时也会先用当前选择的代表图验证；
- 共享模块接口重新检查文件白名单和解析后的实际路径，不能借助构造 URL 编辑处理代码或项目外文件。

## 大模型请求范围

共享模块修改请求只包含：

- 用户指令；
- 当前共享模块完整源码；
- 模块在项目 `lib` 下的相对路径；
- 代表图名称；
- 平台绘图规范。

请求不包含 CSV 摘要、Bundle manifest、payload 内容、服务器路径或共享目录路径。
