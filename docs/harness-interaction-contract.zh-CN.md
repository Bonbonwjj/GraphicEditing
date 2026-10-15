# 绘图平台 Agent ↔ Harness 交互契约（中文设计稿）

状态：核心 Chat/规范化候选流程已实现。本文保留完整目标契约，其中部分细分状态、最小依赖分析及通用语义验收仍为目标要求；实际模块、接口、已运行测试和限制以 [实施状态](implementation-status.zh-CN.md) 为准。两种操作现在共用独立候选、检查、预览与明确应用流程，未完成真实部署模型验收。

## 1. 基本约定

1. 用户上传的是**绘图用数据**（如均值、SD、SEM、样本量、p 值、分位数、散点坐标或热图矩阵）与绘图代码。上传的 CSV 和原图只读；不要求平台访问用于原始统计分析的大数据。
2. Agent 负责理解需求、提出修改方案与候选代码。它返回代码和说明，**不能把自己的输出称为已出图**，也不能直接写项目文件。
3. Harness 负责检查文件范围、执行候选代码、生成图、核对结果、管理版本和保存图片。**只有 Harness 实际渲染成功的新图才可作为成功结果显示。**
4. 默认任务范围为用户选中的图。单图任务不得写共用绘图函数、共用 CSV、全局样式或其他图；必要时在目标图入口或其专属适配文件中实现。项目范围的共用修改须由用户明确选择，并预览所有受影响图。
5. 候选图与正式版本分开：预览成功只得到候选图；用户点击“应用”并通过版本复核后，才替换项目当前版本。失败保留原图与原代码。
6. Chat 可以连续修改很多轮；**用户点击某张候选图的“应用此版”是唯一的完成信号**。Agent 不猜测用户是否满意，也不因生成预览就自动替换正式图。
7. **每轮修改目标始终以 Chat 顶部的选择为准**，聊天文字不能自行换目标。用户说“参照图 A 改图 B”时，顶部必须已选 B；A 作为锁定版本的只读参照图显示。顶部与文字目标冲突时先澄清，不能自动切换或继续写代码。

## 2. 角色与职责

| 角色 | 职责 | 不负责 |
| --- | --- | --- |
| 页面/用户 | 选项目与图、输入要求；中央区显示当前正式图，Chat 区显示逐轮新候选图；选择继续修改哪一版、应用或放弃 | 判断 Python 是否安全、直接维护版本号 |
| 导入/项目服务 | 保存上传文件、图与代码的关联、源文件指纹、原图和版本 | 理解改图意图、改写代码 |
| 规范化 Agent | 识别图种与可适用规则，基于已选 Skill/样式包提出候选代码及逐条规则说明 | 运行代码、写 CSV、宣布已通过视觉验收 |
| Chat 改图 Agent（加载 Chat Skill） | 每轮把用户原话及当前候选状态转为明确的修改意图，提出仅涉及目标图的候选代码，说明无法安全完成的部分 | 判断用户已满意、擅自应用、改项目范围、编造数据或统计结果 |
| Harness | 组装相关上下文、约束可写文件、检查候选代码、隔离运行、保存新图、比较图形和数据映射、生成审阅结果、复核版本后应用 | 自行决定用户想怎样改图、凭语言输出代替渲染结果 |

部署在同一进程或不同端口不改变上述职责；通过版本化请求/响应传递，不靠 Agent 互相直接写文件。

## 3. Harness 给 Agent 的输入

Harness 可以读取整个项目，但只把完成当前任务需要的代码与绘图数据提供给 Agent。一次请求含以下内容：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `request_id`、`operation` | 是 | 唯一任务 ID；`normalize` 或 `chat_edit`。 |
| `project_id`、`scope` | 是 | 项目 ID；`single_chart`、`selected_charts` 或显式的 `project`。 |
| `targets[]` | 是 | 每张选中图的 `chart_id`、当前 `base_revision`、入口脚本路径、图种（可未知）和当前图片版本。 |
| `edit_session_id`、`turn_id`、`parent_draft_id` | Chat 必需 | 当前改图会话和本轮 ID；本轮从哪一张候选图/候选代码继续。第一轮 `parent_draft_id` 为空，使用正式版。 |
| `user_message` | Chat 必需 | 完整保留的用户原话；Harness 独立保存，传递整理后的意图时也必须保留原话。规范化时使用选中的 Skill 和规则版本。 |
| `conversation_context` | Chat 必需 | 最近的用户要求、已确认的修改决策、尚未解决的问题和当前候选图/代码摘要；不能只凭最新一句“再向左一点”猜测对象。 |
| `source_files` | 是 | 当前目标图的父候选版入口代码及其实际调用的相关绘图函数；标明哪些是共享依赖、哪些只读。 |
| `reference_charts[]` | 用户引用其他图时必需 | 每张参照图的 ID、固定版本、图片、入口代码及必要元数据，全部只读。Harness 找不到或匹配不唯一时明确报告。 |
| `plot_data` | 是 | 相关 CSV 的只读路径/内容、列名、类型、单位或含义（已知时）和 SHA-256；只提供相关文件，不推断未提供的原始观测。 |
| `baseline_images` | 有则提供 | 当前图的图片与尺寸，供比对；图片不能替代代码或 CSV 中的数值。 |
| `allowed_write_paths` | 是 | 仅可修改的目标图入口文件和目标图专属适配文件；共用文件默认不在此列。 |
| `constraints` | 是 | 不改 CSV、不编造数值、单图不外溢、不自动新增缺失拟合等项目规则。 |
| `layout_exception` | 知情后允许重叠时提供 | Harness 保存的目标图、警告 ID、涉及元素/约束、用户后续轮次及授权原话。无明确授权时为 `null`，不能由 Agent 自行宣称用户已同意。 |
| `skill_id`、`skill_version`、`profile_version` | 规范化必需 | 所选规范化 Skill 与固定样式包版本。Chat 操作若引用样式也记录相应版本。 |

`targets[]` 的版本是**每张图独立**的。批量任务不能只给一个项目版本，否则无法判断其中哪张图在生成候选期间被他人改动。

一个候选分支绑定生成时的正式版 `base_revision`。明确应用后，会话刷新正式基准并清除该图活跃候选；旧基准候选仍可查看，但不能直接覆盖新正式版。每轮候选图有不可变的 `draft_id` 和 `parent_draft_id`。默认下一轮从当前活跃候选版继续；用户可明确选一张旧候选图继续，也可选择“从正式版重新开始”。Harness 提供对应候选代码和图给 Agent，不能仅靠聊天文字还原前一轮代码。

一个会话对同一目标同时只运行一轮生成；新消息可排队或明确取消上一轮。Harness 用 `turn_id`、`parent_draft_id` 拒绝迟到的旧 Agent 响应，避免晚返回的图片覆盖较新的候选图。

目标来源只有 Chat 顶部绑定的稳定图 ID。首次会话使用用户选中的图，后续轮次沿用该选择；用户在界面切换目标时启动或恢复相应会话，旧会话的候选不会被挪到新图。参照图只出现在 `reference_charts[]`，不进入 `allowed_write_paths`。若需要的 A 图尚未装入上下文，Agent 可返回 `needs_context`，Harness 自动补齐并重试；图名、属性对应或文字目标与顶部选择冲突时才问用户。

### 图、代码与版本的身份约定

具体 ID 前缀、生成方式、文件路径和图内元素定位见 [绘图对象命名与身份规则](object-naming.zh-CN.md)。该命名表为待审阅设计；下文短 ID 示例仅为阅读代称，不作为实际 ID 格式。

| 标识 | 作用与生命周期 |
| --- | --- |
| `project_id` | 项目稳定 ID；与显示名称分开。 |
| `chart_id` | 逻辑图的稳定 ID；改名、换代码或重新渲染不变。Chat 顶部、Agent 请求和应用操作均绑定它。 |
| `base_revision` | 本轮会话所基于的正式版本；绑定目标代码快照、相关依赖与只读数据指纹、所用样式/Skill版本及图片产物。应用前核对依赖指纹，不能只比较入口脚本。 |
| `draft_id`、`parent_draft_id` | 一版候选代码及其渲染图的不可变对应关系，和它从哪版候选继续修改。每轮生成新 ID，应用时指定准确的 `draft_id`。 |
| `edit_session_id`、`turn_id` | 区分对话会话与其中一轮，防止不同目标或迟到结果串线。 |
| 代码文件 `path + sha256` | 第一版不必额外设计 `code_id`；路径定位文件，哈希确认文件内容。一个图版本保存完整相关文件清单，修改共用依赖也能检测出来。 |

图 ID 和代码文件不是一对一概念：一张图可以依赖多个代码文件，同一脚本也可能输出多张图。后一种情况需在图记录中保存 `entry_path + output_key` 来定位具体输出，不能把文件名直接当作唯一图身份。用户看到图名和缩略图即可；ID 由 Harness 管理，不让用户抄写确认。

当前文件名仍作为项目图路由；新 Harness 在 `.chat/identity.json` 保存稳定项目/图 ID，使用入口、只读数据/共用代码及平台 Skill/样式指纹计算 `base_revision`，不再只依赖入口源码哈希。该运行字段目前为 `sha256:...` 内容指纹，正式历史记录另有 `rev_...` ID。直接重命名脚本时的 ID 迁移及一入口多逻辑图尚未完成；不得把本文身份目标视为这些能力已全部实现。

输入示意（路径和哈希为示意值）：

```json
{
  "request_id": "req-123",
  "operation": "chat_edit",
  "project_id": "human",
  "scope": "single_chart",
  "targets": [{"chart_id": "01_obs_vs_disd_01", "base_revision": "rev-a1", "entry_path": "charts/01_obs_vs_disd_01.py"}],
  "edit_session_id": "edit-42",
  "turn_id": "turn-3",
  "parent_draft_id": "draft-2",
  "user_message": "只把这张图的图例移到右上角",
  "conversation_context": {"active_draft_summary": "上一轮已调整线宽", "unresolved": []},
  "source_files": [{"path": "charts/01_obs_vs_disd_01.py", "writable": true}, {"path": "lib/source_renderer.py", "writable": false}],
  "plot_data": [{"path": "data/direct_panel_subject_values.csv", "read_only": true, "sha256": "..."}],
  "allowed_write_paths": ["charts/01_obs_vs_disd_01.py", "charts/overrides/01_obs_vs_disd_01.py"],
  "constraints": ["preserve_csv", "preserve_unselected_charts", "preserve_plotted_values"]
}
```

## 4. Agent 给 Harness 的输出（中间结果）

Agent 必须返回一种结构化结果，而不是只返回一段聊天文字：

| 字段 | 含义 |
| --- | --- |
| `status` | `candidate`、`needs_context`、`needs_clarification` 或 `cannot_complete`；`needs_context` 由 Harness 自动补充只读参照后重试。 |
| `interpreted_request` | 目标图、需要修改的属性/元素、原状态（可确认时）、期望状态，以及哪些内容必须保留。 |
| `user_message` | 原样回传用户原话；Harness 与原始请求核对，不用模型改写后的文本替换原话。 |
| `interpreted_request.operations`、`preserve` | 每项记录响应内的 `operation_id`、原话片段或之前轮次/决策引用、目标元素、属性、已知原值、期望变化及处理状态；事实附来源，保留条件单列。 |
| `intent_check` | 写代码前的意图核对：`status`、`unresolved_items`、`implementation_choices`；区分用户要求、已读取事实和 Agent 自选参数。自查不等于验证成功。 |
| `expected_effects` | 候选必需；关联修改项 ID、预期可观察变化、保留检查及需视觉/用户审阅的部分，供 Harness 出图后逐项对照。 |
| `layout_policy` | 候选必需；`mode` 为 `avoid_overlap` 或 `allow_disclosed_overlap`，附相关约束、请求检查项及已有例外引用。 |
| `edit_session_id`、`turn_id`、`parent_draft_id` | 与输入一致，明确本轮基于哪一版代码；Harness 拒绝错接旧候选或迟到轮次的输出。 |
| `proposed_files[]` | 每个拟修改文件的路径、其基准哈希和完整候选内容；Harness 自行计算差异。只能列 `allowed_write_paths` 内文件。 |
| `read_data_refs[]` | 每项必须含 `path`、`sha256`、非空 `columns`（每列的 `name` 和 `role`）。覆盖共用函数实际使用的列；未使用的 CSV 列不作为已绘图输入。候选不读取 CSV 时为空列表。 |
| `reference_usage[]` | 参照图 ID 与固定版本、实际借用的外观属性、A/B 元素对应关系、不能安全迁移的部分。没有参照图时为空。 |
| `affected_chart_ids[]` | Agent 预计会改变的图；单图任务应仅有目标图。 |
| `rule_results_proposed[]` | 规范化操作逐规则的预期处理；**只是提议，不是已验收结果**。 |
| `summary`、`warnings` | 面向审阅的修改说明、潜在问题和未能应用的规则。 |
| `reason` | `needs_clarification` 或 `cannot_complete` 时给出具体问题、缺少什么、为何不能安全完成。 |

`needs_context` 是**内部路由结果**：缺少可识别的只读参照图时，返回所需图 ID/代码/图片，Harness 补齐后重试。它不生成候选图，也不直接要求用户答复；若图名或 A/B 映射无法判定，再用 `needs_clarification`。Harness 对同一请求的自动补上下文设有限次数，避免来回请求同一资料。

Agent 不提交“成功图片”或“已应用”状态。即使候选代码语法正确，仍必须由 Harness 执行并检查。

只有 `intent_check.status = consistent` 且无未解决的阻塞项时可返回 `candidate`。其他状态没有文件修改。Harness 保留并传递原话、整理后的意图和来源依据，检查目标/版本/允许范围；出图后将可检查的实际效果与 `expected_effects` 对照，无法可靠判断的部分标为待审阅。清晰要求不增加用户确认轮次；关键歧义才先提问。不能完成全部要求时不得静默丢弃受阻项，需报告并在未获部分完成授权时询问用户。

### Chat Skill 具体在哪里使用

用户在 Chat 发出一条改图要求时，Harness 先固定目标图、会话和本轮所基于的代码版本，再调用 **Chat 改图 Agent**。Agent 在这一轮加载 Chat Skill：识别“改哪张图、哪个元素、改到什么状态”，利用当前候选代码和简要对话上下文生成结构化意图与候选代码。Harness 随后负责检查和出图。**Skill 是 Agent 的执行说明，不是图片渲染器，也不直接显示在页面或替用户点击应用。**

例如第一轮“把图例移到右上角”得到 `draft-1` 与新图；用户看图后说“再向左一点”，第二轮必须读取 `draft-1` 的真实代码及图例状态，生成以 `draft-1` 为父版本的 `draft-2`。如果第二轮失败，`draft-1` 仍可预览和应用。

## 5. Harness 的中间状态

每张图各自有状态；批量任务在此基础上汇总。状态变化可显示在页面上，但用户通常只需看到简短说明。

| 状态 | Harness 正在做什么 | 可进入的下一状态 |
| --- | --- | --- |
| `received` | 接收任务，记录请求与目标版本。 | `context_ready`、`input_invalid` |
| `context_ready` | 找到相关入口、共用依赖、CSV、原图与允许修改范围。 | `agent_running`、`input_invalid` |
| `agent_running` | 将上下文和用户要求交给所选 Agent；若需补参照图，更新上下文后在同一用户轮次重试。 | `context_ready`（参照补齐）、`candidate_ready`、`needs_clarification`、`cannot_complete`、`agent_failed` |
| `candidate_ready` | 收到候选代码，尚未运行。 | `scope_checking` |
| `scope_checking` | 检查基准版本、可写路径、CSV 只读、源代码结构和明显越界修改。 | `rendering`、`scope_rejected`、`revision_conflict` |
| `rendering` | 在隔离的临时目录运行候选代码，生成候选 PNG；不覆盖项目当前图。 | `verifying`、`render_failed` |
| `verifying` | 检查实际生成文件、图种与现有元素、输入数据映射、裁切与可见性、规范化规则；按实际导出尺寸检查整图布局。重叠冲突有限修复后仍存在时需用户选择；无法可靠判断的项目显式标为未验证。 | `preview_ready`、`validation_failed`、`repairing`、`needs_clarification` |
| `repairing` | 将具体失败原因交回 Agent 进行有限次数修正，再重新检查与渲染。 | `candidate_ready`、`cannot_complete` |
| `preview_ready` | 将**本轮已生成的新图**、候选代码与报告放进 Chat，中央图仍为正式版。 | 新一轮 `agent_running`、`applying`、`discarded`、`revision_conflict` |
| `applying` | 用户点击应用后再次确认目标版本未变化，保存代码、图片和历史。 | `applied`、`revision_conflict`、`apply_failed` |
| `applied` | 新图和代码成为当前版本，记录新版本号。 | 结束 |

失败/终止状态：`input_invalid`（输入不完整）、`needs_clarification`（需求有关键歧义）、`cannot_complete`（数据或安全约束不支持）、`agent_failed`（Agent 未返回有效方案）、`scope_rejected`（改了不允许的文件或其他图）、`render_failed`（代码运行或出图失败）、`validation_failed`（出图但违反硬边界）、`revision_conflict`（原图版本已被更新）、`apply_failed`（保存失败）、`discarded`（用户放弃候选）。这些状态都必须附具体原因；现有版本保持不变。`repairing` 的最大轮数应由 Harness 配置，超过后返回明确失败原因，不能无限循环。

`preview_ready → agent_running → ... → preview_ready` 可以重复任意用户轮次；这是**新的用户修改请求**，不等同于 Harness 因代码错误执行的有限次数 `repairing`。每轮候选都有独立状态；后一轮失败不销毁前一轮成功候选。用户满意时选择某个 `draft_id` 应用，而不是由 Agent 判断满意程度。

### 布局冲突的处理

默认整图的轴标题、刻度、图例、标记、色条标签和子图不得出现非预期重叠或裁切。轴线正常交接、数据曲线交叉、误差线连接和热图格内标记不属于布局冲突。Harness 按实际输出尺寸结合元素边界、裁切及必要视觉检查，记录 `pass`、`conflict`、`unverified` 或 `accepted_exception`；不能可靠检查时不宣称无重叠。

在用户要求及固定规范允许的范围内先有限修复；仍冲突则进入 `needs_clarification`，告知具体元素和约束并提供替代方案。诊断图片可显示但不能作为默认已通过结果。用户在得知冲突后仍明确坚持相同要求，则保存 `layout_exception` 并在后续生成中放行该项，结果保留警告并标记 `accepted_exception`。同一例外不重复询问，新的冲突不自动继承；例外仅放宽已说明的布局要求，不解除数据、范围、科学含义及点击应用要求。

## 6. Harness 给用户的最终输出

### 成功生成候选图（`preview_ready`）

在 **Chat 区域**逐轮显示**目标图的新生成图片**，每张带目标图 ID、`draft_id`、本轮修改摘要、代码差异、应用前检查结果和“继续修改此版 / 应用此版 / 放弃”操作。Chat 顶部区分“修改目标：B”和“参照图：A（只读）”；中央图和项目图廊保持上一张**已应用的正式图**。这里的新图是候选预览，绝不因生成成功自动替换中央图。

### 用户应用后（`applied`）

把被选中 `draft_id` 的新图更新到中央区与图廊，显示新版本号及历史入口。图片与该候选的代码属于同一版本，不能只保存其中之一。其他候选图仍可在 Chat 会话中回看；会话中的候选代码需保留到应用或放弃后，再按既定历史保留策略处理。

### 无法完成

显示具体原因和受影响的目标图，例如“CSV 只有均值，没有可解释的误差列或样本量，因此无法补 SEM 误差线”；如果其他可做的修改仍可安全生成新图，则逐项报告该限制并展示新图。若候选代码整体无法运行或越界，不显示虚假的新图，原代码、原图和当前版本不变。

### 批量图

按图展示新图或失败原因；任务汇总可为全部成功、部分成功或全部失败。每张图独立持有候选版本和状态；不能因为 A 图成功，就宣称 B 图成功。应用时逐图检查基准版本；显式项目范围的共用文件修改必须把所有受影响图作为一个整体审阅和应用，避免只更新其中一部分。

## 7. Harness 必须执行的边界检查

1. **文件范围**：单图任务只允许目标入口及其专属适配文件；共用 `lib/`、全局样式、其他图、上传 CSV 不可写。Agent 若提出共享修改，退回生成单图方案；若无法安全隔离，报告不能完成。
2. **输入数据**：上传 CSV 的文件指纹不能变化。保留原绘图数值、点数、系列、组别和误差含义，除非用户在本次要求中明确要求可追溯的呈现变动；不能凭图像猜测缺失数值。
3. **统计与拟合**：使用已有的绘图值；只有输入列及规则足以确定时才派生用于绘图的误差值，并写明公式与来源。没有现成拟合模型的散点图不自动新增拟合。
4. **可见性**：对坐标范围、裁切、透明度、可见属性、背景同色和元素遮挡进行检查。可程序确定的直接拦截；无法可靠判断的标为 `待人工确认`，不得伪称自动通过。
5. **运行隔离**：候选代码仅能读取提供的项目数据，在受控环境中限时运行，产物写临时目录，不接触密钥或任意外部文件。
6. **版本一致性**：从请求到应用都绑定 `base_revision`。应用时再比较；若项目图已被别人修改，返回 `revision_conflict`，不得覆盖新版本。

## 8. 实施边界

已实现 `chat_agent.py`（Skill 与结构化响应）、`chat_harness.py`（目标/会话/父候选/版本/参照/应用）和 `chat_runner.py`（只读副本、macOS Seatbelt、实际绘图对象与布局检查），并接入页面。规范化也进入候选流，不自动保存；默认 Agent 在 8765 进程内运行，可配置独立 8766/8767 服务。

当前会话公开 `open/running/interrupted/closed`；候选公开主要成功、待澄清、失败、冲突和应用状态。上表中的 `context_ready/scope_checking/verifying/repairing` 等部分细分阶段是同步函数内部步骤，不是全部已经独立持久化和推送的事件。Chat 当前最多一次自动修复；用户新一轮请求不受此次数限制。

真实候选渲染只支持 macOS，外层环境必须允许启动 Seatbelt；失败时不退回无隔离执行。API 密钥不进入候选环境。上传转换、已有图预览与手动改码尚有旧渲染路径，不能对全站作隔离保证。当前只开放目标入口写入，不支持自动新建适配文件。

原话和结构化意图可以做身份、逐项依据和格式核对，不能自动证明语义完全一致。绘图对象检查不等于所有统计/视觉含义都可判定；未覆盖的对象、遮挡及复杂布局应标为待审阅。真实部署模型尚未验收；没有多用户登录、鉴权和生产级跨进程并发设施。测试口径与剩余限制见实施状态。
