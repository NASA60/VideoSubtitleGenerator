import os
import sys
import json
import wave
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import imageio_ffmpeg as ffmpeg
import vosk
from deep_translator import GoogleTranslator
from tqdm import tqdm
import datetime
import requests
import shutil
import zipfile
import uuid
import time
import tempfile
import re


# --- CONFIGURATION ---
MODEL_URLS = {
    "small": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    "medium": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip",
    "large": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip"
}

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, 'frozen', False):
    PROJECT_ROOT = os.path.dirname(sys.executable)

LOCAL_MODELS_DIR = os.path.join(PROJECT_ROOT, "models")

# --- HELPER FUNCTIONS ---
def get_target_download_path(model_type):
    return os.path.join(LOCAL_MODELS_DIR, model_type)

def validate_model_path(path):
    if not os.path.exists(path): return False
    if os.path.exists(os.path.join(path, "conf")): return True
    # Check subdirectories
    for d in os.listdir(path):
        sub_path = os.path.join(path, d)
        if os.path.isdir(sub_path) and os.path.exists(os.path.join(sub_path, "conf")): return True
    return False

def is_model_installed(model_type):
    path = get_target_download_path(model_type)
    return validate_model_path(path)

def get_installed_model_path(model_type_or_path):
    # If input is a full path, check it directly
    if os.path.exists(model_type_or_path):
        target_path = model_type_or_path
    else:
        # If input is a key (small, medium), get the path
        target_path = get_target_download_path(model_type_or_path)

    if not os.path.exists(target_path): return None

    # Check if 'conf' is directly here
    if os.path.exists(os.path.join(target_path, "conf")): return target_path

    # Check subdirectories
    for d in os.listdir(target_path):
        sub_path = os.path.join(target_path, d)
        if os.path.isdir(sub_path) and os.path.exists(os.path.join(sub_path, "conf")):
            return sub_path
    return None

# --- MODEL MANAGER GUI ---
class ModelManagerGUI:
    def __init__(self, parent, on_close_callback):
        self.window = tk.Toplevel(parent)
        self.window.title("Model Manager")
        self.window.geometry("650x500")
        self.on_close_callback = on_close_callback
        
        self.window.transient(parent)
        self.window.grab_set()
        
        tk.Label(self.window, text="Manage Recognition Models", font=("Segoe UI", 14, "bold")).pack(pady=20)
        
        self.content_frame = tk.Frame(self.window)
        self.content_frame.pack(fill='both', expand=True, padx=20)

        # Header
        header = tk.Frame(self.content_frame)
        header.pack(fill='x', pady=(0, 10))
        tk.Label(header, text="Model", font=("Segoe UI", 10, "bold"), width=15, anchor="w").pack(side='left')
        tk.Label(header, text="Description", font=("Segoe UI", 10, "bold"), width=25, anchor="w").pack(side='left')
        tk.Label(header, text="Status", font=("Segoe UI", 10, "bold"), width=15, anchor="w").pack(side='left')
        
        ttk.Separator(self.content_frame, orient='horizontal').pack(fill='x', pady=(0, 10))

        self.rows_frame = tk.Frame(self.content_frame)
        self.rows_frame.pack(fill='both', expand=True)
        self.row_widgets = {} 

        self.create_row("Small (~50 MB)", "small", "Fast, Low Accuracy")
        self.create_row("Medium (~128 MB)", "medium", "Balanced (Best)")
        self.create_row("Large (~1.8 GB)", "large", "Max Accuracy")
        
        # Global Progress Bar (at bottom)
        self.progress_frame = tk.Frame(self.window)
        self.progress_frame.pack(fill='x', padx=20, pady=20)
        
        self.lbl_progress = tk.Label(self.progress_frame, text="Ready", font=("Segoe UI", 9))
        self.lbl_progress.pack(anchor='w')
        
        self.progress_bar = ttk.Progressbar(self.progress_frame, mode='determinate')
        self.progress_bar.pack(fill='x', pady=5)

        ttk.Button(self.window, text="Close", command=self.close_window).pack(pady=10)

    def create_row(self, title, model_key, desc):
        row = tk.Frame(self.rows_frame)
        row.pack(fill='x', pady=8)
        
        tk.Label(row, text=title, font=("Segoe UI", 10), width=15, anchor="w").pack(side='left')
        tk.Label(row, text=desc, font=("Segoe UI", 9), fg="gray", width=25, anchor="w").pack(side='left')
        
        status_lbl = tk.Label(row, text="Checking...", font=("Segoe UI", 9, "bold"), width=15, anchor="w")
        status_lbl.pack(side='left')
        
        btn = ttk.Button(row, text="Action", command=lambda: self.start_download(model_key))
        btn.pack(side='left', padx=10)
        
        self.row_widgets[model_key] = {"status": status_lbl, "btn": btn}
        self.update_row_status(model_key)

    def update_row_status(self, model_key):
        widgets = self.row_widgets[model_key]
        
        installed = is_model_installed(model_key)
        
        if installed:
            widgets["status"].config(text="Installed", fg="green")
            widgets["btn"].config(text="Re-Download", state="normal")
        else:
            widgets["status"].config(text="Not Installed", fg="red")
            widgets["btn"].config(text="Download", state="normal")

    def start_download(self, model_key):
        for key in self.row_widgets:
            self.row_widgets[key]["btn"].config(state="disabled")
        
        self.progress_bar['value'] = 0
        self.lbl_progress.config(text=f"Starting download for {model_key}...")
        
        threading.Thread(target=self.run_download, args=(model_key,), daemon=True).start()

    def run_download(self, model_key):
        try:
            url = MODEL_URLS[model_key]
            target_dir = get_target_download_path(model_key)
            os.makedirs(target_dir, exist_ok=True)
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            session = requests.Session()
            zip_path = "temp_model.zip"
            
            resume_header = headers.copy(); mode = 'wb'; initial_pos = 0
            if os.path.exists(zip_path):
                initial_pos = os.path.getsize(zip_path)
                if initial_pos > 1024 * 1024: 
                    resume_header['Range'] = f'bytes={initial_pos}-'
                    mode = 'ab'
                else:
                    initial_pos = 0

            self.update_label("Connecting...")
            try:
                response = session.get(url, stream=True, timeout=60, headers=resume_header)
            except requests.exceptions.RequestException as e:
                raise Exception(f"Connection Failed: {e}")
            
            if response.status_code == 416: 
                total_size = initial_pos
            elif response.status_code in [200, 206]:
                content_length = int(response.headers.get('content-length', 0))
                
                if response.status_code == 200:
                    if initial_pos > 0: self.update_label("Resuming failed, restarting...")
                    total_size = content_length
                    initial_pos = 0
                    mode = 'wb'
                else:
                    total_size = content_length + initial_pos
                
                self.update_label(f"Downloading {model_key}...")
                
                with open(zip_path, mode) as file:
                    for data in response.iter_content(chunk_size=1024 * 512):
                        if not data: break
                        size = file.write(data)
                        initial_pos += size
                        self.update_progress((initial_pos / total_size) * 100 if total_size else 0, initial_pos, total_size)
            else:
                raise Exception(f"HTTP Error: {response.status_code}")

            self.update_label("Verifying & Extracting...")
            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    if zip_ref.testzip() is not None:
                        raise zipfile.BadZipFile("File is corrupted")
                        
                    zip_ref.extractall("temp_extract")
                    
                    extracted_root = zip_ref.namelist()[0].split('/')[0]
                    source_path = os.path.join("temp_extract", extracted_root)
                    
                    check_file = "conf" # Vosk models
                    
                    final_source = None
                    if os.path.isdir(source_path) and os.path.exists(os.path.join(source_path, check_file)):
                        final_source = source_path
                    else:
                        if os.path.isdir(source_path):
                            for d in os.listdir(source_path):
                                sub = os.path.join(source_path, d)
                                if os.path.isdir(sub) and os.path.exists(os.path.join(sub, check_file)):
                                    final_source = sub; break
                    
                    if not final_source: final_source = source_path

                    if os.path.exists(target_dir): shutil.rmtree(target_dir)
                    shutil.move(final_source, target_dir)
                    shutil.rmtree("temp_extract")
                
                os.remove(zip_path)
                self.update_label(f"Success! {model_key} installed.")
                self.window.after(0, lambda: self.finish_download(model_key))

            except zipfile.BadZipFile:
                os.remove(zip_path)
                raise Exception("Download corrupted. Please try again.")

        except Exception as e:
            self.update_label(f"Error: {str(e)}")
            self.window.after(0, lambda: messagebox.showerror("Download Error", str(e)))
            self.window.after(0, self.reset_buttons)

    def update_progress(self, perc, current, total):
        self.window.after(0, lambda: self._update_ui_progress(perc, current, total))

    def _update_ui_progress(self, perc, current, total):
        self.progress_bar['value'] = perc
        current_mb = current / (1024*1024)
        total_mb = total / (1024*1024)
        self.lbl_progress.config(text=f"{current_mb:.1f} MB / {total_mb:.1f} MB ({int(perc)}%)")

    def update_label(self, text):
        self.window.after(0, lambda: self.lbl_progress.config(text=text))

    def finish_download(self, model_key):
        self.update_row_status(model_key)
        self.reset_buttons()
        if self.on_close_callback: self.on_close_callback()

    def reset_buttons(self):
        for key in self.row_widgets:
            self.update_row_status(key)

    def close_window(self):
        self.window.destroy()
        if self.on_close_callback: self.on_close_callback()

# --- GUI: AUDIO SELECTION ---
class AudioSelectorGUI:
    def __init__(self):
        self.device_id = None
        self.root = tk.Tk()
        self.root.title("Select Audio Source")
        self.root.geometry("500x450")
        self.root.eval('tk::PlaceWindow . center')
        
        tk.Label(self.root, text="Select Audio Source (Cable Output / Stereo Mix):", font=("Segoe UI", 10, "bold")).pack(pady=10)
        
        frame = tk.Frame(self.root)
        frame.pack(fill='both', expand=True, padx=10)
        
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side='right', fill='y')
        
        self.listbox = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Consolas", 9))
        self.listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.listbox.yview)

        self.devices = sd.query_devices()
        for i, dev in enumerate(self.devices):
            if dev['max_input_channels'] > 0:
                self.listbox.insert(tk.END, f"[{i}] {dev['name']}")

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=15)

        ttk.Button(btn_frame, text="Start Translator", command=self.confirm).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Help & Setup Guide (راهنما)", command=self.show_help).pack(side='left', padx=5)
        
        self.root.mainloop()

    def confirm(self):
        selection = self.listbox.curselection()
        if selection:
            text = self.listbox.get(selection[0])
            self.device_id = int(text.split(']')[0].replace('[', ''))
            self.root.destroy()
        else:
            messagebox.showwarning("Warning", "Select a device.")

    def show_help(self):
        HelpGUI(self.root)

# --- MAIN APP ---
class SubtitleGenGUI:
    def __init__(self, master=None):
        if master:
            self.root = master
        else:
            try:
                from tkinterdnd2 import TkinterDnD
                self.root = TkinterDnD.Tk()
            except ImportError:
                self.root = tk.Tk()
        
        self.root.title("Video Subtitle Generator")
        self.root.geometry("700x650")
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', font=('Segoe UI', 10), borderwidth=1)
        style.configure('Accent.TButton', background='#007acc', foreground='white', font=('Segoe UI', 11, 'bold'))
        style.map('Accent.TButton', background=[('active', '#005f9e')])
        style.configure('TCombobox', arrowcolor="gray")
        style.configure("TProgressbar", background='#007acc')

        # Header
        header_frame = tk.Frame(self.root)
        header_frame.pack(fill='x', padx=20, pady=(15, 5))
        tk.Label(header_frame, text="AI Subtitle Generator", font=("Segoe UI", 20, "bold")).pack(side='left')
        tk.Label(header_frame, text="v2.6", font=("Segoe UI", 10)).pack(side='left', padx=10, pady=(12, 0))

        # MODE SELECTION
        self.mode_var = tk.StringVar(value="video")
        frame_mode = tk.Frame(self.root)
        frame_mode.pack(fill='x', padx=20, pady=5)
        ttk.Radiobutton(frame_mode, text="Generate from Video", variable=self.mode_var, value="video", command=self.update_mode).pack(side='left', padx=10)
        ttk.Radiobutton(frame_mode, text="Translate Existing SRT", variable=self.mode_var, value="srt", command=self.update_mode).pack(side='left', padx=10)

        # FILE SELECTION
        self.frame_file = ttk.LabelFrame(self.root, text=" 1. Select Video File ")
        self.frame_file.pack(fill='x', padx=20, pady=10)
        
        self.lbl_file = tk.Label(self.frame_file, text="Drag & Drop Video Here...", font=("Segoe UI", 10, "italic"), width=50, height=3)
        self.lbl_file.pack(fill='x', padx=10, pady=10)
        self.lbl_file.bind("<Button-1>", lambda e: self.browse_smart())
        
        try:
            self.lbl_file.drop_target_register('DND_Files')
            self.lbl_file.dnd_bind('<<Drop>>', self.drop_smart)
        except: pass

        # SETTINGS
        self.frame_settings = ttk.LabelFrame(self.root, text=" 2. Configuration ")
        self.frame_settings.pack(fill='x', padx=20, pady=10)
        
        # Model (Hideable)
        self.frame_model = ttk.Frame(self.frame_settings)
        self.frame_model.pack(fill='x', padx=15, pady=5)
        ttk.Label(self.frame_model, text="AI Model:").pack(side='left')
        self.combo_models = ttk.Combobox(self.frame_model, state="readonly", width=30)
        self.combo_models.pack(side='left', padx=10)
        ttk.Button(self.frame_model, text="Manage Models", command=self.open_model_manager).pack(side='right')

        # Language
        lang_frame = ttk.Frame(self.frame_settings)
        lang_frame.pack(fill='x', padx=15, pady=5)
        ttk.Label(lang_frame, text="Target:    ").pack(side='left')
        self.var_lang = tk.StringVar(value="fa")
        ttk.Radiobutton(lang_frame, text="Persian (Farsi)", variable=self.var_lang, value="fa").pack(side='left', padx=5)
        ttk.Radiobutton(lang_frame, text="English", variable=self.var_lang, value="en").pack(side='left', padx=15)

        self.refresh_models()

        # LOG
        frame_log = ttk.Frame(self.root)
        frame_log.pack(fill='both', expand=True, padx=20, pady=5)
        self.lbl_status = ttk.Label(frame_log, text="Ready.")
        self.lbl_status.pack(anchor='w')
        self.progress = ttk.Progressbar(frame_log, length=100, mode='determinate')
        self.progress.pack(fill='x', pady=5)
        self.txt_log = tk.Text(frame_log, height=6, state='disabled', font=("Consolas", 9), bg="white")
        self.txt_log.pack(fill='both', expand=True)

        self.btn_run = ttk.Button(self.root, text="START GENERATION", style="Accent.TButton", command=self.start_smart)
        self.btn_run.pack(fill='x', padx=20, pady=10)

        tk.Label(self.root, text="Telegram:nasa1680", font=("Segoe UI", 8)).pack(pady=(0, 5))

        self.file_path = None
        self.running = False
        if not master: self.root.mainloop()

    def open_model_manager(self): ModelManagerGUI(self.root, self.refresh_models)
    
    def refresh_models(self):
        models = []
        if os.path.exists(LOCAL_MODELS_DIR):
            for d in os.listdir(LOCAL_MODELS_DIR):
                if d == "punctuation": continue 
                full_path = os.path.join(LOCAL_MODELS_DIR, d)
                if validate_model_path(full_path): models.append((d, full_path))
        self.model_paths = {name: path for name, path in models}
        vals = list(self.model_paths.keys())
        if not vals:
            self.combo_models['values'] = ["No models found! Please download one."]
            self.combo_models.set("No models found! Please download one.")
        else:
            self.combo_models['values'] = vals
            self.combo_models.current(0)

    def log(self, msg): self.safe_log(msg)

    def update_mode(self):
        mode = self.mode_var.get()
        if mode == "video":
            self.frame_file.config(text=" 1. Select Video File ")
            self.lbl_file.config(text=os.path.basename(self.file_path) if self.file_path and self.file_path.endswith(('.mp4','.mkv','.avi','.mov','.flv')) else "Drag & Drop Video Here...")
            self.frame_model.pack(fill='x', padx=15, pady=5) # Show Model
            self.btn_run.config(text="START GENERATION")
        else:
            self.frame_file.config(text=" 1. Select SRT File ")
            self.lbl_file.config(text=os.path.basename(self.file_path) if self.file_path and self.file_path.endswith('.srt') else "Drag & Drop SRT Here...")
            self.frame_model.pack_forget() # Hide Model
            self.btn_run.config(text="START TRANSLATION")

    def browse_smart(self):
        mode = self.mode_var.get()
        if mode == "video":
            path = filedialog.askopenfilename(filetypes=[("Video Files", "*.mp4;*.mkv;*.avi;*.mov;*.flv")])
        else:
            path = filedialog.askopenfilename(filetypes=[("SRT Files", "*.srt")])
        
        if path: 
            self.file_path = path
            self.lbl_file.config(text=os.path.basename(path), fg="black", font=("Segoe UI", 10, "bold"))

    def drop_smart(self, event):
        path = event.data.strip('{}')
        if not os.path.isfile(path): return
        
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.mp4', '.mkv', '.avi', '.mov', '.flv']:
            self.mode_var.set("video")
            self.update_mode()
            self.file_path = path
            self.lbl_file.config(text=os.path.basename(path), fg="black", font=("Segoe UI", 10, "bold"))
        elif ext == '.srt':
            self.mode_var.set("srt")
            self.update_mode()
            self.file_path = path
            self.lbl_file.config(text=os.path.basename(path), fg="black", font=("Segoe UI", 10, "bold"))

    def start_smart(self):
        if not self.file_path or not os.path.exists(self.file_path): 
            messagebox.showerror("Error", "Check input file."); return

        mode = self.mode_var.get()
        if mode == "video":
            model_name = self.combo_models.get()
            if model_name not in self.model_paths: messagebox.showerror("Error", "Check model."); return
            
            if self.btn_run['text'] == "STOP":
                self.running = False
                self.btn_run.config(state='disabled', text="Stopping...")
                return
            
            self.running = True
            self.btn_run.config(text="STOP")
            threading.Thread(target=self.process_thread, args=(self.file_path, self.model_paths[model_name], self.var_lang.get()), daemon=True).start()
        else:
            # SRT Translation
            if self.btn_run['text'] == "STOP":
                self.running = False
                self.btn_run.config(state='disabled', text="Stopping...")
                return
            
            self.running = True
            self.btn_run.config(text="STOP")
            threading.Thread(target=self.trans_thread, args=(self.file_path, self.var_lang.get()), daemon=True).start()

    def process_thread(self, video_path, model_path, target_lang):
        audio_path = os.path.join(tempfile.gettempdir(), f"temp_{uuid.uuid4().hex}.wav")
        wf = None
        try:
            final_path = get_installed_model_path(os.path.basename(model_path))
            if not final_path: final_path = model_path
            
            self.root.after(0, lambda: self.safe_log("Extracting audio..."))
            self.root.after(0, lambda: self.safe_progress(5))
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            command = [ffmpeg.get_ffmpeg_exe(), "-y", "-i", video_path, "-ac", "1", "-ar", "16000", "-f", "wav", audio_path]
            log_file_path = os.path.join(tempfile.gettempdir(), f"ffmpeg_log_{uuid.uuid4().hex}.txt")
            
            with open(log_file_path, "w") as log_file:
                proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log_file, startupinfo=startupinfo)
                while proc.poll() is None:
                    if not self.running: 
                        proc.terminate()
                        self.root.after(0, lambda: self.safe_finish(False, error="Stopped"))
                        return
                    time.sleep(0.1)
            
            if not self.running: return

            if not os.path.exists(audio_path):
                err_msg = "Unknown Error"
                if os.path.exists(log_file_path):
                    with open(log_file_path, "r") as f: err_msg = f.read()[-500:]
                try: os.remove(log_file_path) 
                except: pass
                raise Exception(f"FFmpeg failed to extract audio.\nError details:\n{err_msg}")
            try: os.remove(log_file_path) 
            except: pass

            self.root.after(0, lambda: self.safe_log(f"Loading {os.path.basename(final_path)}..."))
            model = vosk.Model(final_path)
            wf = wave.open(audio_path, "rb")
            rec = vosk.KaldiRecognizer(model, wf.getframerate())
            rec.SetWords(True)
            
            translator = GoogleTranslator(source='en', target='fa')
            total_frames = wf.getnframes()
            results = []
            
            self.root.after(0, lambda: self.safe_log("Transcribing..."))
            while True:
                if not self.running: 
                    if wf: wf.close()
                    self.root.after(0, lambda: self.safe_finish(False, error="Stopped"))
                    return
                
                data = wf.readframes(8000)
                if len(data) == 0: break
                
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    if 'text' in res and res['text']: 
                        results.append(res)
                        text_preview = res['text'][:30]
                        self.root.after(0, lambda t=text_preview: self.safe_log(f"Detected: {t}..."))
                
                if wf.tell() % 80000 == 0: 
                    progress_val = 10 + (wf.tell() / total_frames * 70)
                    self.root.after(0, lambda p=progress_val: self.safe_progress(p))
            
            res = json.loads(rec.FinalResult())
            if 'text' in res and res['text']: results.append(res)
            wf.close(); wf = None

            if not self.running: return

            self.root.after(0, lambda: self.safe_log("Processing..."))
            srt_content = ""; count = 1
            
            def fmt_time(seconds):
                td = datetime.timedelta(seconds=seconds)
                total_seconds = int(td.total_seconds())
                millis = int((seconds - total_seconds) * 1000)
                return f"{total_seconds//3600:02}:{(total_seconds%3600)//60:02}:{total_seconds%60:02},{millis:03}"

            for item in results:
                if not self.running: self.root.after(0, lambda: self.safe_finish(False, error="Stopped")); return
                if not item.get('result'): continue
                words = item['result']; text = item['text']
                
                if target_lang == "fa":
                    try: text = f"\u202B{translator.translate(text)}"
                    except: pass
                
                srt_content += f"{count}\n{fmt_time(words[0]['start'])} --> {fmt_time(words[-1]['end'])}\n{text}\n\n"
                count += 1
                self.root.after(0, lambda p=80+(count/len(results)*20): self.safe_progress(p))

            srt_path = os.path.splitext(video_path)[0] + f"_{target_lang}.srt"
            with open(srt_path, "w", encoding="utf-8") as f: f.write(srt_content)
            self.root.after(0, lambda: self.safe_finish(True, srt_path))

        except Exception as e:
            self.root.after(0, lambda err=str(e): self.safe_finish(False, error=err))
        finally:
            if wf: wf.close()
            if os.path.exists(audio_path):
                try: os.remove(audio_path)
                except: pass
            self.root.after(0, lambda: self.btn_run.config(text="START GENERATION" if self.mode_var.get()=="video" else "START TRANSLATION", state='normal'))

    def parse_srt_blocks(self, content):
        blocks = re.split(r'\n\s*\n', content.strip())
        parsed = []
        for block in blocks:
            lines = block.split('\n')
            if len(lines) >= 3:
                if lines[0].strip().isdigit():
                    time_line = lines[1]
                    text_lines = lines[2:]
                else:
                    if '-->' in lines[0]:
                        time_line = lines[0]
                        text_lines = lines[1:]
                    else:
                        continue
                text = "\n".join(text_lines)
                parsed.append({'header': lines[0], 'time': time_line, 'text': text})
        return parsed

    def trans_thread(self, srt_path, target_lang):
        try:
            self.root.after(0, lambda: self.safe_log(f"Reading {os.path.basename(srt_path)}..."))
            with open(srt_path, 'r', encoding='utf-8') as f: content = f.read()

            blocks = self.parse_srt_blocks(content)
            translator = GoogleTranslator(source='auto', target=target_lang)
            
            new_content = ""
            total = len(blocks)
            
            for i, block in enumerate(blocks):
                if not self.running: break
                original_text = block['text']
                try:
                    translated = translator.translate(original_text)
                    if target_lang == 'fa': translated = f"\u202B{translated}"
                except: translated = original_text
                
                new_content += f"{block['header']}\n{block['time']}\n{translated}\n\n"
                perc = ((i + 1) / total) * 100
                self.root.after(0, lambda p=perc: self.safe_progress(p))
                if i % 5 == 0: self.root.after(0, lambda t=translated[:30]: self.safe_log(f"Trans: {t}..."))

            new_path = os.path.splitext(srt_path)[0] + f"_translated_{target_lang}.srt"
            with open(new_path, "w", encoding="utf-8") as f: f.write(new_content)
            self.root.after(0, lambda: self.safe_finish(True, new_path))
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.safe_finish(False, error=err))

    def safe_log(self, msg):
        self.txt_log.config(state='normal'); self.txt_log.insert(tk.END, msg + "\n"); self.txt_log.see(tk.END); self.txt_log.config(state='disabled'); self.lbl_status.config(text=msg)
    def safe_progress(self, val): self.progress['value'] = val
    def safe_finish(self, success, path=None, error=None):
        self.btn_run.config(text="START GENERATION" if self.mode_var.get()=="video" else "START TRANSLATION", state='normal')
        if success:
            self.safe_log(f"Done! Saved: {os.path.basename(path)}")
            self.safe_progress(100)
            messagebox.showinfo("Success", f"File saved!\n{path}")
        elif error != "Stopped":
            self.safe_log(f"Error: {error}")
            messagebox.showerror("Error", str(error))
        else: self.safe_progress(0)

if __name__ == "__main__":
    SubtitleGenGUI()