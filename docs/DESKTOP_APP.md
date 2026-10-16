# 桌面应用

Windows 与 macOS 安装包内置 Python 3.11、Matplotlib、NumPy、Pandas、SciPy、Pillow、系统密钥库支持以及 Git。使用者不需要安装 Python、Git、Conda 或 Docker。

## 同事使用

1. 下载适合自己操作系统和 CPU 的 ZIP，完整解压。
2. Windows 打开 `Plot Forge/Plot Forge.exe`，不要只复制 exe；macOS 将 `Plot Forge.app` 拖入“应用程序”并打开。
3. 首次打开自动从随包携带的压缩档初始化运行环境，随后在默认浏览器打开本地工作台。后续启动会复用后台。
4. 公司模型需要连接 VPN，首次填写个人 API Key。团队版本固定同步到 `Bonbonwjj/GraphicEditing` 的 `main`，写入仍需要个人 GitHub 账号的仓库权限和 Git 凭据；安装包不会携带开发者的登录凭据。

工作数据保存在 Windows 的 `%LOCALAPPDATA%/PlotForge/workspace` 或 macOS 的 `~/Library/Application Support/PlotForge/workspace`。密钥、候选和项目不会写到应用安装目录。更新 App 后，正式项目和个人配置继续保留。

应用本身仍使用本地网页界面；双击 App 自动管理后台并打开网页。关闭网页不会退出后台，再次打开 App 会复用后台。

## 维护者构建

只需要构建机具备 Conda/Miniforge：

```sh
conda env create -f desktop-environment.yml
conda activate plot-forge-desktop
python build_desktop.py
```

必须在对应操作系统与 CPU 架构构建；Windows 不能交叉生成可验收的 macOS App。输出在 `dist/`，包括可解压运行目录及 ZIP。`desktop-build.yml` 提供 Windows、macOS Apple 芯片和 Intel 的手动 CI 构建入口；本地修改不会自动触发云端构建，需先提交工作流。

安装包只携带正式项目、数据与应用资源，不含 `.chat`、模块候选、模型配置、协作凭据、Git 工作目录和临时预览。第三方许可证随运行环境保留。项目数据随安装包分发，发布前检查内容是否适合团队接收。

默认 CI 产生内部测试包，尚未接入 Apple Developer 证书签名、公证或 Windows 代码签名。正式对外分发前需配置相应签名；不能将尚未执行的 macOS CI 称为已通过 macOS 验收。

## 验收

运行原生启动器并指定 `--smoke-report <绝对路径>`，使用隔离的 `PLOT_FORGE_HOME`：启动器初始化内置环境、使用内置 Git、实际生成 PNG、启动 HTTP 后台并检查健康状态，最后关闭测试后台并写出 JSON 报告。无需模型请求或 GitHub 发布。

运行环境首次安装到固定的用户目录后不能手动移动；需要更换目录时，在新位置重新从安装包初始化。`PLOT_FORGE_HOME` 可用于测试或维护者指定工作区。
