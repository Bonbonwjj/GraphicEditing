# Plot Forge · 游戏化科研图表工坊

## 启动

需要 Python 3.10+、Matplotlib、Git。当前环境已安装这些依赖。

```bash
cd /data/tool
python server.py
```

浏览器打开 http://127.0.0.1:8765 。服务仅绑定本机回环地址。

对话改图需要一个兼容 Chat Completions 的 API 密钥（不填仍可手动改图）：

```bash
export OPENAI_API_KEY='你的密钥'
export LLM_MODEL='Qwen/Qwen3.5-4B'
# 可选：export LLM_API_URL='https://api.siliconflow.cn/v1/chat/completions'
python server.py
```

密钥只留在启动服务的环境变量中，不写进项目；点击发送时，所选脚本、CSV 列名及前三行样本和你的指令会发送给配置的模型服务。生成代码在编辑器中预览，只有点击“应用修改”后才会运行并写入磁盘。运行绘图脚本意味着执行 Python 代码，请审核 LLM 生成的修改，仅在可信的本地环境使用。

## 工程结构

- `projects/<id>/project.json`：项目元数据
- `projects/<id>/data/*.csv`：绘图数据
- `projects/<id>/charts/*.py`：绘图源代码
- `projects/<id>/history/`：逐图快照与修改说明
- `skills/plot-style/SKILL.md`：统一绘图规范，包含 8 pt 字体规则
- `studio_style.py`：实际执行的 Matplotlib 统一样式
- `.git/`：本地统一版本库；每次应用代码或导入数据都提交一次

左侧可创建项目、新建图、导入小于 250 KB 的 CSV。点击“⬆ 上传项目”后，可以新建项目或从下拉列表选择已有项目，再分别选择代码文件夹与数据文件夹。系统按项目和上传批次归档原件、生成可编辑图表，并推送到 GitHub 的 origin/main；原始上传目录不会同步。较大的 CSV 直接放进对应项目的 `data/` 文件夹。图表脚本通过 `CHART_PROJECT_DIR` 定位数据，通过 `CHART_OUTPUT` 输出图像。中间可以预览、查看和编辑代码、检查 CSV 列；右侧可恢复历史版本并对话修改。支持导出 SVG/PDF。

新建图提供最简模板。请在代码页按 CSV 列编写绘图逻辑，或配置 LLM 后描述想要的图。此项目不自动创建 GitHub 远程仓库；可以在你自己的 GitHub 新建空仓库后执行：

```bash
git remote add origin <你的仓库地址>
git push -u origin main
```

建议先确认 CSV 中没有不应公开的数据，再决定是否推送到远程仓库。`server.py` 未实现多用户登录或容器隔离，定位为单机个人工作台。
