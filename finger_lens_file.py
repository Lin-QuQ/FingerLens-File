#!/usr/bin/env python3
"""FingerLens File — process an uploaded video with two-hand filters."""

from __future__ import annotations

import argparse
import base64
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
# MediaPipe imports optional drawing helpers even though this app does not use
# them. Keep frozen builds small by providing the same harmless stub as the
# core module before MediaPipe is imported.
if getattr(sys, "frozen", False):
    import types

    matplotlib_stub = types.ModuleType("matplotlib")
    pyplot_stub = types.ModuleType("matplotlib.pyplot")
    matplotlib_stub.__path__ = []
    matplotlib_stub.pyplot = pyplot_stub
    sys.modules.setdefault("matplotlib", matplotlib_stub)
    sys.modules.setdefault("matplotlib.pyplot", pyplot_stub)

import mediapipe as mp
import numpy as np

from finger_lens_core import (
    FILTER_NAMES,
    FILTER_SETS,
    SmoothLandmarks,
    draw_zones,
    ensure_model,
    fashion_filter,
    make_landmarker,
    normalize_hands,
)


APP_NAME = "FingerLens 文件版"
SUPPORTED_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".wmv", ".mpg", ".mpeg",
}
SET_NAMES = {
    1: "反片铬印 · 动漫墨线 · 厚涂油画 · 黑白胶片",
    2: "日晒反转 · 故障拼贴 · 热成像浮雕 · 铅笔素描",
    3: "波普印刷 · 水彩 · 蓝晒 · 半调网点",
    4: "金属浮雕 · 霓虹轮廓 · 双色剪纸 · 像素漫画",
    5: "X 光 · 棕褐胶片 · 海报浮雕 · 棱镜镜像",
    6: "蒸汽波 · 全息镭射 · 紫外海报 · 液态铬",
    7: "珊瑚孔版 · CMYK 套色 · 报纸网印 · 水墨",
    8: "极光 · 落日热感 · 潟湖玻璃 · 翡翠浮雕",
    9: "RGB 残影 · CRT 梦境 · 数据缎带 · 矩阵荧光",
    10: "金箔 · 玫瑰金 · 珍珠偏光 · 黑曜石",
    11: "纯绿色绿幕（#00FF00）",
    12: "蓝色负片 · 橙色负片 · 紫色负片 · 彩色负片",
    13: "负片闪烁 · 电光青 · 霓虹洋红 · 酸性绿",
}
FILTER_CN_NAMES = dict(enumerate((
    "反片铬印", "动漫墨线", "厚涂油画", "黑白胶片",
    "日晒反转", "故障拼贴", "热成像浮雕", "铅笔素描",
    "波普印刷", "水彩", "蓝晒", "半调网点",
    "金属浮雕", "霓虹轮廓", "双色剪纸", "像素漫画",
    "X 光", "棕褐胶片", "海报浮雕", "棱镜镜像",
    "蒸汽波", "全息镭射", "紫外海报", "液态铬",
    "珊瑚孔版", "CMYK 套色", "报纸网印", "水墨",
    "极光", "落日热感", "潟湖玻璃", "翡翠浮雕",
    "RGB 残影", "CRT 梦境", "数据缎带", "矩阵荧光",
    "金箔", "玫瑰金", "珍珠偏光", "黑曜石",
    "纯绿色绿幕", "蓝色负片", "橙色负片", "紫色负片",
    "彩色负片", "负片闪烁", "电光青", "霓虹洋红", "酸性绿",
    "纯蓝剪影", "红色罩染", "蓝色罩染", "玫瑰罩染", "紫色罩染",
    "青色罩染", "琥珀罩染", "黑白波点", "玫瑰双色", "蓝色双色", "红蓝电影",
), start=1))
ACTIVE_FILTER_IDS = (
    25, 51, 26, 27, 29, 52, 38, 39, 42, 53, 11, 22, 43, 54,
    18, 19, 44, 55, 7, 13, 45, 56, 8, 12, 33, 50, 34, 57,
    15, 58, 59, 41,
)
FILTER_OPTIONS = tuple(FILTER_CN_NAMES[number] for number in ACTIVE_FILTER_IDS)
FILTER_ID_BY_OPTION = {FILTER_CN_NAMES[number]: number for number in ACTIVE_FILTER_IDS}
FINGER_ZONE_NAMES = ("拇指—食指", "食指—中指", "中指—无名指", "无名指—小指")
DEFAULT_TWO_FILTER_SEQUENCE = (
    25, 51, 26, 27, 29, 52, 38, 39, 42, 53, 11, 22, 43, 54,
    18, 19, 44, 55, 7, 13, 45, 56, 8, 12, 33, 50, 34, 57,
    15, 58, 59, 41,
)
DEFAULT_FIVE_SUITES = (
    (25, 51, 26, 27),
    (29, 52, 38, 39),
    (42, 53, 11, 22),
    (43, 54, 18, 19),
    (44, 55, 7, 13),
    (45, 56, 8, 12),
    (33, 50, 34, 57),
    (15, 58, 59, 29),
    (41, 41, 41, 41),
)
_graphics_initialized = False


class ColorButton(tk.Label):
    """High-contrast cross-platform action button with an explicit state."""

    def __init__(
        self,
        master,
        *,
        text: str,
        command,
        state: str = "normal",
        normal_bg: str,
        hover_bg: str,
        disabled_bg: str = "#30323a",
        **kwargs,
    ) -> None:
        self.command = command
        self._state = state
        self.normal_bg = normal_bg
        self.hover_bg = hover_bg
        self.disabled_bg = disabled_bg
        kwargs.setdefault("fg", "#ffffff")
        kwargs.setdefault("font", ("Helvetica", 12, "bold"))
        kwargs.setdefault("padx", 24)
        kwargs.setdefault("pady", 12)
        kwargs.setdefault("relief", "flat")
        super().__init__(master, text=text, **kwargs)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._render()

    def _render(self, hover: bool = False) -> None:
        enabled = self._state == "normal"
        bg = self.hover_bg if enabled and hover else self.normal_bg if enabled else self.disabled_bg
        super().configure(bg=bg, fg="#ffffff" if enabled else "#858a98", cursor="hand2" if enabled else "arrow")

    def _click(self, _event=None):
        if self._state == "normal" and self.command:
            return self.command()
        return None

    def _enter(self, _event=None) -> None:
        self._render(True)

    def _leave(self, _event=None) -> None:
        self._render(False)

    def configure(self, cnf=None, **kwargs):
        state = kwargs.pop("state", None)
        result = super().configure(cnf, **kwargs)
        if state is not None:
            self._state = state
            self._render()
        return result

    config = configure

    def cget(self, key):
        if key == "state":
            return self._state
        return super().cget(key)

    def invoke(self):
        return self._click()


class MiniScrollbar(tk.Canvas):
    """Always-visible narrow scrollbar that is not hidden by macOS settings."""

    def __init__(self, master, *, command, **kwargs) -> None:
        kwargs.setdefault("width", 11)
        kwargs.setdefault("bg", "#20222a")
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("borderwidth", 0)
        kwargs.setdefault("cursor", "sb_v_double_arrow")
        super().__init__(master, **kwargs)
        self.command = command
        self.first = 0.0
        self.last = 1.0
        self.drag_y: int | None = None
        self.drag_first = 0.0
        self.thumb = self.create_rectangle(2, 0, 9, 10, fill="#9a82ff", outline="")
        self.bind("<Configure>", lambda _event: self._draw_thumb())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda _event: setattr(self, "drag_y", None))

    def set(self, first, last) -> None:
        self.first = max(0.0, min(1.0, float(first)))
        self.last = max(self.first, min(1.0, float(last)))
        self._draw_thumb()

    def _thumb_geometry(self) -> tuple[float, float]:
        height = max(1, self.winfo_height())
        top = self.first * height
        bottom = self.last * height
        if bottom - top < 24:
            bottom = min(float(height), top + 24)
            top = max(0.0, bottom - 24)
        return top, bottom

    def _draw_thumb(self) -> None:
        top, bottom = self._thumb_geometry()
        self.coords(self.thumb, 2, top, max(3, self.winfo_width() - 2), bottom)

    def _press(self, event) -> None:
        top, bottom = self._thumb_geometry()
        if event.y < top:
            self.command("scroll", -1, "pages")
        elif event.y > bottom:
            self.command("scroll", 1, "pages")
        else:
            self.drag_y = event.y
            self.drag_first = self.first

    def _drag(self, event) -> None:
        if self.drag_y is None:
            return
        height = max(1.0, float(self.winfo_height()))
        thumb_fraction = max(0.0, self.last - self.first)
        available = max(1.0, height * (1.0 - thumb_fraction))
        fraction = self.drag_first + (event.y - self.drag_y) / available * (1.0 - thumb_fraction)
        self.command("moveto", max(0.0, min(1.0 - thumb_fraction, fraction)))


def initialize_macos_graphics() -> None:
    """Initialize Cocoa/OpenGL before MediaPipe creates its GPU service.

    MediaPipe's macOS graph requires a graphics service even with CPU inference.
    The two-pixel OpenCV window never contains user video and is effectively
    invisible behind the main application window.
    """
    global _graphics_initialized
    if platform.system() != "Darwin" or _graphics_initialized:
        return
    window = "FingerLens processing engine"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 2, 2)
    cv2.imshow(window, np.zeros((2, 2, 3), dtype=np.uint8))
    cv2.waitKey(1)
    _graphics_initialized = True


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def find_ffmpeg() -> str | None:
    """Locate the bundled FFmpeg first, then a developer system install."""
    try:
        import imageio_ffmpeg

        executable = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if executable.exists():
            return str(executable)
    except Exception:
        pass
    for name in ("ffmpeg.exe", "ffmpeg"):
        bundled = resource_path(name)
        if bundled.exists():
            return str(bundled)
    return shutil.which("ffmpeg")


def video_metadata(path: Path) -> tuple[int, int, float, int, np.ndarray]:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("无法打开这个视频，请确认文件没有损坏，并尝试转换为 MP4 或 MOV。")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        ok, preview = capture.read()
        if not ok or preview is None or width <= 0 or height <= 0:
            raise ValueError("读取不到视频画面，请尝试转换为 MP4 或 MOV。")
        if not np.isfinite(fps) or fps <= 1e-3:
            fps = 30.0
        return width, height, fps, frames, preview
    finally:
        capture.release()


def preview_png_data(frame: np.ndarray) -> bytes:
    """Return Tk-compatible base64 PNG data for a BGR preview frame."""
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("无法生成视频预览图")
    return base64.b64encode(encoded.tobytes())


def reorder_items(items: list, source: int, target: int) -> list:
    """Return a copy with one item moved in an ordered sequence."""
    if not 0 <= source < len(items) or not 0 <= target < len(items):
        raise IndexError("sequence index out of range")
    reordered = list(items)
    moved = reordered.pop(source)
    reordered.insert(target, moved)
    return reordered


def reorder_suites(suites: list[tuple[int, ...]], source: int, target: int) -> list[tuple[int, ...]]:
    """Return a copy with one complete filter suite moved in the sequence."""
    return reorder_items(suites, source, target)


def scroll_units(delta: int | float = 0, button_number: int | None = None) -> int:
    """Normalize macOS/Windows wheel deltas and Linux wheel buttons."""
    if delta:
        if abs(delta) >= 120:
            return int(-delta / 120)
        return -1 if delta > 0 else 1
    if button_number == 4:
        return -1
    if button_number == 5:
        return 1
    return 0


def filters_for_time(
    finger_mode: str,
    two_filter_sequence: tuple[int, ...],
    filter_suites: tuple[tuple[int, ...], ...],
    switch_interval: float | None,
    elapsed_seconds: float,
) -> tuple[tuple[int, ...], int]:
    """Choose active filters without using gesture-based switching."""
    if finger_mode == "two":
        if not two_filter_sequence:
            raise ValueError("two mode requires at least one filter")
        if any(filter_id not in ACTIVE_FILTER_IDS for filter_id in two_filter_sequence):
            raise ValueError("two mode contains an invalid filter id")
        if switch_interval is None:
            index = 0
        else:
            if switch_interval <= 0:
                raise ValueError("switch interval must be positive")
            index = int(max(elapsed_seconds, 0.0) // switch_interval) % len(two_filter_sequence)
        return (two_filter_sequence[index],), index
    if finger_mode != "five" or not filter_suites:
        raise ValueError("five mode requires at least one filter suite")
    if switch_interval is None:
        index = 0
    else:
        if switch_interval <= 0:
            raise ValueError("switch interval must be positive")
        index = int(max(elapsed_seconds, 0.0) // switch_interval) % len(filter_suites)
    return tuple(filter_suites[index]), index


def _ffmpeg_command(
    executable: str,
    source: Path,
    destination: Path,
    width: int,
    height: int,
    fps: float,
) -> list[str]:
    return [
        executable,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-video_size", f"{width}x{height}",
        "-framerate", f"{fps:.8f}",
        "-i", "pipe:0",
        "-i", str(source),
        "-map", "0:v:0",
        "-map", "1:a?",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(destination),
    ]


def process_video(
    source: Path,
    destination: Path,
    finger_mode: str,
    two_filter_sequence: tuple[int, ...],
    filter_suites: tuple[tuple[int, ...], ...],
    switch_interval: float | None,
    model_path: Path,
    detect_width: int,
    cancel_event: threading.Event,
    update,
) -> None:
    """Process every frame and encode a broadly compatible MP4 with audio."""
    width, height, fps, total_frames, _ = video_metadata(source)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("找不到 FFmpeg，无法生成带音频的 MP4。请重新安装完整应用。")

    destination.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError("视频在开始处理时无法打开。")

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.system() == "Windows" else 0
    encoder = subprocess.Popen(
        _ffmpeg_command(ffmpeg, source, destination, width, height, fps),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=creation_flags,
    )
    smoother = SmoothLandmarks(0.58)
    frame_index = 0
    preview_every = max(1, round(fps / 4.0))

    try:
        with make_landmarker(ensure_model(model_path)) as landmarker:
            while not cancel_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    break
                scale = min(1.0, detect_width / max(width, 1))
                detection = (
                    cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                    if scale < 1.0 else frame
                )
                rgb = cv2.cvtColor(detection, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp_ms = int(frame_index * 1000.0 / fps)
                result = landmarker.detect_for_video(mp_image, timestamp_ms)
                hands = normalize_hands(result, width, height, smoother, selfie_mirrored=False)

                elapsed = frame_index / fps
                current_filter_ids, suite_index = filters_for_time(
                    finger_mode,
                    two_filter_sequence,
                    filter_suites,
                    switch_interval,
                    elapsed,
                )
                style = suite_index + 1

                phase = frame_index / fps * 2.2
                output = draw_zones(
                    frame,
                    hands,
                    phase,
                    style,
                    finger_mode=finger_mode,
                    custom_filter_ids=current_filter_ids,
                )
                try:
                    assert encoder.stdin is not None
                    encoder.stdin.write(output.tobytes())
                except (BrokenPipeError, OSError) as exc:
                    raise RuntimeError("视频编码器意外停止。") from exc

                frame_index += 1
                if frame_index % preview_every == 0 or frame_index == 1:
                    progress = frame_index / total_frames if total_frames > 0 else 0.0
                    current_label = (
                        f"套装 {suite_index + 1:02d}"
                        if finger_mode == "five"
                        else FILTER_CN_NAMES[current_filter_ids[0]]
                    )
                    update(progress, frame_index, total_frames, current_label, output)

        if cancel_event.is_set():
            raise InterruptedError("处理已取消")
        assert encoder.stdin is not None
        encoder.stdin.close()
        stderr = encoder.stderr.read().decode("utf-8", errors="replace") if encoder.stderr else ""
        return_code = encoder.wait()
        if return_code != 0:
            raise RuntimeError(f"FFmpeg 编码失败：{stderr.strip() or '未知错误'}")
        final_label = "完成"
        update(1.0, frame_index, total_frames, final_label, None)
    except Exception:
        if encoder.stdin and not encoder.stdin.closed:
            encoder.stdin.close()
        if encoder.poll() is None:
            encoder.terminate()
            try:
                encoder.wait(timeout=3)
            except subprocess.TimeoutExpired:
                encoder.kill()
        destination.unlink(missing_ok=True)
        raise
    finally:
        capture.release()


class FingerLensFileApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1380x820")
        self.root.minsize(1100, 700)
        self.root.configure(bg="#101116")
        self.source: Path | None = None
        self.destination: Path | None = None
        self.cancel_event = threading.Event()
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.video_preview_photo: tk.PhotoImage | None = None
        self.filter_preview_photos: list[tk.PhotoImage] = []
        self.mode_var = tk.StringVar(value="two")
        self.two_filters = list(DEFAULT_TWO_FILTER_SEQUENCE)
        self.two_add_var = tk.StringVar(value=self._filter_option(DEFAULT_TWO_FILTER_SEQUENCE[0]))
        self.two_drag_index: int | None = None
        self.suites = [tuple(filters) for filters in DEFAULT_FIVE_SUITES]
        self.selected_suite_index = 0
        self.draft_filter_ids = list(self.suites[0])
        self.draft_dirty = False
        self.suite_drag_index: int | None = None
        self.slot_vars = [tk.StringVar() for _ in range(4)]
        self.double_speed_var = tk.StringVar(value="2")
        self.five_speed_var = tk.StringVar(value="2")
        self.status_var = tk.StringVar(value="选择视频后即可开始")
        self.detail_var = tk.StringVar(value="支持 MP4、MOV、M4V、AVI、MKV、WebM、WMV、MPG")
        self.progress_var = tk.DoubleVar(value=0.0)
        self._build_ui()
        self._render_two_filter_list()
        self._refresh_slot_editor()
        self._render_suite_list()
        self.root.after_idle(lambda: self.suite_canvas.yview_moveto(0.0))
        self._mode_changed()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_events)
        self.root.after(180, self._build_filter_previews)

    def _filter_option(self, filter_id: int) -> str:
        return FILTER_CN_NAMES[filter_id]

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor="#24262f", background="#73f3bc", borderwidth=0)
        style.configure("Filter.TCombobox", fieldbackground="#f1f2f5", background="#353946", foreground="#151821", arrowcolor="#ffffff", bordercolor="#4a4f60")
        style.map("Filter.TCombobox", fieldbackground=[("readonly", "#f1f2f5")], foreground=[("readonly", "#151821")], selectbackground=[("readonly", "#f1f2f5")], selectforeground=[("readonly", "#151821")])

    def _card(self, parent) -> tk.Frame:
        return tk.Frame(parent, bg="#191b22", highlightbackground="#30333d", highlightthickness=1)

    def _build_ui(self) -> None:
        self._configure_styles()
        header = tk.Frame(self.root, bg="#101116")
        header.pack(fill="x", padx=26, pady=(20, 14))
        tk.Label(header, text="FingerLens", fg="#f4f5f8", bg="#101116", font=("Helvetica", 25, "bold")).pack(side="left")
        tk.Label(header, text="文件版  ·  本机离线处理", fg="#73f3bc", bg="#101116", font=("Helvetica", 12)).pack(side="left", padx=14, pady=(8, 0))
        tk.Label(header, text="上传 → 预览 → 配置 → 导出", fg="#a7aab4", bg="#101116", font=("Helvetica", 11)).pack(side="right", pady=(8, 0))

        body = tk.Frame(self.root, bg="#101116")
        body.pack(fill="both", expand=True, padx=26)
        body.grid_columnconfigure(0, weight=4, uniform="body")
        body.grid_columnconfigure(1, weight=3, uniform="body")
        body.grid_columnconfigure(2, weight=5, uniform="body")
        body.grid_rowconfigure(0, weight=1)

        upload = self._card(body)
        previews = self._card(body)
        config = self._card(body)
        upload.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        previews.grid(row=0, column=1, sticky="nsew", padx=7)
        config.grid(row=0, column=2, sticky="nsew", padx=(7, 0))

        tk.Label(upload, text="01  上传视频", fg="#f4f5f8", bg="#191b22", font=("Helvetica", 15, "bold")).pack(anchor="w", padx=18, pady=(16, 10))
        self.video_canvas = tk.Canvas(upload, bg="#0d0e12", highlightbackground="#3c404d", highlightthickness=1, cursor="hand2")
        self.video_canvas.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        self.video_canvas.bind("<Button-1>", lambda _event: self.choose_video())
        self.video_canvas.bind("<Configure>", lambda _event: self._draw_empty_video() if not self.video_preview_photo else None)
        self.file_label = tk.Label(upload, text="尚未选择文件", fg="#f4f5f8", bg="#191b22", font=("Helvetica", 11, "bold"), anchor="w")
        self.file_label.pack(fill="x", padx=18)
        tk.Label(upload, textvariable=self.detail_var, fg="#8f93a0", bg="#191b22", font=("Helvetica", 9), anchor="w", justify="left").pack(fill="x", padx=18, pady=(3, 16))

        tk.Label(previews, text="02  滤镜预览", fg="#f4f5f8", bg="#191b22", font=("Helvetica", 15, "bold")).pack(anchor="w", padx=16, pady=(16, 3))
        tk.Label(previews, text="原图 + 32 个已筛选滤镜 · 新旧效果交错排列", fg="#8f93a0", bg="#191b22", font=("Helvetica", 9)).pack(anchor="w", padx=16, pady=(0, 8))
        preview_wrap = tk.Frame(previews, bg="#191b22")
        preview_wrap.pack(fill="both", expand=True, padx=(10, 5), pady=(0, 10))
        self.filter_canvas = tk.Canvas(preview_wrap, bg="#191b22", highlightthickness=0)
        preview_scroll = ttk.Scrollbar(preview_wrap, orient="vertical", command=self.filter_canvas.yview)
        self.filter_grid = tk.Frame(self.filter_canvas, bg="#191b22")
        self.filter_grid.bind("<Configure>", lambda _e: self.filter_canvas.configure(scrollregion=self.filter_canvas.bbox("all")))
        self.filter_canvas.create_window((0, 0), window=self.filter_grid, anchor="nw")
        self.filter_canvas.configure(yscrollcommand=preview_scroll.set)
        self.filter_canvas.pack(side="left", fill="both", expand=True)
        preview_scroll.pack(side="right", fill="y")
        self._bind_filter_scroll(self.filter_canvas, self.filter_grid, preview_wrap)

        tk.Label(config, text="03  模式与滤镜", fg="#f4f5f8", bg="#191b22", font=("Helvetica", 15, "bold")).pack(anchor="w", padx=18, pady=(16, 8))
        mode_row = tk.Frame(config, bg="#191b22")
        mode_row.pack(fill="x", padx=18)
        for value, label in (("two", "双指模式"), ("five", "五指模式")):
            tk.Radiobutton(mode_row, text=label, variable=self.mode_var, value=value, command=self._mode_changed, indicatoron=False, bg="#2a2d37", fg="#ffffff", selectcolor="#6847f5", activebackground="#7a5cff", activeforeground="#ffffff", relief="flat", font=("Helvetica", 11, "bold"), padx=18, pady=9, cursor="hand2").pack(side="left", fill="x", expand=True, padx=(0, 5) if value == "two" else (5, 0))
        self.mode_content = tk.Frame(config, bg="#191b22")
        self.mode_content.pack(fill="both", expand=True, padx=18, pady=(10, 14))
        self._build_double_config()
        self._build_five_config()

        footer = tk.Frame(self.root, bg="#101116")
        footer.pack(fill="x", padx=26, pady=(14, 20))
        ttk.Progressbar(footer, variable=self.progress_var, maximum=100).pack(fill="x", pady=(0, 9))
        actions = tk.Frame(footer, bg="#101116")
        actions.pack(fill="x")
        tk.Label(actions, textvariable=self.status_var, fg="#d8dae0", bg="#101116", font=("Helvetica", 10)).pack(side="left")
        self.cancel_button = ColorButton(actions, text="取消", command=self.cancel, state="disabled", normal_bg="#d9475d", hover_bg="#f05b70", padx=24, pady=11)
        self.cancel_button.pack(side="right", padx=(10, 0))
        self.start_button = ColorButton(actions, text="开始处理并导出", command=self.start, state="disabled", normal_bg="#7048ff", hover_bg="#876aff", padx=28, pady=11)
        self.start_button.pack(side="right")

    def _build_double_config(self) -> None:
        self.double_frame = tk.Frame(self.mode_content, bg="#191b22")
        tk.Label(self.double_frame, text="只使用拇指与食指的交叉区域；滤镜按下方顺序循环。", fg="#9fa4b2", bg="#191b22", font=("Helvetica", 9), wraplength=460, justify="left").pack(anchor="w", pady=(2, 9))
        self._build_speed_selector(self.double_frame, self.double_speed_var)
        tk.Label(self.double_frame, text="滤镜顺序（拖动 ☰ 排序）", fg="#d8dae0", bg="#191b22", font=("Helvetica", 9, "bold")).pack(anchor="w", pady=(10, 5))
        queue_wrap = tk.Frame(self.double_frame, bg="#191b22")
        queue_wrap.pack(fill="both", expand=True)
        self.two_canvas = tk.Canvas(queue_wrap, bg="#191b22", highlightthickness=0, height=280)
        two_scroll = ttk.Scrollbar(queue_wrap, orient="vertical", command=self.two_canvas.yview)
        self.two_inner = tk.Frame(self.two_canvas, bg="#191b22")
        self.two_inner.bind("<Configure>", lambda _e: self.two_canvas.configure(scrollregion=self.two_canvas.bbox("all")))
        self.two_window = self.two_canvas.create_window((0, 0), window=self.two_inner, anchor="nw")
        self.two_canvas.bind("<Configure>", lambda event: self.two_canvas.itemconfigure(self.two_window, width=event.width))
        self.two_canvas.configure(yscrollcommand=two_scroll.set)
        self.two_canvas.pack(side="left", fill="both", expand=True)
        two_scroll.pack(side="right", fill="y")
        add_row = tk.Frame(self.double_frame, bg="#191b22")
        add_row.pack(fill="x", pady=(8, 0))
        combo = ttk.Combobox(add_row, textvariable=self.two_add_var, values=FILTER_OPTIONS, state="readonly", style="Filter.TCombobox")
        combo.pack(side="left", fill="x", expand=True)
        add_button = ColorButton(add_row, text="＋ 添加", command=self._add_two_filter, normal_bg="#168a5b", hover_bg="#22a970", padx=13, pady=7, font=("Helvetica", 9, "bold"))
        add_button.pack(side="left", padx=(8, 0))
        tk.Label(self.double_frame, text="也可点击 02 中的滤镜预览，将它添加到队尾。永不切换只使用第一个。", fg="#858a98", bg="#191b22", font=("Helvetica", 8), wraplength=460, justify="left").pack(anchor="w", pady=(6, 0))

    def _build_speed_selector(self, parent, variable: tk.StringVar) -> None:
        speed = tk.Frame(parent, bg="#191b22")
        speed.pack(fill="x")
        tk.Label(speed, text="切换速度", fg="#f4f5f8", bg="#191b22", font=("Helvetica", 10, "bold")).pack(side="left", padx=(0, 8))
        for value, label in (("1", "1秒"), ("2", "2秒"), ("3", "3秒"), ("never", "永不切换")):
            tk.Radiobutton(speed, text=label, variable=variable, value=value, indicatoron=False, bg="#2a2d37", fg="#ffffff", selectcolor="#6847f5", activebackground="#4a3a91", activeforeground="#ffffff", relief="flat", font=("Helvetica", 9, "bold"), padx=9, pady=6, cursor="hand2").pack(side="left", padx=2)

    def _build_five_config(self) -> None:
        self.five_frame = tk.Frame(self.mode_content, bg="#191b22")
        self._build_speed_selector(self.five_frame, self.five_speed_var)
        editor = tk.Frame(self.five_frame, bg="#191b22")
        editor.pack(fill="both", expand=True, pady=(9, 0))
        editor.grid_columnconfigure(0, weight=5, uniform="edit")
        editor.grid_columnconfigure(1, weight=6, uniform="edit")
        editor.grid_rowconfigure(1, weight=1)
        tk.Label(editor, text="滤镜套装（拖动 ☰ 换序）", fg="#d8dae0", bg="#191b22", font=("Helvetica", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 5))
        tk.Label(editor, text="滤镜槽", fg="#d8dae0", bg="#191b22", font=("Helvetica", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(0, 5))
        suite_wrap = tk.Frame(editor, bg="#191b22")
        suite_wrap.grid(row=1, column=0, sticky="nsew")
        self.suite_canvas = tk.Canvas(suite_wrap, bg="#191b22", highlightthickness=0)
        self.suite_scroll = MiniScrollbar(suite_wrap, command=self.suite_canvas.yview)
        self.suite_inner = tk.Frame(self.suite_canvas, bg="#191b22")
        self.suite_inner.bind("<Configure>", lambda _e: self.suite_canvas.configure(scrollregion=self.suite_canvas.bbox("all")))
        self.suite_window = self.suite_canvas.create_window((0, 0), window=self.suite_inner, anchor="nw")
        self.suite_canvas.bind("<Configure>", lambda event: self.suite_canvas.itemconfigure(self.suite_window, width=event.width))
        self.suite_canvas.configure(yscrollcommand=self.suite_scroll.set)
        self.suite_scroll.pack(side="right", fill="y", padx=(4, 0))
        self.suite_canvas.pack(side="left", fill="both", expand=True)
        self._bind_suite_scroll(suite_wrap, self.suite_canvas, self.suite_inner)
        suite_actions = tk.Frame(editor, bg="#191b22")
        suite_actions.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        self.add_suite_button = ColorButton(suite_actions, text="＋ 新增", command=self._add_suite, normal_bg="#168a5b", hover_bg="#22a970", padx=11, pady=7, font=("Helvetica", 9, "bold"))
        self.add_suite_button.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.delete_suite_button = ColorButton(suite_actions, text="删除", command=self._delete_suite, normal_bg="#b33b50", hover_bg="#d94b62", padx=11, pady=7, font=("Helvetica", 9, "bold"))
        self.delete_suite_button.pack(side="left", fill="x", expand=True, padx=(3, 0))
        slots = tk.Frame(editor, bg="#191b22")
        slots.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(10, 0))
        for index, name in enumerate(FINGER_ZONE_NAMES):
            tk.Label(slots, text=name, fg="#cfd2da", bg="#191b22", font=("Helvetica", 9, "bold")).pack(anchor="w", pady=(0 if index == 0 else 7, 3))
            combo = ttk.Combobox(slots, textvariable=self.slot_vars[index], values=FILTER_OPTIONS, state="readonly", style="Filter.TCombobox", width=20)
            combo.pack(fill="x")
            combo.bind("<<ComboboxSelected>>", lambda _event, slot=index: self._draft_slot_changed(slot))
        self.confirm_suite_button = ColorButton(slots, text="确定并更新该套装", command=self._confirm_suite, normal_bg="#168a5b", hover_bg="#22a970", padx=16, pady=9, font=("Helvetica", 10, "bold"))
        self.confirm_suite_button.pack(fill="x", pady=(14, 0))
        tk.Label(slots, text="修改下拉选项后需点击确定。", fg="#858a98", bg="#191b22", font=("Helvetica", 8)).pack(anchor="w", pady=(5, 0))

    def _draw_empty_video(self) -> None:
        self.video_canvas.delete("all")
        width, height = max(self.video_canvas.winfo_width(), 360), max(self.video_canvas.winfo_height(), 280)
        self.video_canvas.create_text(width / 2, height / 2 - 14, text="＋", fill="#73f3bc", font=("Helvetica", 38))
        self.video_canvas.create_text(width / 2, height / 2 + 32, text="点击这里上传视频", fill="#d9dbe1", font=("Helvetica", 13, "bold"))

    def _show_video_frame(self, frame: np.ndarray) -> None:
        cw, ch = max(300, self.video_canvas.winfo_width() - 4), max(220, self.video_canvas.winfo_height() - 4)
        height, width = frame.shape[:2]
        scale = min(cw / width, ch / height)
        resized = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
        self.video_preview_photo = tk.PhotoImage(data=preview_png_data(resized))
        self.video_canvas.delete("all")
        self.video_canvas.create_image(self.video_canvas.winfo_width() / 2, self.video_canvas.winfo_height() / 2, image=self.video_preview_photo)

    def _build_filter_previews(self) -> None:
        source = cv2.imread(str(resource_path("assets/fingerlens-icon.png")))
        if source is None:
            tk.Label(self.filter_grid, text="无法加载预览 Logo", fg="#ff8899", bg="#191b22").grid(row=0, column=0)
            return
        source = cv2.resize(source, (112, 112), interpolation=cv2.INTER_AREA)
        entries = [(0, "原图", source)] + [(number, FILTER_CN_NAMES[number], fashion_filter(source, 0.78, number)) for number in ACTIVE_FILTER_IDS]
        for position, (filter_id, name, image) in enumerate(entries):
            card = tk.Frame(self.filter_grid, bg="#24262f", highlightbackground="#3d414d", highlightthickness=1, cursor="hand2" if filter_id else "arrow")
            card.grid(row=position // 2, column=position % 2, padx=4, pady=4, sticky="nsew")
            photo = tk.PhotoImage(data=preview_png_data(image))
            self.filter_preview_photos.append(photo)
            image_label = tk.Label(card, image=photo, bg="#24262f")
            image_label.pack(padx=5, pady=(5, 3))
            text = name
            name_label = tk.Label(card, text=text, fg="#f2f3f6", bg="#24262f", font=("Helvetica", 8), wraplength=112)
            name_label.pack(fill="x", padx=4, pady=(0, 5))
            self._bind_filter_scroll(card, image_label, name_label)
            if filter_id:
                for widget in (card, image_label, name_label):
                    widget.bind("<Button-1>", lambda _event, number=filter_id: self._preview_filter_clicked(number))
        self.root.after_idle(lambda: self.filter_canvas.yview_moveto(0.0))

    def _bind_filter_scroll(self, *widgets) -> None:
        for widget in widgets:
            widget.bind("<MouseWheel>", self._on_filter_mousewheel)
            widget.bind("<Button-4>", self._on_filter_mousewheel)
            widget.bind("<Button-5>", self._on_filter_mousewheel)

    def _on_filter_mousewheel(self, event):
        units = scroll_units(getattr(event, "delta", 0), getattr(event, "num", None))
        if units:
            self.filter_canvas.yview_scroll(units, "units")
        return "break"

    def _preview_filter_clicked(self, filter_id: int) -> None:
        if self.mode_var.get() == "two":
            self.two_filters.append(filter_id)
            self._render_two_filter_list()
            self.two_canvas.yview_moveto(1.0)
            self.status_var.set(f"已将 {FILTER_CN_NAMES[filter_id]} 添加到双指滤镜队尾")

    def _render_two_filter_list(self) -> None:
        for child in self.two_inner.winfo_children():
            child.destroy()
        self.two_rows = []
        for index, filter_id in enumerate(self.two_filters):
            bg = "#24262f"
            row = tk.Frame(self.two_inner, bg=bg, highlightbackground="#3d414d", highlightthickness=1)
            row.pack(fill="x", padx=3, pady=3)
            handle = tk.Label(row, text="☰", fg="#73f3bc", bg=bg, font=("Helvetica", 13, "bold"), padx=7, cursor="fleur")
            handle.pack(side="left", fill="y")
            tk.Label(row, text=f"{index + 1:02d}", fg="#9fa4b2", bg=bg, font=("Helvetica", 9, "bold"), width=3).pack(side="left")
            name = tk.Label(row, text=FILTER_CN_NAMES[filter_id], fg="#ffffff", bg=bg, font=("Helvetica", 9, "bold"), anchor="w")
            name.pack(side="left", fill="x", expand=True, padx=5, pady=7)
            remove = tk.Label(row, text="删除", fg="#ff8192", bg=bg, font=("Helvetica", 8, "bold"), padx=8, cursor="hand2")
            remove.pack(side="right", fill="y")
            handle.bind("<ButtonPress-1>", lambda _event, item=index: self._two_drag_start(item))
            handle.bind("<ButtonRelease-1>", self._two_drag_release)
            remove.bind("<Button-1>", lambda _event, item=index: self._delete_two_filter(item))
            for widget in (row, handle, name, remove):
                widget.bind("<MouseWheel>", self._on_two_mousewheel)
                widget.bind("<Button-4>", self._on_two_mousewheel)
                widget.bind("<Button-5>", self._on_two_mousewheel)
            self.two_rows.append(row)

    def _add_two_filter(self) -> None:
        filter_id = FILTER_ID_BY_OPTION[self.two_add_var.get()]
        self.two_filters.append(filter_id)
        self._render_two_filter_list()
        self.two_canvas.yview_moveto(1.0)
        self.status_var.set(f"已添加 {FILTER_CN_NAMES[filter_id]}")

    def _delete_two_filter(self, index: int) -> None:
        if len(self.two_filters) <= 1:
            messagebox.showwarning(APP_NAME, "双指模式至少要保留一个滤镜。")
            return
        removed = self.two_filters.pop(index)
        self._render_two_filter_list()
        self.status_var.set(f"已删除 {FILTER_CN_NAMES[removed]}")

    def _two_drag_start(self, index: int) -> None:
        self.two_drag_index = index

    def _two_drag_release(self, event) -> None:
        source = self.two_drag_index
        if source is None:
            return
        target = 0
        for index, row in enumerate(self.two_rows):
            if event.y_root >= row.winfo_rooty() + row.winfo_height() / 2:
                target = index
        self.two_filters = reorder_items(self.two_filters, source, target)
        self.two_drag_index = None
        self._render_two_filter_list()
        self.status_var.set("双指滤镜顺序已调整")

    def _on_two_mousewheel(self, event):
        units = scroll_units(getattr(event, "delta", 0), getattr(event, "num", None))
        if units:
            self.two_canvas.yview_scroll(units, "units")
        return "break"

    def _mode_changed(self) -> None:
        self.double_frame.pack_forget()
        self.five_frame.pack_forget()
        if self.mode_var.get() == "two":
            self.double_frame.pack(fill="both", expand=True)
            message = "双指模式：按自定义滤镜顺序和切换速度循环"
        else:
            self.five_frame.pack(fill="both", expand=True)
            message = "五指模式：按左侧套装顺序和切换速度自动切换"
        if self.source:
            self.status_var.set(message)

    def _suite_summary(self, filters: tuple[int, ...]) -> str:
        return " · ".join(FILTER_CN_NAMES[number] for number in filters)

    def _render_suite_list(self) -> None:
        for child in self.suite_inner.winfo_children():
            child.destroy()
        self.suite_rows = []
        for index, filters in enumerate(self.suites):
            selected = index == self.selected_suite_index
            bg = "#4833a0" if selected else "#24262f"
            row = tk.Frame(self.suite_inner, bg=bg, highlightbackground="#755cff" if selected else "#3d414d", highlightthickness=2 if selected else 1, cursor="hand2")
            row.pack(fill="x", padx=3, pady=3)
            handle = tk.Label(row, text="☰", fg="#73f3bc", bg=bg, font=("Helvetica", 13, "bold"), padx=6, cursor="fleur")
            handle.pack(side="left", fill="y")
            text = tk.Frame(row, bg=bg)
            text.pack(side="left", fill="both", expand=True, padx=(0, 5), pady=5)
            title = tk.Label(text, text=f"套装 {index + 1:02d}", fg="#ffffff", bg=bg, font=("Helvetica", 9, "bold"), anchor="w")
            title.pack(fill="x")
            summary = tk.Label(text, text=self._suite_summary(filters), fg="#d6d8e0", bg=bg, font=("Helvetica", 7), anchor="w", justify="left", wraplength=205)
            summary.pack(fill="x", pady=(2, 0))
            for widget in (row, text, title, summary):
                widget.bind("<Button-1>", lambda _event, suite=index: self._select_suite(suite))
            self._bind_suite_scroll(row, handle, text, title, summary)
            handle.bind("<ButtonPress-1>", lambda _event, suite=index: self._suite_drag_start(suite))
            handle.bind("<ButtonRelease-1>", self._suite_drag_release)
            self.suite_rows.append(row)
        self.delete_suite_button.configure(state="normal" if len(self.suites) > 1 else "disabled")

    def _bind_suite_scroll(self, *widgets) -> None:
        for widget in widgets:
            widget.bind("<MouseWheel>", self._on_suite_mousewheel)
            widget.bind("<Button-4>", self._on_suite_mousewheel)
            widget.bind("<Button-5>", self._on_suite_mousewheel)

    def _on_suite_mousewheel(self, event):
        units = scroll_units(getattr(event, "delta", 0), getattr(event, "num", None))
        if units:
            self.suite_canvas.yview_scroll(units, "units")
        return "break"

    def _select_suite(self, index: int) -> None:
        self.selected_suite_index = index
        self.draft_filter_ids = list(self.suites[index])
        self.draft_dirty = False
        self._refresh_slot_editor()
        self._render_suite_list()

    def _refresh_slot_editor(self) -> None:
        for index, variable in enumerate(self.slot_vars):
            variable.set(self._filter_option(self.draft_filter_ids[index]))

    def _draft_slot_changed(self, index: int) -> None:
        self.draft_filter_ids[index] = FILTER_ID_BY_OPTION[self.slot_vars[index].get()]
        self.draft_dirty = True
        self.status_var.set("滤镜槽已修改，请点击“确定并更新该套装”")

    def _confirm_suite(self) -> None:
        self.suites[self.selected_suite_index] = tuple(self.draft_filter_ids)
        self.draft_dirty = False
        self._render_suite_list()
        self.status_var.set(f"套装 {self.selected_suite_index + 1:02d} 已更新")

    def _add_suite(self) -> None:
        new_suite = tuple(self.suites[self.selected_suite_index])
        self.suites.append(new_suite)
        self.selected_suite_index = len(self.suites) - 1
        self.draft_filter_ids = list(new_suite)
        self.draft_dirty = False
        self._refresh_slot_editor()
        self._render_suite_list()
        self.suite_canvas.yview_moveto(1.0)
        self.status_var.set(f"已新增套装 {self.selected_suite_index + 1:02d}，内容复制自上一套")

    def _delete_suite(self) -> None:
        if len(self.suites) <= 1:
            messagebox.showwarning(APP_NAME, "五指模式至少要保留一个滤镜套装。")
            return
        removed_index = self.selected_suite_index
        self.suites.pop(removed_index)
        self.selected_suite_index = min(removed_index, len(self.suites) - 1)
        self.draft_filter_ids = list(self.suites[self.selected_suite_index])
        self.draft_dirty = False
        self._refresh_slot_editor()
        self._render_suite_list()
        self.status_var.set(f"已删除套装 {removed_index + 1:02d}")

    def _suite_drag_start(self, index: int) -> None:
        self.suite_drag_index = index

    def _suite_drag_release(self, event) -> None:
        source = self.suite_drag_index
        if source is None:
            return
        target = 0
        for index, row in enumerate(self.suite_rows):
            if event.y_root >= row.winfo_rooty() + row.winfo_height() / 2:
                target = index
        self.suites = reorder_suites(self.suites, source, target)
        self.selected_suite_index = target
        self.draft_filter_ids = list(self.suites[target])
        self.draft_dirty = False
        self.suite_drag_index = None
        self._refresh_slot_editor()
        self._render_suite_list()
        self.status_var.set("滤镜套装顺序已调整")

    def choose_video(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        filename = filedialog.askopenfilename(title="选择要处理的视频", filetypes=[("常见视频", "*.mp4 *.mov *.m4v *.avi *.mkv *.webm *.wmv *.mpg *.mpeg"), ("所有文件", "*.*")])
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            messagebox.showwarning(APP_NAME, "这个扩展名不在常见视频列表中，仍会尝试读取。")
        try:
            width, height, fps, frames, preview = video_metadata(path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.source = path
        duration = frames / fps if frames > 0 else 0.0
        self.file_label.configure(text=path.name)
        self.detail_var.set(f"{width} × {height}  ·  {fps:.2f} FPS  ·  {duration:.1f} 秒")
        self.start_button.configure(state="normal")
        self.status_var.set("视频已就绪，请检查 03 模式与滤镜")
        try:
            self._show_video_frame(preview)
        except Exception:
            self.video_preview_photo = None
            self._draw_empty_video()

    def start(self) -> None:
        if not self.source:
            return
        if self.mode_var.get() == "five" and self.draft_dirty:
            messagebox.showwarning(APP_NAME, "当前滤镜槽尚未确定。请先点击“确定并更新该套装”。")
            return
        filename = filedialog.asksaveasfilename(title="保存处理后的视频", initialdir=str(self.source.parent), initialfile=f"{self.source.stem}_FingerLens.mp4", defaultextension=".mp4", filetypes=[("MP4 视频", "*.mp4")])
        if not filename:
            return
        destination = Path(filename)
        if destination.resolve() == self.source.resolve():
            messagebox.showerror(APP_NAME, "输出文件不能覆盖原视频，请换一个名称。")
            return
        self.destination = destination
        self.cancel_event.clear()
        self.progress_var.set(0)
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status_var.set("正在初始化手势识别…")
        source = self.source
        finger_mode = self.mode_var.get()
        two_filter_sequence = tuple(self.two_filters)
        filter_suites = tuple(self.suites)
        speed_value = self.double_speed_var.get() if finger_mode == "two" else self.five_speed_var.get()
        switch_interval = None if speed_value == "never" else float(speed_value)

        def update(progress, frame_index, total_frames, current_label, frame):
            self.events.put(("progress", progress, frame_index, total_frames, current_label, frame))

        def work() -> None:
            try:
                process_video(source, destination, finger_mode, two_filter_sequence, filter_suites, switch_interval, resource_path("models/hand_landmarker.task"), 960, self.cancel_event, update)
                self.events.put(("done", destination))
            except InterruptedError:
                self.events.put(("cancelled",))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def cancel(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status_var.set("正在安全停止并删除未完成文件…")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, progress, frame_index, total_frames, current_label, frame = event
                    self.progress_var.set(progress * 100)
                    count = f"{frame_index}/{total_frames}" if total_frames > 0 else str(frame_index)
                    self.status_var.set(f"处理中 {progress * 100:5.1f}%  ·  帧 {count}  ·  {current_label}")
                    if frame is not None:
                        self._show_video_frame(frame)
                elif event[0] == "done":
                    destination = event[1]
                    self._finish_ui()
                    self.progress_var.set(100)
                    self.status_var.set(f"完成：{destination.name}")
                    messagebox.showinfo(APP_NAME, f"视频已经处理完成：\n{destination}")
                elif event[0] == "cancelled":
                    self._finish_ui()
                    self.progress_var.set(0)
                    self.status_var.set("处理已取消，原视频没有改动")
                elif event[0] == "error":
                    self._finish_ui()
                    self.progress_var.set(0)
                    self.status_var.set("处理失败")
                    messagebox.showerror(APP_NAME, event[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _finish_ui(self) -> None:
        self.start_button.configure(state="normal" if self.source else "disabled")
        self.cancel_button.configure(state="disabled")

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "视频还在处理中。确定退出并删除未完成文件吗？"):
                return
            self.cancel_event.set()
        cv2.destroyAllWindows()
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FingerLens 上传视频处理版")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        initialize_macos_graphics()
        model = ensure_model(resource_path("models/hand_landmarker.task"))
        blank = np.zeros((180, 320, 3), dtype=np.uint8)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=blank)
        with make_landmarker(model) as landmarker:
            landmarker.detect_for_video(image, 0)
        if not find_ffmpeg():
            raise RuntimeError("FFmpeg missing")
        print("FingerLens File self-test passed")
        return 0
    root = tk.Tk()
    # Tk must create the main native window before OpenCV initializes its tiny
    # MediaPipe graphics context, otherwise macOS can assign window ownership
    # to OpenCV and leave the Tk interface hidden.
    initialize_macos_graphics()
    FingerLensFileApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
