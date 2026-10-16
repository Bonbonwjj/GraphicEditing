# 规范化画图：第一版验收样本

规则来源：[中文版规则](../normalization-rules.zh-CN.draft.md)与 `skills/chart-normalization/assets/style-profile.v1.json`（1.1）。本目录的 `fixtures/<样本名>/` 均保存上传前的 `source.py`、`data.csv`、`original.png`；`shared_helper` 另有共用函数 `shared_draw.py`、第二入口 `companion.py` 和第二张 `companion_original.png`。`fixtures.lock.json` 用 SHA-256 固定每个文件的版本。原图由 `make_fixtures.py` 从原代码和 CSV 生成，**不是规范化后目标图**。

下表是每个样本的目标图形与验收清单。运行后的逐条判定必须依据图形对象及其实际数值，不能只凭整张 PNG 的像素差异。样本中的文字、数值和数据形状可以不同，固定样式值取样式包 1.1。`AX-02` 按 x 轴线、刻度和 label 相对绘图区一起下移 12 pt 判定；y 轴与数据不移动，不要求截短后的端点距离等于 12 pt。

| 样本 | 匹配模板 | 目标图形和必须满足的规则 | 必须保留或例外 |
| --- | --- | --- | --- |
| `box_dataset_a` | `two_group_box` | 1620×1440 px；无上标题；双组位置、箱宽、边距、线宽和轴字体按 G/AX/TX/DIST；与下一样本所有固定样式相同。 | A、B 顺序和各组观测值、箱线统计定义不变。 |
| `box_dataset_b` | `two_group_box` | 与 `box_dataset_a` 用同一画布、绘图区、轴与箱体样式；数值刻度可不同。 | 箱体高度和须随本组数据变化；不能为了图像相同而改数据。 |
| `p_boundaries` | 未配置的四对柱组合；安全通用规则和现有柱元素 | 四个标记依次为 `***`、`**`、`*`、`n.s.`，对应 p = 0.0009、0.001、0.01、0.05；保留四组柱和比较对象。 | 不强套双组柱画布/间距模板；`G-03/G-04/DIST-01/DIST-03` 记 `不适用（missing_template）`。 |
| `line_explicit_error` | `line` | 使用 CSV `sem` 列给每个 x 补误差线，记录“来源：sem，含义：SEM”；误差线 3.2 pt、端帽 8 pt；2160×1440 px。 | 原均值、x 顺序与单条系列保留；不能再次从均值计算 SEM。 |
| `line_replicates` | `line`，保留的旧输入反例 | 不再按默认 SEM 新增误差计算；`SER-02` 报告缺少明确误差定义/汇总映射。 | 保留源代码已有均值计算，不主动改变既有统计。 |
| `line_aggregate_sem` | `line` | CSV 明确 `error_kind=SEM`，使用同一汇总的 sd=0.6、n=9 算出 0.2；保留所有均值、分组与 x 顺序。 | 不能默认 SEM，也不能把不同汇总的 SD/n 交叉配对。 |
| `line_missing_error` | `line` | 仍正常生成 2160×1440 px 折线图；`SER-02` 记 `未满足`，说明没有误差列、明确汇总换算或可判定的误差含义。 | 不编造误差线或将整张图判为失败。 |
| `scatter_existing_fit` | `scatter` | 1620×1440 px；`SER-03` 散点 100 pt²；`SER-04` 已有拟合线改为 3.2 pt 虚线、使用组色。 | 不重算/替换原 `np.polyfit` 的模型、系数和 x 范围；点位不变。 |
| `scatter_without_fit` | `scatter` | 1620×1440 px；只统一 `SER-03` 散点样式；`SER-04` 记 `不适用`。 | 不新增拟合线；不把“无拟合”报告成缺数据或失败。 |
| `violin_quartiles` | `two_group_violin` | 两组各显示 q25、q50、q75 三条横线及 q25–q75 竖线；外侧两条各为中位横线长度的 1/2；1620×1440 px。 | 分位数由原始观测计算；保留原小提琴密度形状。 |
| `heatmap_7x4` | `heatmap` | 2520×2340 px；7 列×4 行被四边框紧贴包住；两个显著标记分别在 `(第1行,第6列)` 为 `***`、`(第3行,第2列)` 为 `*`，均居中；color bar 与实际矩阵等高。 | 保留 `viridis` 色带、28 个值、行列顺序及色标上下限；不强制 `RdBu_r`。 |
| `composite_paired` | 已知元素的混合图；无整图模板 | 分别规范箱线、散点和已有配对连线；对无匹配值记 `missing_template`，其他安全规则逐项应用。 | 5 条配对连线、10 个散点、2 个箱体与对应关系都保留；不可转换成纯箱线或纯散点。 |
| `unknown_polar` | 无模板 | 保持极坐标图可渲染；安全的通用规则可以应用，普通笛卡尔轴位置与轴间距等记 `不适用（missing_template）`。 | 不改成直角坐标、折线图或热图；角度和半径数据不变。 |
| `shared_helper` | `line`，同一共用函数控制两张图 | `source.py` 与 `companion.py` 分别生成 A、B 两张原图。方案必须指出 `shared_draw.draw_series` 被两图共享；共用函数只读，目标图用局部调整；未选 B 时不得改变 B。 | 两张图的系列、数据和语义不变；不可只检查 A 图就宣布共用修改安全。 |

## 逐张图的验收记录格式

每个样本生成一条记录，至少有以下字段：

```json
{
  "fixture_id": "line_missing_error",
  "source_revision": "原代码和CSV的版本或哈希",
  "profile_version": "1.1",
  "matched_template": "line",
  "affected_shared_sources": [],
  "rule_results": [
    {"rule_id": "SER-02", "status": "未满足", "actual": "无误差线", "reason": "CSV仅有x和mean"}
  ],
  "preserved": ["x/y数值", "原系列数", "图种"],
  "preview_path": "规范化后生成的图片路径",
  "image_px": [2160, 1440],
  "dpi": 300
}
```

状态只用 `满足`、`未满足`、`不适用`、`待人工确认`。有模板但未达到规则是 `未满足`；图种或元素不适用是 `不适用`；证据不足、无法可靠判定是 `待人工确认`。`missing_template` 是原因标签。原图或规范化图无法打开、代码无法运行时不得标记 `满足`。显著性数据缺失时不生成星号，并说明未标注原因；没有现成拟合模型时不新增拟合，也不记为缺数据。

## 本阶段与下一阶段的边界

本目录提供可复现的**输入、原图、预期结果说明**，并新增 `verify_style.py` 的确定性运行验收。`verified-style/` 是运行该脚本生成的合成候选图与结果，不是部署模型生成的图，也不是全部规则的金标准。真实模型输出仍需 Harness 逐条检查；不能仅因这里的测试通过就判定任意上传图全部合格。


## 2026-10-03 运行验收

执行 `MPLCONFIGDIR=/tmp/plot-forge-mpl python3 docs/acceptance/verify_style.py`。17 项确定性检查通过，结果保存在 `verified-style/results.json`：

- 使用渲染器测量：底轴、x 刻度文字和 x label 相对零偏移版均下移准确 12 pt，左轴和数据像素位置不变。
- 普通轴止于可见刻度；柱状完整基线；类别 y 轴标签保留；数值 y 主刻度不超过 5。
- 两面板、双轴、极坐标不误套单面板模板，不重叠放置子图。
- 7×4 热图无偏移闭合边框、color bar 与实际矩阵等高、viridis 与色限及矩阵值不变。
- 即使全局 rcParams 配置 tight crop，输出仍符合固定像素尺寸。
- 明确 SEM 列、已提供 sample SD+n 换算 SEM、已定义 CI 区间正常；无误差含义、重复行、错误 n、负误差均不编造结果。
- 缺少拟合模型时不新增拟合。
- 小提琴使用已提供 quartile，三横线、IQR 竖线齐全，25%/75% 线各为中位线一半，原密度顶点不变。

这些测试检查实现的几何及数据辅助函数，不涵盖任意脚本所有 artist 的识别、通用显著性布局或部署模型表现。模板选择与 artist-specific 修改由 Agent 完成，Harness 必须保留未验证项。当前环境 `STHeiti` 缺少部分粗字重时，英文标题使用样式包已有的 `DejaVu Sans` 回退粗体并记录字体替换；中文标题保留可显示中文的字体，同时报告粗细未验证，不能静默宣称固定粗体已满足。
