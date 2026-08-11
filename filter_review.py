#!/usr/bin/env python3
"""Camera-based review tool for deciding which FingerLens filters to keep."""

from __future__ import annotations

import argparse
import base64
import platform
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import cv2
import numpy as np

from finger_lens_core import FILTER_NAMES, fashion_filter
from finger_lens_file import ACTIVE_FILTER_IDS, FILTER_CN_NAMES, ColorButton


APP_NAME = "FingerLens 滤镜筛选"
FILTER_GROUPS = {
    "active": tuple(ACTIVE_FILTER_IDS),
    "old": tuple(range(1, 50)),
    "new": tuple(range(50, 61)),
}
FILTER_IDS = FILTER_GROUPS["new"]


def format_review_results(decisions: dict[int, str]) -> str:
    """Create a compact Chinese result file that can be sent back for editing."""
    keep = [number for number in FILTER_IDS if decisions.get(number) == "keep"]
    drop = [number for number in FILTER_IDS if decisions.get(number) == "drop"]
    pending = [number for number in FILTER_IDS if number not in decisions]

    def line(number: int) -> str:
        return f"{number:02d}  {FILTER_CN_NAMES[number]}"

    sections = [
        "FingerLens 滤镜筛选结果",
        "",
        f"保留（{len(keep)} 个）",
        *(line(number) for number in keep),
        "",
        f"不要（{len(drop)} 个）",
        *(line(number) for number in drop),
        "",
        f"未决定（{len(pending)} 个）",
        *(line(number) for number in pending),
        "",
        "编号汇总",
        "保留：" + (", ".join(f"{number:02d}" for number in keep) or "无"),
        "不要：" + (", ".join(f"{number:02d}" for number in drop) or "无"),
        "未决定：" + (", ".join(f"{number:02d}" for number in pending) or "无"),
    ]
    return "\n".join(sections) + "\n"


def photo_data(frame: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("无法显示摄像头画面")
    return base64.b64encode(encoded.tobytes())


class FilterReviewApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1180x820")
        self.root.minsize(980, 720)
        self.root.configure(bg="#101116")
        self.capture: cv2.VideoCapture | None = None
        self.camera_index = 0
        self.running = True
        self.filter_index = 0
        self.decisions: dict[int, str] = {}
        self.photo: tk.PhotoImage | None = None
        self.last_frame: np.ndarray | None = None
        self.started_at = time.monotonic()
        self.status_var = tk.StringVar(value="正在申请摄像头权限…")
        self.filter_var = tk.StringVar()
        self.count_var = tk.StringVar()
        self.number_buttons: dict[int, tk.Label] = {}
        self._build_ui()
        self._show_filter(0)
        self.root.bind("<Left>", lambda _event: self.previous_filter())
        self.root.bind("<Right>", lambda _event: self.next_filter())
        self.root.bind("<Key-k>", lambda _event: self.mark("keep"))
        self.root.bind("<Key-K>", lambda _event: self.mark("keep"))
        self.root.bind("<Key-x>", lambda _event: self.mark("drop"))
        self.root.bind("<Key-X>", lambda _event: self.mark("drop"))
        self.root.bind("<BackSpace>", lambda _event: self.clear_decision())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(180, self.open_camera)
        self.root.after(220, self.update_frame)

    @property
    def filter_id(self) -> int:
        return FILTER_IDS[self.filter_index]

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg="#101116")
        header.pack(fill="x", padx=24, pady=(18, 12))
        tk.Label(header, text="FingerLens 滤镜筛选", fg="#f4f5f8", bg="#101116", font=("Helvetica", 23, "bold")).pack(side="left")
        if FILTER_IDS == FILTER_GROUPS["active"]:
            group_text = "正式应用现存的 26 个滤镜"
        elif FILTER_IDS == FILTER_GROUPS["old"]:
            group_text = "全部旧滤镜 01–49"
        else:
            group_text = "新增候选 50–60"
        tk.Label(header, text=f"摄像头实时预览 · {group_text}", fg="#73f3bc", bg="#101116", font=("Helvetica", 11)).pack(side="left", padx=14, pady=(7, 0))
        tk.Label(header, textvariable=self.status_var, fg="#a7aab4", bg="#101116", font=("Helvetica", 10)).pack(side="right", pady=(7, 0))

        body = tk.Frame(self.root, bg="#101116")
        body.pack(fill="both", expand=True, padx=24)
        body.grid_columnconfigure(0, weight=8)
        body.grid_columnconfigure(1, weight=3)
        body.grid_rowconfigure(0, weight=1)

        preview_card = tk.Frame(body, bg="#191b22", highlightbackground="#30333d", highlightthickness=1)
        preview_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.video_canvas = tk.Canvas(preview_card, bg="#08090c", highlightthickness=0)
        self.video_canvas.pack(fill="both", expand=True, padx=14, pady=14)
        self.video_canvas.create_text(400, 280, text="正在打开摄像头…", fill="#9fa4b2", font=("Helvetica", 15, "bold"), tags="placeholder")

        controls = tk.Frame(body, bg="#191b22", highlightbackground="#30333d", highlightthickness=1)
        controls.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        tk.Label(controls, text="当前滤镜", fg="#9fa4b2", bg="#191b22", font=("Helvetica", 10, "bold")).pack(anchor="w", padx=16, pady=(16, 2))
        tk.Label(controls, textvariable=self.filter_var, fg="#ffffff", bg="#191b22", font=("Helvetica", 20, "bold"), wraplength=280, justify="left").pack(anchor="w", padx=16)
        self.decision_label = tk.Label(controls, text="未决定", fg="#d0d3db", bg="#30333d", font=("Helvetica", 11, "bold"), padx=12, pady=6)
        self.decision_label.pack(anchor="w", padx=16, pady=(9, 12))

        decision_row = tk.Frame(controls, bg="#191b22")
        decision_row.pack(fill="x", padx=16)
        keep = ColorButton(decision_row, text="保留  K", command=lambda: self.mark("keep"), normal_bg="#168a5b", hover_bg="#22a970", padx=18, pady=10, font=("Helvetica", 11, "bold"))
        keep.pack(side="left", fill="x", expand=True, padx=(0, 4))
        drop = ColorButton(decision_row, text="不要  X", command=lambda: self.mark("drop"), normal_bg="#b33b50", hover_bg="#d94b62", padx=18, pady=10, font=("Helvetica", 11, "bold"))
        drop.pack(side="left", fill="x", expand=True, padx=(4, 0))

        nav = tk.Frame(controls, bg="#191b22")
        nav.pack(fill="x", padx=16, pady=(9, 4))
        previous = ColorButton(nav, text="← 上一个", command=self.previous_filter, normal_bg="#3a3e4a", hover_bg="#505565", padx=12, pady=8, font=("Helvetica", 9, "bold"))
        previous.pack(side="left", fill="x", expand=True, padx=(0, 3))
        clear = ColorButton(nav, text="清除判断", command=self.clear_decision, normal_bg="#5a4b34", hover_bg="#756143", padx=10, pady=8, font=("Helvetica", 9, "bold"))
        clear.pack(side="left", fill="x", expand=True, padx=3)
        following = ColorButton(nav, text="下一个 →", command=self.next_filter, normal_bg="#3a3e4a", hover_bg="#505565", padx=12, pady=8, font=("Helvetica", 9, "bold"))
        following.pack(side="left", fill="x", expand=True, padx=(3, 0))

        tk.Label(controls, text="点击编号可直接跳转", fg="#9fa4b2", bg="#191b22", font=("Helvetica", 9, "bold")).pack(anchor="w", padx=16, pady=(10, 5))
        number_grid = tk.Frame(controls, bg="#191b22")
        number_grid.pack(fill="x", padx=14)
        for position, filter_id in enumerate(FILTER_IDS):
            button = tk.Label(number_grid, text=f"{filter_id:02d}", fg="#ffffff", bg="#30333d", font=("Helvetica", 8, "bold"), width=3, pady=4, cursor="hand2")
            button.grid(row=position // 7, column=position % 7, padx=2, pady=2, sticky="ew")
            button.bind("<Button-1>", lambda _event, index=position: self._show_filter(index))
            self.number_buttons[filter_id] = button
        for column in range(7):
            number_grid.grid_columnconfigure(column, weight=1)

        tk.Label(controls, textvariable=self.count_var, fg="#d8dae0", bg="#191b22", font=("Helvetica", 9)).pack(anchor="w", padx=16, pady=(10, 7))
        reopen = ColorButton(controls, text="重新打开摄像头", command=self.reopen_camera, normal_bg="#3a3e4a", hover_bg="#505565", padx=14, pady=8, font=("Helvetica", 9, "bold"))
        reopen.pack(fill="x", padx=16, pady=(0, 7))
        export = ColorButton(controls, text="导出筛选结果", command=self.export_results, normal_bg="#7048ff", hover_bg="#876aff", padx=18, pady=10, font=("Helvetica", 11, "bold"))
        export.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(controls, text="快捷键：←/→ 切换，K 保留，X 不要，退格清除。", fg="#858a98", bg="#191b22", font=("Helvetica", 8), wraplength=280, justify="left").pack(anchor="w", padx=16, pady=(0, 14))

    def open_camera(self) -> None:
        self.release_camera()
        backend = cv2.CAP_AVFOUNDATION if platform.system() == "Darwin" else cv2.CAP_ANY
        capture = cv2.VideoCapture(self.camera_index, backend)
        if not capture.isOpened() and backend != cv2.CAP_ANY:
            capture.release()
            capture = cv2.VideoCapture(self.camera_index)
        if not capture.isOpened():
            capture.release()
            self.capture = None
            self.status_var.set("摄像头不可用")
            self._show_camera_error()
            return
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        capture.set(cv2.CAP_PROP_FPS, 30)
        self.capture = capture
        self.status_var.set("摄像头已连接 · 画面不会上传")

    def reopen_camera(self) -> None:
        self.status_var.set("正在重新打开摄像头…")
        self.root.after(50, self.open_camera)

    def release_camera(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def _show_camera_error(self) -> None:
        self.video_canvas.delete("all")
        width = max(500, self.video_canvas.winfo_width())
        height = max(380, self.video_canvas.winfo_height())
        self.video_canvas.create_text(width / 2, height / 2 - 20, text="无法打开摄像头", fill="#ff8192", font=("Helvetica", 18, "bold"))
        self.video_canvas.create_text(width / 2, height / 2 + 25, text="请在系统设置 → 隐私与安全性 → 摄像头中允许此应用，然后点击“重新打开摄像头”。", fill="#cfd2da", font=("Helvetica", 11), width=520)

    def update_frame(self) -> None:
        if not self.running:
            return
        if self.capture is not None:
            ok, frame = self.capture.read()
            if ok and frame is not None:
                frame = cv2.flip(frame, 1)
                if frame.shape[1] > 960:
                    scale = 960 / frame.shape[1]
                    frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                self.last_frame = frame
                phase = (time.monotonic() - self.started_at) * 2.2
                filtered = fashion_filter(frame, phase, self.filter_id)
                self._display_frame(filtered)
        self.root.after(42, self.update_frame)

    def _display_frame(self, frame: np.ndarray) -> None:
        canvas_width = max(400, self.video_canvas.winfo_width())
        canvas_height = max(300, self.video_canvas.winfo_height())
        scale = min(canvas_width / frame.shape[1], canvas_height / frame.shape[0])
        shown = cv2.resize(frame, (max(1, int(frame.shape[1] * scale)), max(1, int(frame.shape[0] * scale))), interpolation=cv2.INTER_AREA)
        self.photo = tk.PhotoImage(data=photo_data(shown))
        self.video_canvas.delete("all")
        self.video_canvas.create_image(canvas_width / 2, canvas_height / 2, image=self.photo)
        self.video_canvas.create_rectangle(18, 18, 142, 66, fill="#101116", outline="#9a82ff", width=2)
        self.video_canvas.create_text(80, 42, text=f"滤镜 {self.filter_id:02d}", fill="#ffffff", font=("Helvetica", 17, "bold"))

    def _show_filter(self, index: int) -> None:
        self.filter_index = max(0, min(len(FILTER_IDS) - 1, index))
        filter_id = self.filter_id
        self.filter_var.set(f"{filter_id:02d}  {FILTER_CN_NAMES[filter_id]}")
        decision = self.decisions.get(filter_id)
        if decision == "keep":
            self.decision_label.configure(text="✓ 保留", bg="#168a5b", fg="#ffffff")
        elif decision == "drop":
            self.decision_label.configure(text="× 不要", bg="#b33b50", fg="#ffffff")
        else:
            self.decision_label.configure(text="未决定", bg="#30333d", fg="#d0d3db")
        self._refresh_numbers()

    def _refresh_numbers(self) -> None:
        for filter_id, button in self.number_buttons.items():
            if filter_id == self.filter_id:
                bg = "#7048ff"
            elif self.decisions.get(filter_id) == "keep":
                bg = "#168a5b"
            elif self.decisions.get(filter_id) == "drop":
                bg = "#9c3447"
            else:
                bg = "#30333d"
            button.configure(bg=bg)
        keep = sum(value == "keep" for value in self.decisions.values())
        drop = sum(value == "drop" for value in self.decisions.values())
        self.count_var.set(f"已判断 {keep + drop}/{len(FILTER_IDS)}  ·  保留 {keep}  ·  不要 {drop}")

    def previous_filter(self) -> None:
        self._show_filter((self.filter_index - 1) % len(FILTER_IDS))

    def next_filter(self) -> None:
        self._show_filter((self.filter_index + 1) % len(FILTER_IDS))

    def mark(self, decision: str) -> None:
        self.decisions[self.filter_id] = decision
        if self.filter_index < len(FILTER_IDS) - 1:
            self._show_filter(self.filter_index + 1)
        else:
            self._show_filter(self.filter_index)
            messagebox.showinfo(APP_NAME, "已经看到最后一个滤镜。可以回看修改，或导出筛选结果。")

    def clear_decision(self) -> None:
        self.decisions.pop(self.filter_id, None)
        self._show_filter(self.filter_index)

    def export_results(self) -> None:
        filename = filedialog.asksaveasfilename(
            title="保存滤镜筛选结果",
            initialfile=(
                "FingerLens_现存滤镜重新筛选结果.txt"
                if FILTER_IDS == FILTER_GROUPS["active"]
                else "FingerLens_全部旧滤镜筛选结果.txt"
                if FILTER_IDS == FILTER_GROUPS["old"]
                else "FingerLens_新增滤镜筛选结果.txt"
            ),
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt")],
        )
        if not filename:
            return
        Path(filename).write_text(format_review_results(self.decisions), encoding="utf-8")
        self.status_var.set(f"结果已保存：{Path(filename).name}")
        messagebox.showinfo(APP_NAME, f"筛选结果已保存：\n{filename}\n\n把这个文件发回来，我就可以按你的选择精简滤镜。")

    def close(self) -> None:
        self.running = False
        self.release_camera()
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FingerLens 摄像头滤镜筛选")
    parser.add_argument("--group", choices=tuple(FILTER_GROUPS), default="new")
    return parser.parse_args()


def main() -> int:
    global FILTER_IDS
    FILTER_IDS = FILTER_GROUPS[parse_args().group]
    root = tk.Tk()
    FilterReviewApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
