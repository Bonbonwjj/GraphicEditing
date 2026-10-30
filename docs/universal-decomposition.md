# 通用绘图工程拆解

从“新建并拆分工程”选择 Python 工程目录。应用备份文件、静态识别绘图入口，显示“通用拆解并验证绘图代码”。确认运行后，对候选入口逐一执行隔离试绘。

## 执行链

`project_preparation.open_project/status → universal_project.discover/start/prepare → chat_runner._one_render → universal_plot_runtime.render_original`

- AST 发现脚本绘图语句、无必填参数的绘图函数，以及依赖绘图模块的主脚本。
- 保留工程的相对目录、脚本同级导入和独立 argv；数据从临时工程副本读取。
- 按 savefig/show 顺序建立图入口；无保存调用时可捕获函数返回值或尚未关闭的画布。
- 运行时读取轨迹与静态模块闭包共同写入 `universal-project.json` 的 source_files/input_files。
- 每个安装的输出重复运行两次，比较 PNG 与图元签名。此项证明可重复性，不代表已与未拦截的原程序输出完成等价比较。
- 已通过双次验证的输出按源码、数据、环境、渲染器与样式配置指纹缓存；失败重试时可复用。缓存位于 `.preparation/universal-cache/`。工程安装成功、正式状态可打开后自动删除该缓存和原生拆解的 `.preparation/native-cache/`；失败任务保留重试缓存。
- 跨入口去重同时要求图片、图元和实际保存位置一致；不同位置生成的相同图片仍分别保留。
- 原始代码放在 `lib/universal/source`，可写入口位于 `charts`。外观改动写入 customize，原代码局部修改写入 UNIVERSAL_SOURCE_EDITS，并只应用于临时副本。
- 后续改图沿用候选图的数据、布局和可见变化检查。源码索引及局部编辑接口均支持通用入口。

## 结果和限制

有已验证图时允许打开改图；存在失败入口或扫描上限时，validation 标记 partial、coverage_complete=false，界面显示部分完成。失败入口的详细错误保留在 checks。完全失败时保留备份，并显示模型分批提取后备流程。

每次逐入口试绘结束后，诊断保存在 `.preparation/universal-diagnostics.json`。全部试绘失败时也保留入口、输出编号及错误详情；还未进入试绘的扫描或复制错误由准备状态记录。

当前实现支持 Python/Matplotlib 及基于 Matplotlib 的 Seaborn，使用应用现有 Python 环境；需要额外参数、缺失依赖、外部路径、网络资源的工程可能需要补充配置。Notebook、R、MATLAB、自动环境安装、独立科学计算切片尚未实现。每入口最多20个输出、最多50个候选入口。导入最多10000个文件、Python源码最多100 MiB；通用工程的数据文件不计入源码和渲染快照的容量限制。

大数据仍保存在本机并参与完整试绘。复制、哈希校验采用流式处理；聊天上下文对超过256 KB的CSV/TSV仅读取有限样本，明确标记truncated_sample、总行数未知。模型不能从样本推断完整分布。备份与逐图快照仍需磁盘空间和I/O时间，当前尚未实现数据外置挂载或按需复制。

每张图的双次试绘完成或失败后，立即释放其 `render_<图ID>` 与 `repeat_<图ID>` 临时目录。原始备份、正式代码、数据、预览、验证报告和聊天记录均保留。已有老进程可以通过 `preparation_cleanup.py --project <工程目录> --work <明确的准备临时目录> --watch` 接管清理：仅回收同时具备已验证缓存及相符预览的完成项，绝不根据目录年龄清理正在运行的图。

Linux 本机模式使用 bubblewrap。系统沙箱、Python 审计和签名检查的保证不同；代码重复运行一致不构成对恶意源码或科学正确性的证明。

## 交互式工程运行配置

工程副本根目录可保存 `run-config.json`，通过原有类和方法传入完整数据目录，避免执行旧电脑绝对路径或弹窗主程序。例如：

```json
{
  "schema": "plot-forge-run/1",
  "entries": [{
    "path": "analysis.py",
    "symbol": "Analyzer",
    "method": "main_analysis",
    "kwargs": {"main_folder": ".", "trust": true}
  }]
}
```

`symbol` 为原函数或类；有 `method` 时先实例化类，再调用该方法。`kwargs` 是该函数/方法的参数；相对路径以临时工程根目录解析。配置中的条目就是本轮明确选择的入口。它不改动原始数据和计算实现。GUI画布后端由运行适配器转为Agg；其他未配置的交互窗口不会被自动猜测回答。

渲染子进程的文件写入容量按最大输入文件与PNG上限取较大值，避免复制大CSV时触发图片的30 MB限制；最终PNG仍单独检查大小。通用工程使用与原生工程相同的120秒CPU限制和150秒墙钟超时。
