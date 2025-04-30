#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import threading
import subprocess
import base64
import re
import random
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont

import openai
from dotenv import load_dotenv

def create_client():
    load_dotenv()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "Please set OPENAI_API_KEY in your environment or .env file."
        )
    return openai.OpenAI(api_key=key)

def load_settings(key):
    try:
        with open('settings.txt', 'r', encoding='utf-8') as f:
            for line in f:
                clean_line = ''.join(line.split())
                if clean_line.startswith(f"{key}="):
                    return clean_line[len(key)+1:]
    except FileNotFoundError:
        raise FileNotFoundError('settings.txt not found')
    raise ValueError(f'{key} not found in settings.txt')


class DialogueAnalyzerApp:
    SPEAKER_PATTERN = re.compile(r'^(Man|Woman|Boy|Girl)\d+$')

    def __init__(self, master, file_location):
        self.master = master
        master.title("Dialogue Analyzer")
        sw, sh = master.winfo_screenwidth(), master.winfo_screenheight()
        w, h = int(sw * 0.5), int(sh * 0.8)
        x, y = (sw - w) // 2, (sh - h) // 2
        master.geometry(f"{w}x{h}+{x}+{y}")
        master.resizable(False, False)  # 禁用缩放、最大化

        self.name_font = tkfont.Font(family="Helvetica", size=10, weight="bold")
        self.msg_font  = tkfont.Font(family="Helvetica", size=10)

        self.PAD_X      = 8
        self.PAD_Y      = 6
        self.AVATAR_GAP = 6

        # 用三个数组分别记录：每行起始 y、每行高度、每行对应的 canvas item ids
        self.line_positions = []
        self.line_heights   = []
        self.line_items     = []

        self.canvas = tk.Canvas(master, bg="white")
        self.canvas.pack(fill="both", expand=True)

        # 只绑到 canvas 上就够了
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)
        self.can_scroll = False

        self.analysis_text = ""
        self.speaker_colors = {}

        t = threading.Thread(
            target=self._worker, args=(file_location,), daemon=True
        )
        t.start()

    def _on_mousewheel(self, event):
        if not self.can_scroll:
            return "break"
        if hasattr(event, "delta") and event.delta:
            move = -1 if event.delta > 0 else 1
        else:
            move = -1 if event.num == 4 else (1 if event.num == 5 else 0)
        lo, hi = self.canvas.yview()
        if (lo <= 0 and move < 0) or (hi >= 1 and move > 0):
            return "break"
        self.canvas.yview_scroll(move, "units")
        return "break"

    def _worker(self, file_location):
        try:
            self._convert_to_mp3(file_location)
            transcript = self._speech_to_text("input.mp3")
            self._generate_analysis(transcript)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.analysis_text = f"Error during processing:\n{e}\n{tb}"
            self.master.after(0, self._redraw)

    def _convert_to_mp3(self, src_path):
        dest = "input.mp3"
        base_dir = os.path.abspath(os.path.dirname(__file__))
        ffmpeg_exe = os.path.join(base_dir, "ffmpeg.exe")
        cmd = [
            ffmpeg_exe, "-y",
            "-i", src_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ac", "2",
            "-ar", "44100",
            dest
        ]
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.run(cmd, check=True, **kwargs)

    def _speech_to_text(self, input_file_path):
        client = create_client()
        with open(input_file_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=f
            )
        return response.text

    def _generate_analysis(self, transcript):
        extra = ""
        p = Path("prompt.txt")
        if p.exists():
            txt = p.read_text(encoding="utf-8").strip()
            if txt:
                extra = "\nBelow are additional user instructions:\n" + txt

        dmsg = (
            "You are given an original English audio segment and a corresponding transcript"
            " (which may be incomplete or contain errors). Your tasks:\n\n"
            "1) Directly produce a fully corrected English dialogue with speaker labels. Each line must start"
            " with one of: Man#, Woman#, Boy#, Girl# (e.g., Man1, Woman2), followed by a colon and a space,"
            " then the utterance. Determine gender and age (Man vs Woman vs Boy vs Girl) from the speaker’s voice."
            " If there are multiple speakers of the same category with distinct voices, assign different numbers"
            " (e.g., Man1, Man2).\n\n"
            "2) 在所有对话行之后，提供一个中文的关于以上对话的理解。不仅需要对总体含义进行简述，而且还要对存在的英文难点进行分析。你可以在解释中引用英文原文。"
            + extra
        )

        with open("input.mp3", "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")

        messages = [
            {"role": "developer", "content": dmsg},
            {
                "role": "user",
                "content": [
                    {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "mp3"}},
                    {"type": "text",  "text": transcript}
                ]
            }
        ]

        client = create_client()
        stream = client.chat.completions.create(
            model="gpt-4o-audio-preview-2024-12-17",
            stream=True,
            temperature = float(load_settings("temperature")),
            messages=messages
        )

        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                self.analysis_text += delta
                self.master.after(0, self._redraw)

        if not self.analysis_text.endswith("\n"):
            self.analysis_text += "\n"
            self.master.after(0, self._redraw)

    def _redraw(self):
        """
        只更新最后两行的布局与绘制，不重算全部行。
        """
        self.master.update_idletasks()
        cw = self.canvas.winfo_width() - 15 #这里是特殊处理!!
        PAD_X, PAD_Y, AVATAR_GAP = self.PAD_X, self.PAD_Y, self.AVATAR_GAP
        lines = self.analysis_text.split("\n")
        n = len(lines)

        # 用来计算第 i 行应有的高度（气泡高度 + PAD_Y）
        def compute_h(i):
            line = lines[i]
            if not line.strip():
                return PAD_Y
            m = re.match(r"^([^:]+):\s*(.*)$", line)
            if m and self.SPEAKER_PATTERN.match(m.group(1).strip()):
                speaker = m.group(1).strip()
                text = m.group(2)
                avatar_h = self.name_font.metrics("linespace") + 2 * PAD_Y
                name_w = self.name_font.measure(speaker)
                max_tw = cw - name_w - 4*PAD_X - AVATAR_GAP
                wrapped = self._wrap_char(text, self.msg_font, max_tw)
                line_h = self.msg_font.metrics("linespace")
                bubble_h = line_h * len(wrapped) + 2 * PAD_Y
                return max(avatar_h, bubble_h) + PAD_Y
            else:
                txt = line.strip()
                max_tw = cw - 2 * PAD_X
                wrapped = self._wrap_char(txt, self.msg_font, max_tw)
                line_h = self.msg_font.metrics("linespace")
                bubble_h = line_h * len(wrapped) + 2 * PAD_Y
                return bubble_h + PAD_Y

        # 1) 拓展三个数组到当前行数
        prev = len(self.line_positions)
        if n > prev:
            self.line_positions += [0] * (n - prev)
            self.line_heights   += [0] * (n - prev)
            self.line_items     += [[]] * (n - prev)

        # 2) 确定要重绘的行索引（最后两行）
        if n == 0:
            to_draw = []
        elif n == 1:
            to_draw = [0]
        else:
            to_draw = [n-2, n-1]

        # 3) 先更新高度和位置（按升序），保证后一行位置正确
        for i in sorted(to_draw):
            h_i = compute_h(i)
            self.line_heights[i] = h_i
            if i == 0:
                self.line_positions[i] = PAD_Y
            else:
                self.line_positions[i] = self.line_positions[i-1] + self.line_heights[i-1]

        # 4) 删除旧的 item，清空记录
        for i in to_draw:
            for it in self.line_items[i]:
                self.canvas.delete(it)
            self.line_items[i] = []

        # 5) 绘制这几行，并把所有新 item id 收集到 self.line_items[i]
        for i in to_draw:
            if i < 0 or i >= n:
                continue
            y = self.line_positions[i]
            line = lines[i]
            if not line.strip():
                continue

            m = re.match(r"^([^:]+):\s*(.*)$", line)
            ids = []
            if m and self.SPEAKER_PATTERN.match(m.group(1).strip()):
                # 对话行
                speaker, text = m.group(1).strip(), m.group(2)
                color = self._get_speaker_color(speaker)

                # 名字泡泡
                name_w = self.name_font.measure(speaker)
                avatar_w = name_w + 2 * PAD_X
                avatar_h = self.name_font.metrics("linespace") + 2 * PAD_Y
                ax1, ay1 = PAD_X, y
                ax2, ay2 = ax1 + avatar_w, ay1 + avatar_h
                ids.append(self._draw_rounded_rect(ax1, ay1, ax2, ay2,
                                                  r=8, fill=color, outline=""))
                ids.append(self.canvas.create_text(
                    ax1 + PAD_X, ay1 + PAD_Y,
                    anchor="nw", text=speaker,
                    font=self.name_font, fill="black"
                ))

                # 文本泡泡
                bx1 = ax2 + AVATAR_GAP
                max_tw = cw - bx1 - PAD_X
                wrapped = self._wrap_char(text, self.msg_font, max_tw)
                line_h = self.msg_font.metrics("linespace")
                bubble_w = max(self.msg_font.measure(t) for t in wrapped) + 2 * PAD_X
                bubble_h = line_h * len(wrapped) + 2 * PAD_Y
                bx2, by1 = bx1 + bubble_w, y
                by2 = y + bubble_h
                ids.append(self._draw_rounded_rect(bx1, by1, bx2, by2,
                                                  r=8, fill=color, outline=""))
                for idx, sub in enumerate(wrapped):
                    ids.append(self.canvas.create_text(
                        bx1 + PAD_X,
                        by1 + PAD_Y + idx * line_h,
                        anchor="nw",
                        text=sub,
                        font=self.msg_font,
                        fill="black"
                    ))

            else:
                # 解释内容
                txt = line.strip()
                ex1 = PAD_X
                max_tw = cw - 2 * PAD_X
                wrapped = self._wrap_char(txt, self.msg_font, max_tw)
                line_h = self.msg_font.metrics("linespace")
                bubble_w = max(self.msg_font.measure(t) for t in wrapped) + 2 * PAD_X
                bubble_h = line_h * len(wrapped) + 2 * PAD_Y
                ex2, ey1 = ex1 + bubble_w, y
                ey2 = y + bubble_h
                ids.append(self._draw_rounded_rect(ex1, ey1, ex2, ey2,
                                                  r=8, fill="#f0f0f0", outline=""))
                for idx, sub in enumerate(wrapped):
                    ids.append(self.canvas.create_text(
                        ex1 + PAD_X,
                        ey1 + PAD_Y + idx * line_h,
                        anchor="nw",
                        text=sub,
                        font=self.msg_font,
                        fill="black"
                    ))

            self.line_items[i] = ids

        # 6) 更新滚动区域
        total_h = 0
        if self.line_positions:
            total_h = self.line_positions[-1] + self.line_heights[-1]
        self.canvas.configure(scrollregion=(0, 0, cw, total_h))
        self.can_scroll = (total_h > self.canvas.winfo_height())

    def _wrap_char(self, text, font, max_width):
        lines = []
        cur = ""
        for ch in text:
            if font.measure(cur + ch) <= max_width:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
        return lines

    def _get_speaker_color(self, speaker):
        if speaker in self.speaker_colors:
            return self.speaker_colors[speaker]
        low = speaker.lower()
        if low.startswith("man") or low.startswith("boy"):
            r, g, b = (random.randint(150,200),
                       random.randint(180,230),
                       random.randint(220,255))
        else:
            r, g, b = (random.randint(220,255),
                       random.randint(150,200),
                       random.randint(170,220))
        col = f"#{r:02x}{g:02x}{b:02x}"
        self.speaker_colors[speaker] = col
        return col

    def _draw_rounded_rect(self, x1, y1, x2, y2, r=8, **kwargs):
        pts = [
            x1+r, y1,
            x2-r, y1,
            x2,   y1,
            x2,   y1+r,
            x2,   y2-r,
            x2,   y2,
            x2-r, y2,
            x1+r, y2,
            x1,   y2,
            x1,   y2-r,
            x1,   y1+r,
            x1,   y1,
        ]
        return self.canvas.create_polygon(pts, smooth=True, **kwargs)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python dialogue_analyzer.py <file_location>")
        sys.exit(1)
    root = tk.Tk()
    app = DialogueAnalyzerApp(root, sys.argv[1])
    root.mainloop()