# -*- coding: utf-8 -*-
"""超分辨 · 图形界面 v2
- 顶部选择处理模式：① AI 超分 / ② 仅放大（传统算法），选哪个只显示哪套参数
- 分页：基础 / 高级
- 预设、信息面板、进度条、日志窗口（不再另开黑窗口）
"""
import os, sys, json, re, subprocess, threading, queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).parent
else:
    BASE = Path(__file__).resolve().parent
    if not (BASE / "bin").is_dir() and (BASE.parent / "bin").is_dir():
        BASE = BASE.parent
BIN = BASE / "bin"
CFG = BASE / "config.json"
CLI = BASE / "超分辨.exe"

SR_ORDER = ["realesr-animevideov3", "realcugan-pro", "realcugan-se",
            "realesrgan-x4plus", "realesrgan-x4plus-anime"]
SR_DESC = {
    "realesr-animevideov3": "视频向·快·几乎不重画",
    "realcugan-pro": "保守·不易重画脸·真人素材推荐",
    "realcugan-se": "保守·更快",
    "realesrgan-x4plus": "写实照片向·慢·易过度锐化",
    "realesrgan-x4plus-anime": "动漫向",
}
LEVEL_DESC = {-1: "-1 不降噪（保留噪点）", 0: "0 保守（最轻）", 1: "1 轻", 2: "2 中", 3: "3 强"}
RIFE_ORDER = ["rife-v4.6", "rife-HD", "rife-anime", "rife-UHD"]
RIFE_DESC = {"rife-v4.6": "通用·质量最好（支持 2/3/4 倍）", "rife-HD": "高清向·只能 2 倍",
             "rife-anime": "动漫向·只能 2 倍", "rife-UHD": "超高清·最慢·只能 2 倍"}
LUTS = [(0, "无"), (1, "灰黑重工业"), (2, "冷蓝档案"), (3, "暖橙工业"), (4, "阴天纪实"), (5, "自定义（自己调）")]
ALGOS = [(1, "lanczos（锐·轻微振铃）"), (2, "spline36（平滑·推荐）"),
         (3, "bicubic（最柔）"), (4, "超采样（3倍再缩·最干净·慢）"),
         (5, "ewa_lanczossharp（libplacebo·传统最强·慢）")]
LEVEL_MAP = {"no-denoise": -1, "conservative": 0, "denoise1x": 1, "denoise2x": 2, "denoise3x": 3}

DEFAULTS = {
    "mode": "scale", "sr_model": "realesr-animevideov3", "sr_scale": 2, "rc_noise": -1,
    "scale_algo": 2, "rife_model": "rife-v4.6", "rife_mul": 2, "target": "720",
    "crf": 16, "chunk_sec": 20, "gpu": "auto", "auto_clean": True,
    "pp_deband": 1, "pp_deblock": 0, "pp_cas": 0.3, "lut": 4, "grain": 1,
    "lut_contrast": 1.08, "lut_sat": 0.85, "lut_lift": 0.010,
    "lut_shoulder": 0.25, "lut_temp": -0.008,
}

PRESETS = {
    "阴天纪实·纯放大": dict(mode="scale", scale_algo=2, target="720", rife_mul=2, lut=4,
                      grain=1, pp_deband=1, pp_deblock=0, pp_cas=0.3, crf=16),
    "灰黑重工业·AI 超分": dict(mode="ai", sr_model="realcugan-pro", sr_scale=2, rc_noise=-1,
                        target="720", rife_mul=2, lut=1, grain=1, pp_deband=1,
                        pp_deblock=0, pp_cas=0.3, crf=16),
    "高质量修复": dict(mode="ai", sr_model="realesr-animevideov3", sr_scale=2, target="1080",
                  rife_mul=2, lut=1, grain=1, pp_deband=2, pp_deblock=1, pp_cas=0.6, crf=16),
    "快速出片": dict(mode="scale", scale_algo=1, target="720", rife_mul=2, lut=4,
                 grain=0, pp_deband=0, pp_deblock=0, pp_cas=0.0, crf=20),
}


def scan_sr():
    found = {}
    d = BIN / "models"
    if d.is_dir():
        for p in d.glob("*.param"):
            m = re.match(r"^(.+?)-x([234])$", p.stem)
            if m:
                found.setdefault(m.group(1), set()).add(int(m.group(2)))
            else:
                found.setdefault(p.stem, set()).add(4)
    for name, folder in (("realcugan-pro", "models-pro"), ("realcugan-se", "models-se")):
        dd = BIN / folder
        if (BIN / "realcugan-ncnn-vulkan.exe").exists() and dd.is_dir():
            sc = set()
            for p in dd.glob("up*x-*.param"):
                m = re.match(r"up([234])x-", p.name)
                if m:
                    sc.add(int(m.group(1)))
            if sc:
                found[name] = sc
    order = [x for x in SR_ORDER if x in found] + [x for x in sorted(found) if x not in SR_ORDER]
    return {k: found[k] for k in order}


def scan_rife():
    out = [p.name for p in BIN.iterdir() if p.is_dir() and p.name.lower().startswith("rife")] if BIN.is_dir() else []
    return [x for x in RIFE_ORDER if x in out] + [x for x in sorted(out) if x not in RIFE_ORDER]


def cugan_levels(model, scale):
    folder = "models-pro" if model.endswith("-pro") else "models-se"
    d = BIN / folder
    out = []
    if d.is_dir():
        for p in d.glob(f"up{int(scale)}x-*.param"):
            name = p.stem.split(f"up{int(scale)}x-")[-1]
            if name in LEVEL_MAP:
                out.append(LEVEL_MAP[name])
    return sorted(out) or [-1]


def load_cfg():
    c = dict(DEFAULTS)
    if CFG.exists():
        try:
            c.update(json.loads(CFG.read_text(encoding="utf-8-sig")))
        except Exception:
            pass
    return c


def probe(path):
    ff = BIN / "ffmpeg.exe"
    try:
        p = subprocess.run([str(ff), "-hide_banner", "-i", str(path)],
                           capture_output=True, universal_newlines=True,
                           encoding="utf-8", errors="replace",
                           creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        txt = (p.stderr or "") + (p.stdout or "")
    except Exception:
        return 0, 0, 0, 0
    dur = fps = 0.0
    w = h = 0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", txt)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", txt)
    if m:
        fps = float(m.group(1))
    m = re.search(r",\s*(\d{2,5})x(\d{2,5})", txt)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    return dur, fps, w, h


def _write_seed_png(path, size=16, val=(32, 32, 32)):
    """不依赖 Tk 生成一张纯色 PNG"""
    import zlib, struct
    raw = b"".join(b"\x00" + bytes(val) * size for _ in range(size))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw))
    png += chunk(b"IEND", b"")
    Path(path).write_bytes(png)


def detect_gpus():
    """用 realesrgan 初始化时的设备列表，返回 [(编号, 型号)]"""
    sr = BIN / "realesrgan-ncnn-vulkan.exe"
    if not sr.exists():
        return []
    tmpdir = BASE / "_gpuprobe"
    try:
        tmpdir.mkdir(exist_ok=True)
        png = tmpdir / "seed.png"
        if not png.exists():
            _write_seed_png(png)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        r = subprocess.run([str(sr), "-i", str(png), "-o", str(tmpdir / "out.png"),
                            "-n", "realesr-animevideov3", "-s", "2", "-g", "0", "-v"],
                           capture_output=True, universal_newlines=True,
                           encoding="utf-8", errors="replace",
                           creationflags=flags, timeout=40)
        txt = (r.stderr or "") + (r.stdout or "")
        gpus = re.findall(r"\[(\d+)\s+([^\]]+)\]", txt)
        seen = []
        for idx, name in gpus:
            item = (int(idx), name.strip())
            if item not in seen:
                seen.append(item)
        return sorted(seen)
    except Exception:
        return []
    finally:
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("超分辨 · 视频 / 图片 超分")
        self.geometry("880x760")
        self.minsize(780, 640)
        try:
            self.iconbitmap(str(BASE / "icon.ico"))
        except Exception:
            pass
        self.cfg = load_cfg()
        self.sr = scan_sr()
        self.rife = scan_rife()
        self.src = tk.StringVar()
        self.info = tk.StringVar(value="未选择视频")
        self.proc = None
        self.q = queue.Queue()
        self.gpus = []
        self._build()
        self._load_into_ui()
        threading.Thread(target=self._gpu_async, daemon=True).start()
        self.after(120, self._pump)

    # ---------------- 布局 ----------------
    def _build(self):
        pad = ttk.Frame(self, padding=10)
        pad.pack(fill="both", expand=True)

        head = ttk.Frame(pad)
        head.pack(fill="x")
        ttk.Label(head, text="超分辨", font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        ttk.Label(head, text="  AI 超分 / 传统放大 · 补帧 · 调色",
                  foreground="#777").pack(side="left", padx=(8, 0))

        self.kind = tk.StringVar(value="video")

        box_kind = ttk.LabelFrame(pad, text=" 处理对象（先选这个，下面只显示对应参数） ", padding=6)
        box_kind.pack(fill="x", pady=(8, 3))
        ttk.Radiobutton(box_kind, text="视频（超分 + 补帧）", variable=self.kind,
                        value="video", command=self.on_kind).pack(side="left")
        ttk.Radiobutton(box_kind, text="图片（只超分，不补帧）", variable=self.kind,
                        value="image", command=self.on_kind).pack(side="left", padx=(20, 0))

        self.box_mode = ttk.LabelFrame(pad, text=" 处理模式（二选一，只显示对应参数） ", padding=6)
        self.box_mode.pack(fill="x", pady=(6, 3))
        self.mode = tk.StringVar(value="ai")
        ttk.Radiobutton(self.box_mode, text="① AI 超分（提清晰度·可能重画细节）",
                        variable=self.mode, value="ai", command=self.on_mode).pack(side="left")
        ttk.Radiobutton(self.box_mode, text="② 仅放大（传统算法·不改内容）",
                        variable=self.mode, value="scale", command=self.on_mode).pack(side="left", padx=(18, 0))

        self.box_src = ttk.LabelFrame(pad, text=" 1. 视频 ", padding=6)
        self.box_src.pack(fill="x", pady=3)
        row = ttk.Frame(self.box_src)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.src).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", command=self.pick_file).pack(side="left", padx=6)
        ttk.Label(self.box_src, textvariable=self.info, foreground="#555",
                  anchor="w").pack(fill="x", pady=(4, 0))

        self.box_pre = ttk.LabelFrame(pad, text=" 快速预设 ", padding=6)
        self.box_pre.pack(fill="x", pady=3)
        for name in PRESETS:
            ttk.Button(self.box_pre, text=name, width=15,
                       command=lambda n=name: self.apply_preset(n)).pack(side="left", padx=2)

        self.nb = ttk.Notebook(pad)
        self.nb.pack(fill="both", expand=True, pady=4)
        nb = self.nb

        # ---------- 基础页 ----------
        tab1 = self._scroll_tab(nb, " 基础 ")

        self.box_out = ttk.LabelFrame(tab1, text=" 输出与补帧 ", padding=8)
        self.box_out.pack(fill="x", pady=3, side="bottom")
        self.box_out.columnconfigure(1, weight=1)
        self.cb_res = ttk.Combobox(self.box_out, state="readonly", width=12, values=["1080", "720", "原始"])
        self._row(self.box_out, 0, "输出分辨率", self.cb_res)
        self.cb_rife = ttk.Combobox(self.box_out, state="readonly", width=38)
        self.cb_rife.bind("<<ComboboxSelected>>", lambda e: self.on_rife())
        self._row(self.box_out, 1, "补帧模型", self.cb_rife)
        self.lbl_rife = ttk.Label(self.box_out, text="", foreground="#666")
        self.lbl_rife.grid(row=2, column=0, columnspan=2, sticky="w")
        self.cb_mul = ttk.Combobox(self.box_out, state="readonly", width=12, values=["2", "3", "4"])
        self._row(self.box_out, 3, "补帧倍数", self.cb_mul)

        self.box_ai = ttk.LabelFrame(tab1, text=" AI 超分参数 ", padding=8)
        self.box_ai.pack(fill="x", pady=3)
        self.box_ai.columnconfigure(1, weight=1)
        self.cb_sr = ttk.Combobox(self.box_ai, state="readonly", width=38)
        self.cb_sr.bind("<<ComboboxSelected>>", lambda e: self.on_sr())
        self._row(self.box_ai, 0, "超分模型", self.cb_sr)
        self.lbl_sr = ttk.Label(self.box_ai, text="", foreground="#666")
        self.lbl_sr.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.cb_scale = ttk.Combobox(self.box_ai, state="readonly", width=12)
        self.cb_scale.bind("<<ComboboxSelected>>", lambda e: self.on_scale())
        self._row(self.box_ai, 2, "超分倍数", self.cb_scale)
        self.cb_lv = ttk.Combobox(self.box_ai, state="readonly", width=26)
        self._row(self.box_ai, 3, "CUGAN 降噪档", self.cb_lv)
        self.lbl_lv = ttk.Label(self.box_ai, text="", foreground="#666")
        self.lbl_lv.grid(row=4, column=0, columnspan=2, sticky="w")

        self.box_scale = ttk.LabelFrame(tab1, text=" 放大参数（传统算法，不改内容） ", padding=8)
        self.box_scale.pack(fill="x", pady=3)
        self.box_scale.columnconfigure(1, weight=1)
        self.cb_algo = ttk.Combobox(self.box_scale, state="readonly", width=42,
                                    values=[f"{i} {n}" for i, n in ALGOS])
        self._row(self.box_scale, 0, "放大算法", self.cb_algo)
        ttk.Label(self.box_scale, text="spline36 适合暗部多的素材；ewa 更干净但更慢",
                  foreground="#666").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # ---------- 高级页 ----------
        tab2 = self._scroll_tab(nb, " 高级 ")

        box_pp = ttk.LabelFrame(tab2, text=" 后处理（专治 AI 素材的毛病） ", padding=8)
        box_pp.pack(fill="x", pady=3)
        box_pp.columnconfigure(1, weight=1)
        box_pp.columnconfigure(4, weight=1)
        ttk.Label(box_pp, text="去色带 deband").grid(row=0, column=0, sticky="w", pady=3)
        self.cb_deband = ttk.Combobox(box_pp, state="readonly", width=8, values=["0 关", "1 轻", "2 中"])
        self.cb_deband.grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(box_pp, text="去压缩块 deblock").grid(row=0, column=3, sticky="w", padx=(16, 6))
        self.cb_deblock = ttk.Combobox(box_pp, state="readonly", width=8, values=["0 关", "1 开"])
        self.cb_deblock.grid(row=0, column=4, sticky="w")

        ttk.Label(box_pp, text="锐化 cas").grid(row=1, column=0, sticky="w", pady=3)
        self.cb_cas = ttk.Combobox(box_pp, state="readonly", width=8, values=["0 关", "0.3 轻", "0.6 中"])
        self.cb_cas.grid(row=1, column=1, sticky="w", pady=3)

        box_grade = ttk.LabelFrame(tab2, text=" 调色 ", padding=8)
        box_grade.pack(fill="x", pady=3)
        box_grade.columnconfigure(1, weight=1)
        self.cb_lut = ttk.Combobox(box_grade, state="readonly", width=24,
                                   values=[f"{i} {n}" for i, n in LUTS])
        self._row(box_grade, 0, "调色 LUT", self.cb_lut)
        self.cb_grain = ttk.Combobox(box_grade, state="readonly", width=10, values=["0 关", "1 轻", "2 中"])
        self._row(box_grade, 1, "胶片颗粒", self.cb_grain)

        self.fr_custom = ttk.LabelFrame(box_grade, text=" 自定义调色 ", padding=6)
        self.fr_custom.grid(row=2, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.fr_custom.columnconfigure(2, weight=1)
        self.custom_vars = {}
        spec = [
            ("对比", "lut_contrast", 0.80, 1.30, 0.02,
             "↑ 更硬更深（压暗暗部） ｜ ↓ 更平更灰 ｜ 1.0 = 不变"),
            ("饱和", "lut_sat", 0.50, 1.20, 0.02,
             "↑ 更艳（接近原色） ｜ ↓ 更灰更脏 ｜ 0.85 左右最真实"),
            ("抬黑", "lut_lift", 0.0, 0.05, 0.005,
             "↑ 黑变灰、暗部出细节（胶片感） ｜ 0 = 死黑"),
            ("高光", "lut_shoulder", 0.0, 0.60, 0.05,
             "↑ 高光压得狠（防爆白/防塑料反光） ｜ 0 = 不压"),
            ("色温", "lut_temp", -0.05, 0.05, 0.005,
             "↑ 偏暖（发黄） ｜ ↓ 偏冷（发青蓝） ｜ 0 = 中性"),
        ]
        for i, (lab, key, lo, hi, inc, hint) in enumerate(spec):
            ttk.Label(self.fr_custom, text=lab, width=5).grid(row=i, column=0, sticky="w", pady=1)
            var = tk.StringVar()
            ttk.Spinbox(self.fr_custom, from_=lo, to=hi, increment=inc, width=6,
                        textvariable=var).grid(row=i, column=1, sticky="w", padx=(2, 8), pady=1)
            ttk.Label(self.fr_custom, text=hint, foreground="#777").grid(
                row=i, column=2, sticky="w")
            self.custom_vars[key] = var
        self.cb_lut.bind("<<ComboboxSelected>>", lambda e: self.on_lut())

        box_misc = ttk.LabelFrame(tab2, text=" 其它 ", padding=8)
        box_misc.pack(fill="x", pady=3)
        ttk.Label(box_misc, text="画质 CRF").grid(row=0, column=0, sticky="w", pady=3)
        self.sp_crf = ttk.Spinbox(box_misc, from_=12, to=26, width=8)
        self.sp_crf.grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(box_misc, text="每段秒数").grid(row=0, column=2, sticky="w", padx=(18, 6))
        self.sp_chunk = ttk.Spinbox(box_misc, from_=5, to=60, width=8)
        self.sp_chunk.grid(row=0, column=3, sticky="w")
        ttk.Label(box_misc, text="GPU 编号").grid(row=1, column=0, sticky="w", pady=3)
        self.cb_gpu = ttk.Combobox(box_misc, state="readonly", width=26,
                                   values=["auto（自动）", "0", "1", "2"])
        self.cb_gpu.grid(row=1, column=1, sticky="w", pady=3)
        self.var_clean = tk.BooleanVar(value=True)
        ttk.Checkbutton(box_misc, text="每段完自动清理缓存",
                        variable=self.var_clean).grid(row=1, column=2, columnspan=2, sticky="w", padx=(18, 0))
        ttk.Button(tab2, text="恢复默认", command=self.reset_defaults).pack(anchor="w", pady=(10, 0))
        ttk.Label(tab2, text="提示：CRF 越小画质越好、文件越大；16 是母版档，18–20 是交付档。",
                  foreground="#666").pack(anchor="w", pady=(6, 0))

        foot = ttk.Frame(pad)
        foot.pack(fill="x", pady=(4, 0))
        self.btn_run = ttk.Button(foot, text="开始处理", command=self.start)
        self.btn_run.pack(side="left")
        ttk.Button(foot, text="打开输出", command=lambda: self.open_dir(BASE / "输出")).pack(side="left", padx=6)
        ttk.Button(foot, text="打开日志", command=lambda: self.open_dir(BASE / "日志")).pack(side="left")
        self.status = ttk.Label(foot, text="就绪", foreground="#666")
        self.status.pack(side="right")

        self.pb = ttk.Progressbar(pad, mode="determinate", maximum=100)
        self.pb.pack(fill="x", pady=(6, 2))
        logbox = ttk.Frame(pad, height=96)
        logbox.pack(fill="x", expand=False, pady=(4, 0))
        logbox.pack_propagate(False)
        self.log = tk.Text(logbox, height=4, wrap="none", font=("Consolas", 9),
                           bg="#111418", fg="#cfd6dd", insertbackground="#cfd6dd")
        sb = ttk.Scrollbar(logbox, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.configure(state="disabled")

    def _gpu_async(self):
        gpus = detect_gpus()
        self.after(0, lambda: self._fill_gpus(gpus))

    def _fill_gpus(self, gpus):
        self.gpus = gpus
        if not gpus:
            self.cb_gpu["values"] = ["auto（自动）", "0", "1", "2"]
            return
        vals = ["auto（自动）"] + [f"{i} {n}" for i, n in gpus]
        self.cb_gpu["values"] = vals
        cur = str(self.cfg.get("gpu", "auto"))
        pick = vals[0]
        if cur != "auto":
            for v in vals[1:]:
                if v.split()[0] == cur:
                    pick = v
                    break
        self.cb_gpu.set(pick)
        self.log_line("[显卡] " + " ｜ ".join(f"{i}: {nm}" for i, nm in gpus))

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")

    def _scroll_tab(self, nb, title):
        wrap = ttk.Frame(nb)
        canvas = tk.Canvas(wrap, highlightthickness=0, borderwidth=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=8)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))

        def _wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")

        canvas.bind_all("<MouseWheel>", _wheel)
        nb.add(wrap, text=title)
        return inner

    def _row(self, parent, r, label, w):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
        w.grid(row=r, column=1, sticky="w", pady=3)

    # ---------------- 联动 ----------------
    def on_kind(self):
        """切换视频 / 图片：只显示对应的参数区"""
        img = self.kind.get() == "image"
        if img:
            # 视频专属区收起来
            self.box_mode.pack_forget()
            self.box_pre.pack_forget()
            self.box_out.pack_forget()
            self.box_scale.pack_forget()
            self.box_ai.pack(fill="x", pady=3)      # 图片模式必须有超分参数
            self.nb.tab(1, state="disabled")
            self.box_src.configure(text=" 1. 图片（单张；也可以拖整个文件夹批量） ")
            self.info.set("未选择图片")
        else:
            self.box_mode.pack(fill="x", pady=(6, 3), before=self.box_src)
            self.box_pre.pack(fill="x", pady=3, after=self.box_src, before=self.nb)
            self.box_out.pack(fill="x", pady=3, side="bottom")
            self.box_ai.pack(fill="x", pady=3)
            if self.mode.get() == "scale":
                self.box_scale.pack(fill="x", pady=3)
            self.nb.tab(1, state="normal")
            self.box_src.configure(text=" 1. 视频 ")
            self.info.set("未选择视频")
        # 图片模式强制回到 AI 超分（图片必须有超分）
        if img:
            self.mode.set("ai")

    def on_mode(self):
        # 图片模式下 box_out / box_scale 是收起的，这里要判断着来，不能硬 pack
        img = self.kind.get() == "image"
        if self.mode.get() == "ai":
            if not img:
                self.box_scale.pack_forget()
            self.box_ai.pack(fill="x", pady=3)
        else:
            self.box_ai.pack_forget()
            if not img:
                self.box_scale.pack(fill="x", pady=3)

    def cur_sr(self):
        return self.cb_sr.get().split("（")[0].strip()

    def cur_rife(self):
        return self.cb_rife.get().split("（")[0].strip()

    def cur_scale(self):
        s = str(self.cb_scale.get()).replace("×", "").strip()
        return int(s) if s.isdigit() else 2

    def cur_gpu(self):
        t = self.cb_gpu.get().strip()
        if t.startswith("auto"):
            return "auto"
        return t.split()[0] if t else "auto"

    def cur_algo(self):
        t = self.cb_algo.get().strip()
        return int(t.split()[0]) if t and t.split()[0].isdigit() else 2

    def on_sr(self):
        model = self.cur_sr()
        self.lbl_sr.config(text=SR_DESC.get(model, ""))
        scales = sorted(self.sr.get(model, {2}))
        prev = str(self.cb_scale.get())
        vals = [f"×{s}" for s in scales]
        self.cb_scale["values"] = vals
        self.cb_scale.set(prev if prev in vals else (vals[0] if vals else ""))
        self.on_scale()

    def on_scale(self):
        model = self.cur_sr()
        is_cugan = model.startswith("realcugan")
        self.cb_lv.config(state="readonly" if is_cugan else "disabled")
        if is_cugan:
            lv = cugan_levels(model, self.cur_scale())
            self.cb_lv["values"] = [LEVEL_DESC.get(x, str(x)) for x in lv]
            if self.cb_lv.get() not in list(self.cb_lv["values"]):
                self.cb_lv.current(0)
            self.lbl_lv.config(text="该模型可用的降噪档：" + " / ".join(str(x) for x in lv))
        else:
            self.cb_lv["values"] = []
            self.cb_lv.set("")
            self.lbl_lv.config(text="（只有 Real-CUGAN 有降噪档）")

    def on_lut(self):
        t = self.cb_lut.get().strip()
        is_custom = t.startswith("5")
        if is_custom:
            self.fr_custom.grid()
        else:
            self.fr_custom.grid_remove()

    def on_rife(self):
        model = self.cur_rife()
        self.lbl_rife.config(text=RIFE_DESC.get(model, ""))
        if model.lower().startswith("rife-v4"):
            self.cb_mul["values"] = ["2", "3", "4"]
            if self.cb_mul.get() not in ("2", "3", "4"):
                self.cb_mul.set("2")
        else:
            self.cb_mul["values"] = ["2"]
            self.cb_mul.set("2")

    # ---------------- 数据 ----------------
    def _load_into_ui(self):
        c = self.cfg
        self.mode.set(c.get("mode", "ai"))
        self.cb_sr["values"] = [f"{k}（{SR_DESC.get(k, '')}）" for k in self.sr]
        idx = list(self.sr.keys()).index(c["sr_model"]) if c["sr_model"] in self.sr else 0
        self.cb_sr.current(idx)
        self.cb_rife["values"] = [f"{k}（{RIFE_DESC.get(k, '')}）" for k in self.rife]
        ridx = self.rife.index(c["rife_model"]) if c["rife_model"] in self.rife else 0
        self.cb_rife.current(ridx)
        self.cb_mul.set(str(c.get("rife_mul", 2)))
        self.cb_res.set(str(c.get("target", "720")))
        self.sp_crf.set(str(c.get("crf", 16)))
        self.sp_chunk.set(str(c.get("chunk_sec", 20)))
        g = str(c.get("gpu", "auto"))
        self.cb_gpu.set("auto（自动）" if g == "auto" else g)
        self.var_clean.set(bool(c.get("auto_clean", True)))
        db = int(c.get("pp_deband", 1))
        self.cb_deband.set(f"{db} " + ("关" if db == 0 else ("轻" if db == 1 else "中")))
        dk = int(c.get("pp_deblock", 0))
        self.cb_deblock.set(f"{dk} " + ("关" if dk == 0 else "开"))
        casv = float(c.get("pp_cas", 0.3))
        self.cb_cas.set("0 关" if casv <= 0 else ("0.3 轻" if casv < 0.45 else "0.6 中"))
        lutv = int(c.get("lut", 4))
        self.cb_lut.set(f"{lutv} " + dict(LUTS).get(lutv, "无"))
        g = int(c.get("grain", 1))
        self.cb_grain.set(f"{g} " + ("关" if g == 0 else ("轻" if g == 1 else "中")))
        for key, dflt in (("lut_contrast", 1.08), ("lut_sat", 0.85), ("lut_lift", 0.010),
                          ("lut_shoulder", 0.25), ("lut_temp", -0.008)):
            self.custom_vars[key].set(str(c.get(key, dflt)))
        amap = {i: f"{i} {n}" for i, n in ALGOS}
        self.cb_algo.set(amap.get(int(c.get("scale_algo", 2)), amap[2]))
        self.on_sr()
        want = c.get("sr_scale", 2)
        for v in list(self.cb_scale["values"]):
            if v == f"×{want}":
                self.cb_scale.set(v)
                break
        self.on_scale()
        self.on_rife()
        self.on_lut()
        self.on_mode()

    def collect(self):
        db = int(self.cb_deband.get().split()[0])
        dk = int(self.cb_deblock.get().split()[0])
        cas = float(self.cb_cas.get().split()[0])
        lut = int(self.cb_lut.get().split()[0])
        grain = int(self.cb_grain.get().split()[0])
        lv = -1
        if self.cur_sr().startswith("realcugan"):
            txt = self.cb_lv.get()
            for k, v in LEVEL_DESC.items():
                if txt == v:
                    lv = k
                    break
        ai = self.mode.get() == "ai"
        return {
            "mode": "ai" if ai else "scale",
            "sr_model": self.cur_sr() if ai else "realesr-animevideov3",
            "sr_scale": self.cur_scale() if ai else 0,
            "rc_noise": lv,
            "scale_algo": self.cur_algo(),
            "rife_model": self.cur_rife(), "rife_mul": int(self.cb_mul.get()),
            "target": self.cb_res.get(), "crf": int(self.sp_crf.get()),
            "chunk_sec": int(self.sp_chunk.get()), "gpu": self.cur_gpu(),
            "auto_clean": bool(self.var_clean.get()),
            "pp_deband": db, "pp_deblock": dk, "pp_cas": cas,
            "lut": lut, "grain": grain,
            "lut_contrast": self._num("lut_contrast", 1.08),
            "lut_sat": self._num("lut_sat", 0.85),
            "lut_lift": self._num("lut_lift", 0.010),
            "lut_shoulder": self._num("lut_shoulder", 0.25),
            "lut_temp": self._num("lut_temp", -0.008),
        }

    def _num(self, key, dflt):
        try:
            return float(self.custom_vars[key].get())
        except Exception:
            return dflt

    def apply_preset(self, name):
        cfg = dict(self.cfg)
        cfg.update(PRESETS[name])
        self.cfg = cfg
        self._load_into_ui()
        self.log_line(f"[预设] {name}")

    def reset_defaults(self):
        self.cfg = dict(DEFAULTS)
        self._load_into_ui()
        self.log_line("[已恢复默认参数]")

    # ---------------- 交互 ----------------
    def pick_file(self):
        p = filedialog.askopenfilename(title="选择视频或图片",
                                       filetypes=[("视频与图片", "*.mp4 *.mov *.mkv *.avi *.webm *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"),
                                                  ("视频", "*.mp4 *.mov *.mkv *.avi *.webm"),
                                                  ("图片", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"),
                                                  ("所有文件", "*.*")])
        if p:
            self.set_src(p)

    def set_src(self, p):
        self.src.set(p)
        self.info.set(f"{Path(p).name} ｜ 读取中…")
        threading.Thread(target=self._probe_async, args=(p,), daemon=True).start()

    def _probe_async(self, p):
        try:
            dur, fps, w, h = probe(p)
            size = Path(p).stat().st_size / 1048576
        except Exception:
            dur = fps = 0
            w = h = 0
            size = 0
        self.after(0, lambda: self._show_info(p, dur, fps, w, h, size))

    def _show_info(self, p, dur, fps, w, h, size):
        ext = Path(p).suffix.lower()
        is_img = ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
        if is_img:
            self.info.set(f"{Path(p).name} ｜ {w}×{h} ｜ {size:.2f}MB   图片模式（只超分，不补帧）")
            return
        tgt = self.cb_res.get() or "720"
        out = tgt if tgt != "原始" else f"{w}×{h}"
        try:
            frames = int(dur * fps * int(self.cb_mul.get() or 2))
        except Exception:
            frames = 0
        self.info.set(f"{Path(p).name} ｜ {w}×{h} ｜ {dur:.1f}s ｜ {fps:.2f}fps ｜ {size:.1f}MB"
                      f"   →   输出 {out} ｜ 约 {frames} 帧")

    def open_dir(self, d):
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))

    def log_line(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self):
        src = self.src.get().strip().strip('"')
        if not src or not Path(src).exists():
            messagebox.showwarning("提示", "先选一个视频或图片文件（图片也可以拖整个文件夹）。")
            return
        if not CLI.exists():
            messagebox.showerror("错误", f"找不到内核：{CLI}")
            return
        cfg = self.collect()
        CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.log_line("[启动] 模式=" + ("AI 超分" if cfg["mode"] == "ai" else "仅放大")
                      + f" ｜ 放大={self.cb_algo.get().split('（')[0]}"
                      + f" ｜ LUT={self.cb_lut.get()}")
        self.btn_run.config(state="disabled")
        self.status.config(text="运行中…")
        self.pb["value"] = 0
        threading.Thread(target=self._run, args=(src,), daemon=True).start()

    def _run(self, src):
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            p = subprocess.Popen([str(CLI), "--auto", src], cwd=str(BASE),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL,
                                 universal_newlines=True, encoding="utf-8",
                                 errors="replace", creationflags=flags)
            self.proc = p
            for line in p.stdout:
                self.q.put(line.rstrip())
            p.wait()
            self.q.put("__EXIT__%d" % p.returncode)
        except Exception as e:
            self.q.put("__ERR__" + str(e))

    def _pump(self):
        try:
            while True:
                line = self.q.get_nowait()
                if line.startswith("__EXIT__"):
                    code = int(line.replace("__EXIT__", "") or 0)
                    self.btn_run.config(state="normal")
                    self.status.config(text="完成" if code == 0 else f"失败（{code}）")
                    if code == 0:
                        self.pb["value"] = 100
                    self.proc = None
                    continue
                if line.startswith("__ERR__"):
                    self.log_line("[错误] " + line.replace("__ERR__", ""))
                    self.btn_run.config(state="normal")
                    self.status.config(text="失败")
                    continue
                self.log_line(line)
                m = re.search(r"\[(?:段\s*)?(\d+)/(\d+)\]", line)
                if m:
                    cur, tot = int(m.group(1)), int(m.group(2))
                    self.pb["value"] = int((cur - 1) / max(tot, 1) * 100)
                if "完成！" in line:
                    self.pb["value"] = 100
        except queue.Empty:
            pass
        self.after(120, self._pump)


if __name__ == "__main__":
    App().mainloop()
