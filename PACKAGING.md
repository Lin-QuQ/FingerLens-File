# 打包说明

构建依赖会把 FFmpeg 可执行文件一并装入应用，因此最终用户无需另外安装 FFmpeg，导出时可以保留原视频音频。

## GitHub 自动构建 Windows 版

`.github/workflows/build-release.yml` 使用 GitHub 的 `windows-latest` x64 环境执行以下步骤：

1. 安装 Python 3.11 和固定版本依赖。
2. 运行完整自动化测试。
3. 使用 PyInstaller 构建无终端窗口的桌面应用。
4. 校验 `FingerLensFile.exe` 是 Windows x64 PE 文件。
5. 使用打包后的程序加载 MediaPipe 模型并检查 FFmpeg。
6. 生成完整免安装包 `FingerLens-File-Windows-x64.zip`。

在 GitHub 仓库的 **Actions → Build Windows app → Run workflow** 可手动生成测试包。推送 `v*` 标签时会同时创建 GitHub Release。

## 本机打包

```bash
python -m pip install -r packaging/requirements-build.txt
python -m unittest -v
pyinstaller --noconfirm --clean FingerLensFile.spec
```

打包后执行模型与 FFmpeg 自检：

macOS：

```bash
dist/FingerLens\ File.app/Contents/MacOS/FingerLensFile --self-test
```

Windows PowerShell：

```powershell
.\dist\FingerLensFile\FingerLensFile.exe --self-test
```

macOS 当前配置最低支持 macOS 13，并生成 Apple Silicon 应用。Windows 工作流生成 Windows 10/11 x64 应用。未购买商业签名时，首次打开可能出现系统安全提示。
