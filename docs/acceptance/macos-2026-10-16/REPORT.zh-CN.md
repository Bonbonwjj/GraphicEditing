# macOS 验证报告（2026-10-16）

结论：基础运行和绘图可用，当前版本未通过完整 macOS 验收，尚不适合直接声明可交付。

## 环境与方法

- 实机：macOS 15.7.3，arm64（Apple 芯片）。
- 源码目录：GraphicEditing-main-ready；独立 .venv 使用 Python 3.13.2，按 requirements.txt 安装依赖成功。
- 前端：node tests/test_chat_frontend.js，通过。
- Python：PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring .venv/bin/python -m unittest discover -s tests -v。
- 完整回归：162 tests，400.140 秒；errors=15，skipped=4，未通过。错误中含两个 Bundle 子测试。详见 unittest.log。
- 为避免原生钥匙串访问等待，回归及临时服务器验证使用空钥匙串后端，没有读取或修改个人密钥。

## 实测通过

- launch.main() 完成依赖检查并启动本目录后台，/api/health 返回 200、local-python。测试屏蔽自动打开浏览器。
- 首页与 /static/app.js 返回 200。
- 合成图实际导出 PNG、SVG、PDF 成功。
- 调用 build_desktop.stage_application 在含空格、中文的临时目录准备应用资源，识别 demo_interception、human 两个项目。
- 对上述两个项目各抽测第一张图，preview、svg、pdf 六次 HTTP 请求全部 200，并返回相应格式内容。
- 7 项真实候选流程集成测试通过，模型响应采用模拟数据，没有请求真实模型。

## 问题

1. 源码直接启动不能识别附带项目。两个项目元数据都在 projects/<id>/code/project.json，server.py:333 的 list_projects 只读取 projects/<id>/project.json；实测返回空数组。打包资源准备阶段有转换，但 launch.py/server.py 启动没有相同转换。影响本目录直接双击使用时的初始项目展示。
2. 路径检查不兼容 macOS 默认临时目录别名。collaboration_sync.py:153 检查所有祖先是否符号链接；chat_runner.py:409 同样检查输出目录所有祖先。macOS 的 /var 是 /private/var 的系统别名，默认 TemporaryDirectory 因而被拒绝。完整测试中 12 项协作测试、2 个 Bundle 子测试和 1 项项目导出测试因此报错。不能将临时目录测试的错误直接推断为普通用户目录中的同步必然失败；但路径包含系统别名时可以复现。
3. 原生钥匙串未通过验证：初次 /api/projects 请求超过 10 秒未返回；同一接口会调用 effective_model_config -> keyring.get_password。没有确认是否为系统授权等待，因此作为待验收项，不能断言是权限或代码故障。

## 原因核对

仅对测试进程设置 TMPDIR=/private/tmp（不改代码），重跑 tests.test_collaboration_sync：12 tests / 5.743 秒 / OK。支持系统路径别名触发错误的判断，不能替代源码修复及全量复验。

## 未验证范围

- 此目录没有 .app 或安装包；未构建、安装或验收独立 App，也未验证内置 Python/Git 初始化、Gatekeeper、签名或公证。
- 未覆盖 Intel Mac、其他 macOS 版本。
- 未请求公司模型、未验证 VPN/API Key，未向真实 GitHub 仓库发布。
- Bundle 测试使用合成数据，未验证同事真实大型实验 Bundle。
- local 模式的两个 OS 文件沙箱测试按设计跳过；另两个跳过项为 Windows 专用测试。

## 本次改动

未修改应用源码或附带项目。创建了 .venv、依赖安装标记、启动日志和本报告。验证启动的后台已停止。临时应用与合成输出由临时目录自动清理。
