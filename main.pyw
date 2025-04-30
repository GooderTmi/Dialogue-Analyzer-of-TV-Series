import os
import sys
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog
import sounddevice as sd
import numpy as np
from pydub import AudioSegment

# 全局变量以下几个的
prompt_file = 'prompt.txt'
file_location = ''
audio_buffer = []
buffer_lock = threading.Lock()
recording = False
stereo_mix_index = None

def find_stereo_mix():
    global stereo_mix_index
    devs = sd.query_devices()
    for i, dev in enumerate(devs):
        name = dev['name']
        if 'stereo mix' in name.lower() or '立体声混音' in name:
            stereo_mix_index = i
            return
    print("Warning: 未找到 Stereo Mix 设备，录音功能将无法使用。")

def audio_callback(indata, frames, time, status):
    if status:
        print("录音回调状态：", status, file=sys.stderr)
    # 一直往缓存里写
    with buffer_lock:
        audio_buffer.append(indata.copy())

def start_audio_stream():
    find_stereo_mix()
    if stereo_mix_index is None:
        return
    try:
        stream = sd.InputStream(samplerate=44100,
                                channels=2,
                                dtype='int16',
                                device=stereo_mix_index,
                                callback=audio_callback)
        stream.start()
    except Exception as e:
        print("启动录音流失败：", e, file=sys.stderr)

def save_buffer_to_mp3(path='record.mp3'):
    # 导出缓存到mp3
    with buffer_lock:
        if not audio_buffer:
            print("缓存为空，未能录到任何音频。")
            return False
        buf_copy = audio_buffer.copy()
    # 合并所有片段
    audio_data = np.concatenate(buf_copy, axis=0)
    raw_bytes = audio_data.tobytes()
    seg = AudioSegment(
        data=raw_bytes,
        sample_width=2,       # int16 => 2 bytes
        frame_rate=44100,
        channels=2
    )
    seg.export(path, format='mp3')
    return True

class DialogueAnalyzerApp:
    def __init__(self, master):
        self.master = master
        master.title("Dialogue Analyzer")
        
        # prompt 编辑区
        self.prompt_str = ''
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                self.prompt_str = f.read()
        except:
            self.prompt_str = ''
        self.placeholder = "Please enter your prompt..."
        self.placeholder_active = False
        
        prompt_frame = tk.Frame(master)
        prompt_frame.pack(fill='both', padx=10, pady=10, expand=True)
        
        self.text = tk.Text(prompt_frame, width=60, height=8, wrap='word', undo=True)
        self.text.pack(side='left', fill='both', expand=True)
        self.scroll = tk.Scrollbar(prompt_frame, command=self.text.yview)
        self.text.configure(yscrollcommand=self.scroll.set)
        if self.prompt_str.strip():
            self.text.insert('1.0', self.prompt_str)
            self.text.tag_remove('placeholder', '1.0', 'end')
            self.placeholder_active = False
        else:
            self._show_placeholder()
        self.text.bind("<FocusIn>", self._on_focus_in)
        self.text.bind("<FocusOut>", self._on_focus_out)
        self.text.bind("<KeyRelease>", self._on_key_release)

        self.text.bind("<KeyRelease>", lambda e: self._update_scrollbar(), add='+')
        master.after(100, self._update_scrollbar)
        
        # 并排按钮 音频 / 视频 / 录音
        btn_frame = tk.Frame(master)
        btn_frame.pack(pady=5)
        
        self.btn_audio = tk.Button(btn_frame, text='🎵', width=6, height=2,
                                   command=self.select_audio,
                                   activebackground='lightgray')
        self.btn_audio.pack(side='left', padx=5)
        
        self.btn_video = tk.Button(btn_frame, text='🎥', width=6, height=2,
                                   command=self.select_video,
                                   activebackground='lightgray')
        self.btn_video.pack(side='left', padx=5)
        
        self.btn_record = tk.Button(btn_frame, text='🎙', width=6, height=2,
                                    command=self.toggle_record)
        self.btn_record.pack(side='left', padx=5)
        self.record_normal_bg = self.btn_record.cget('bg')
        self.record_active_bg = 'lightgreen'
        
        self.analyse_btn = tk.Button(master, text='Analyse', width=40, height=2,
                                     state='disabled', fg='gray',
                                     command=self.on_analyse)
        self.analyse_btn.pack(pady=(10, 20))
        
        # 录音: 这个录音是一直有的 开始录音是清空缓冲实现的
        threading.Thread(target=start_audio_stream, daemon=True).start()
    
    def _show_placeholder(self):
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', self.placeholder, 'placeholder')
        self.text.tag_configure('placeholder', foreground='gray')
        self.placeholder_active = True
    
    def _on_focus_in(self, event):
        if self.placeholder_active:
            self.text.delete('1.0', 'end')
            self.placeholder_active = False
    
    def _on_focus_out(self, event):
        content = self.text.get('1.0', 'end-1c').strip()
        if not content:
            self._show_placeholder()
    
    def _on_key_release(self, event):
        if self.placeholder_active:
            return
        content = self.text.get('1.0', 'end-1c')
        # 保存 prompt
        try:
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            print("保存 prompt.txt 失败：", e, file=sys.stderr)
    
    def _update_scrollbar(self):
        # 根据行数决定是否显示滚动条
        vis_lines = int(self.text['height'])
        cur_lines = int(self.text.index('end-1c').split('.')[0])
        if cur_lines > vis_lines:
            if not self.scroll.winfo_ismapped():
                self.scroll.pack(side='right', fill='y')
        else:
            if self.scroll.winfo_ismapped():
                self.scroll.pack_forget()
    
    def select_audio(self):
        global file_location
        types = [
            ("Audio files", "*.wav *.mp3 *.flac *.ogg *.aac *.m4a"),
            ("All files", "*.*")
        ]
        path = filedialog.askopenfilename(title="Select an audio file", filetypes=types)
        if path:
            file_location = path
            self._update_analyse_button()
    
    def select_video(self):
        global file_location
        types = [
            ("Video files", "*.mp4 *.mov *.avi *.mkv *.flv *.wmv"),
            ("All files", "*.*")
        ]
        path = filedialog.askopenfilename(title="Select a video file", filetypes=types)
        if path:
            file_location = path
            self._update_analyse_button()
    
    def toggle_record(self):
        global recording, audio_buffer, file_location
        if not recording:
            with buffer_lock:
                audio_buffer.clear()
            recording = True
            self.btn_record.config(bg=self.record_active_bg)
        else:
            recording = False
            self.btn_record.config(bg=self.record_normal_bg)
            success = save_buffer_to_mp3('record.mp3')
            if success:
                file_location = os.path.abspath('record.mp3')
                self._update_analyse_button()
    
    def _update_analyse_button(self):
        if not file_location:
            self.analyse_btn.config(text='Analyse', state='disabled', fg='gray')
        else:
            fn = os.path.basename(file_location)
            if fn.lower() == 'record.mp3':
                txt = "Analyse recording"
            else:
                txt = f"Analyse {fn}"
            self.analyse_btn.config(text=txt, state='normal', fg='black')
    
    def on_analyse(self):
        if not file_location:
            return
        submit_py = os.path.join(os.path.dirname(__file__), 'submit_n3.pyw')
        try:
            subprocess.Popen([sys.executable, submit_py, file_location])
        except Exception as e:
            print("启动 submit.py 失败：", e, file=sys.stderr)

if __name__ == '__main__':
    root = tk.Tk()
    app = DialogueAnalyzerApp(root)
    root.mainloop()