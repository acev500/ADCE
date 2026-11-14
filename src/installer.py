# -*- coding: utf-8 -*-
"""超分辨 · 安装程序（自包含：内嵌 payload.7z 与 7z 解压器）"""
import os, sys, subprocess, threading, queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

APP_NAME = "超分辨"
DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME


def res(name):
    """PyInstaller 解包目录 / 源码目录"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def sete(name):
    return Path(os.environ.get(name, str(Path.home())))


class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} · 安装程序")
        self.geometry("560x300")
        self.resizable(False, False)
        try:
            self.iconbitmap(str(res("icon.ico")))
        except Exception:
            pass
        self.target = tk.StringVar(value=str(DEFAULT_DIR))
        self.msg = tk.StringVar(value="准备安装。目标目录可修改。")
        self.q = queue.Queue()
        self._build()

    def _build(self):
        pad = ttk.Frame(self, padding=14)
        pad.pack(fill="both", expand=True)
        ttk.Label(pad, text=f"{APP_NAME} · 视频超分 / 放大 / 补帧",
                  font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        ttk.Label(pad, text="将安装到下面的目录（约 530 MB）：", foreground="#555").pack(anchor="w", pady=(10, 2))
        row = ttk.Frame(pad)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.target).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="更改…", command=self.pick_dir).pack(side="left", padx=6)
        self.pb = ttk.Progressbar(pad, mode="determinate", maximum=100)
        self.pb.pack(fill="x", pady=14)
        ttk.Label(pad, textvariable=self.msg, foreground="#333").pack(anchor="w")
        foot = ttk.Frame(pad)
        foot.pack(fill="x", pady=(14, 0))
        self.btn = ttk.Button(foot, text="开始安装", command=self.start)
        self.btn.pack(side="left")
        ttk.Button(foot, text="退出", command=self.destroy).pack(side="left", padx=8)

    def pick_dir(self):
        d = filedialog.askdirectory(title="选择安装目录")
        if d:
            self.target.set(str(Path(d) / APP_NAME))

    def start(self):
        self.btn.config(state="disabled")
        threading.Thread(target=self._work, daemon=True).start()
        self.after(150, self._pump)

    def _work(self):
        try:
            tgt = Path(self.target.get())
            tgt.mkdir(parents=True, exist_ok=True)
            payload = res("payload.7z")
            seven = res("7z.exe")
            if not payload.exists() or not seven.exists():
                self.q.put(("err", "安装包不完整（缺少 payload.7z 或 7z.exe）"))
                return
            self.q.put(("msg", "正在解压（约 1–3 分钟）…"))
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            p = subprocess.Popen([str(seven), "x", str(payload), f"-o{tgt}", "-y", "-bsp1"],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 universal_newlines=True, encoding="utf-8", errors="replace",
                                 creationflags=flags)
            for line in p.stdout:
                line = line.strip()
                if "%" in line:
                    try:
                        pct = int(line.split("%")[0].strip().split()[-1])
                        self.q.put(("pb", pct))
                    except Exception:
                        pass
                elif line:
                    self.q.put(("msg", line[:80]))
            p.wait()
            if p.returncode != 0:
                self.q.put(("err", "解压失败，请检查目标目录权限"))
                return
            self.q.put(("msg", "正在创建桌面快捷方式…"))
            self._shortcut(tgt)
            self.q.put(("done", tgt))
        except Exception as e:
            self.q.put(("err", str(e)))

    def _shortcut(self, tgt):
        exe = tgt / "ChaofenbianGUI.exe"
        ico = tgt / "icon.ico"
        desk = str(Path(os.path.expanduser("~")) / "Desktop")
        ps = (
            "$ws=New-Object -ComObject WScript.Shell;"
            f"$d='{desk}';"
            f"$l=$ws.CreateShortcut((Join-Path $d '{APP_NAME}.lnk'));"
            f"$l.TargetPath='{exe}';"
            f"$l.WorkingDirectory='{tgt}';"
            f"$l.IconLocation='{ico},0';"
            f"$l.Description='视频超分 / 放大 / 补帧';"
            "$l.Save()"
        )
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       creationflags=flags, capture_output=True)

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "pb":
                    self.pb["value"] = val
                elif kind == "msg":
                    self.msg.set(val)
                elif kind == "err":
                    self.msg.set("错误：" + val)
                    self.btn.config(state="normal")
                    messagebox.showerror("安装失败", val)
                    return
                elif kind == "done":
                    self.pb["value"] = 100
                    self.msg.set("安装完成。")
                    exe = Path(val) / "ChaofenbianGUI.exe"
                    if messagebox.askyesno("安装完成", f"已安装到：\n{val}\n\n现在启动吗？"):
                        try:
                            subprocess.Popen([str(exe)], cwd=str(Path(val)))
                        except Exception as e:
                            messagebox.showwarning("启动失败", str(e))
                    self.btn.config(state="normal")
                    return
        except queue.Empty:
            pass
        self.after(150, self._pump)


if __name__ == "__main__":
    Installer().mainloop()
