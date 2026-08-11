# FingerLens 文件版

FingerLens 文件版用于处理本地视频，不需要摄像头。界面分为上传视频、滤镜预览、模式与滤镜三个区域，所有处理均在本机完成。

## 下载 Windows 版

前往 [GitHub Releases](https://github.com/Lin-QuQ/FingerLens-File/releases/latest) 下载 `FingerLens-File-Windows-x64.zip`。完整解压后双击 `FingerLensFile.exe`，无需另外安装 Python、MediaPipe、OpenCV 或 FFmpeg。

## 功能

- 支持读取 MP4、MOV、M4V、AVI、MKV、WebM、WMV、MPG、MPEG 等常见视频
- 合并两轮摄像头筛选结果：保留 22 个现有效果与 10 个新增效果，共 32 个滤镜
- 双指模式只使用两手的拇指和食指，并保留对应连线形成的自交“蝴蝶结/沙漏形”区域；区域边界使用细半透明白线
- 滤镜预览、队列和滤镜槽仅显示滤镜名称，不显示内部编号
- 双指模式预置全部 32 个保留滤镜，新旧效果交错排列；可拖动调整顺序、添加或删除
- 五指模式使用五个指尖生成四个跨手滤镜区域，与原版逻辑相同
- 中间预览区显示原图与 32 个保留滤镜，新旧效果交错排列，支持触控板双指上下滚动
- 五指模式包含可拖动换序的滤镜套装；每套可新增、删除，列表支持右侧小滑轨及触控板滚动，点击套装后可在右侧编辑四个滤镜槽并确认更新
- 五指模式默认重组为 9 套；前 8 套穿插新旧效果，套装 09 保持四槽全绿幕；42–45 分别位于套装 03–06
- 五指模式支持每 1 秒、2 秒、3 秒切换下一套，或永不切换
- 输出 H.264 MP4，保留原视频的画面尺寸、帧率和音轨（奇数尺寸会补 1 像素以兼容播放器）
- 所有画面均在本机处理，不会上传

## 直接运行源码

```bash
conda env create -f environment.yml
conda activate fingerlens-file
python finger_lens_file.py
```

也可以使用 Python 3.11 虚拟环境安装 `requirements.txt` 后运行。

## 使用方法

1. 点击左侧上传区，选择视频。
2. 在中间查看原图和 32 个保留滤镜预览；双指模式下可直接点击缩略图，将滤镜添加到播放队尾。
3. 在右侧选择“双指模式”或“五指模式”。
4. 双指模式按列表顺序切换滤镜；拖动 `☰` 排序，通过下拉框或中间预览添加，点击“删除”移除。至少保留一个滤镜。
5. 五指模式可点击左侧某个滤镜套装，在右侧修改四个滤镜槽；修改后点击“确定并更新该套装”。套装支持拖动换序、新增和删除，至少保留一套。
6. 五指模式选择 1 秒、2 秒、3 秒或永不切换。定时切换到最后一套后会回到第一套。
7. 点击“开始处理并导出”，选择输出 MP4 的保存位置。

纯绿色绿幕会把滤镜区域直接填为标准纯绿色 `#00FF00`。双指模式填充交叉区域，五指模式填充对应指缝区域。

蓝色负片、橙色负片、紫色负片和彩色负片仍带有动态颜色变化，但已经分散到四个不同套装。负片闪烁、电光青、霓虹洋红和酸性绿已按筛选结果从正式应用隐藏。

动态负片包含闪烁画面。光敏感或有光敏性癫痫风险的观众应避免观看，公开发布前建议加入闪烁内容提示。

## 测试

```bash
python -m unittest -v
python finger_lens_file.py --self-test
```

## 打包

PyInstaller 不能跨系统打包。Windows 应用需在 Windows x64 构建，macOS 应用需在 Apple Silicon Mac 构建。

```bash
python -m pip install -r packaging/requirements-build.txt
pyinstaller --noconfirm --clean FingerLensFile.spec
```

产物：

- macOS：`dist/FingerLens File.app`
- Windows：`dist/FingerLensFile/FingerLensFile.exe`

仓库中的 GitHub Actions 工作流会在 Windows x64 环境运行测试、打包应用并生成 `FingerLens-File-Windows-x64.zip`。推送 `v*` 标签时还会创建对应的 GitHub Release。

## 摄像头滤镜筛选工具

`filter_review.py` 是独立的实时筛选工具，不会修改正式视频处理配置。当前一轮只展示新增候选 50–60：参考图的纯蓝剪影，以及 10 个明显但不改变人物结构的色层、双色与黑白波点效果。

```bash
python filter_review.py --group new   # 新增候选 50–60
python filter_review.py --group active # 正式应用现存的滤镜
python filter_review.py --group old   # 全部旧滤镜 01–49（通常无需再筛）
```

- 点击“保留”或按 `K`：记录保留并前往下一个
- 点击“不要”或按 `X`：记录不要并前往下一个
- 使用左右方向键回看，退格键清除当前判断
- 右侧 11 个候选编号可直接跳转，绿色代表保留，红色代表不要
- 点击“导出筛选结果”生成文本清单，之后可按清单精简正式应用

筛选工具仅保留为源码测试工具，不随正式应用打包。摄像头画面仅在本机内存中处理，不会保存或上传。
