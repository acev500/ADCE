# -*- coding: utf-8 -*-
"""
超分辨 · 视频超分 + 插帧 + 图片超分（命令行界面，全中文）
依赖（放在同目录 bin\\ 下）：
  realesrgan-ncnn-vulkan.exe
  rife-ncnn-vulkan.exe
  ffmpeg.exe
"""
import os, sys, re, json, glob, time, shutil, subprocess, tempfile, math
from pathlib import Path

APP = "超分辨"
VER = "1.0"
if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).parent
else:
    BASE = Path(__file__).resolve().parent
    # 源码直接运行时，本文件在 src\ 里，程序根目录是上一层
    if not (BASE / "bin").is_dir() and (BASE.parent / "bin").is_dir():
        BASE = BASE.parent
BIN = BASE / "bin"
WORKROOT = BASE / "work"
OUTDIR = BASE / "输出"
LOGDIR = BASE / "日志"
CFG = BASE / "config.json"

SR_EXE = BIN / "realesrgan-ncnn-vulkan.exe"
IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
QUIET = False
JSON_OUT = False
CUGAN_EXE = BIN / "realcugan-ncnn-vulkan.exe"
FFMPEG_PL = BIN / "ffmpeg_pl.exe"
LUTDIR = BASE / "lut"
LUT_FILES = {1: "heavy_industrial.cube", 2: "cold_archive.cube", 3: "warm_industrial.cube", 4: "overcast_doc.cube"}
LUT_NAMES = {0: "无", 1: "灰黑重工业", 2: "冷蓝档案", 3: "暖橙工业", 4: "阴天纪实", 5: "自定义"}


def gen_custom_lut(spec, path, size=33):
    """按参数实时生成 .cube：对比/饱和/抬黑/高光滚降/色温"""
    contrast = float(spec.get("contrast", 1.0))
    sat = float(spec.get("sat", 1.0))
    lift = float(spec.get("lift", 0.0))
    shoulder = float(spec.get("shoulder", 0.2))
    temp = float(spec.get("temp", 0.0))

    def tone(x):
        x = 0.5 + (x - 0.5) * contrast
        x = min(max(x, 0.0), 1.0)
        x = x + lift * (1.0 - x) ** 3
        if x > 0.6:
            t = (x - 0.6) / 0.4
            x = 0.6 + 0.4 * (t - shoulder * t * t)
        return min(max(x, 0.0), 1.0)

    def grade(r, g, b):
        r, g, b = tone(r), tone(g), tone(b)
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        r = lum + (r - lum) * sat
        g = lum + (g - lum) * sat
        b = lum + (b - lum) * sat
        r = min(max(r * (1.0 + temp), 0.0), 1.0)
        b = min(max(b * (1.0 - temp), 0.0), 1.0)
        return r, g, b

    lines = ['TITLE "custom"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0",
             "DOMAIN_MAX 1.0 1.0 1.0", ""]
    for bi in range(size):
        bb = bi / (size - 1)
        for gi in range(size):
            gg = gi / (size - 1)
            for ri in range(size):
                rr = ri / (size - 1)
                R, G, B = grade(rr, gg, bb)
                lines.append(f"{R:.6f} {G:.6f} {B:.6f}")
    Path(path).write_text("\n".join(lines), encoding="ascii")
RIFE_EXE = BIN / "rife-ncnn-vulkan.exe"
FFMPEG = BIN / "ffmpeg.exe"

MODEL_DESC = {
    # 超分
    "realesr-animevideov3": "视频向·快·AI 生成的片子首选",
    "realesrgan-x4plus": "写实照片向·慢·细节多但容易过度锐化",
    "realesrgan-x4plus-anime": "动漫向·线条干净·色块平",
    "realcugan-pro": "保守·视频向·不易重画脸（推荐真人素材）",
    "realcugan-se": "保守·更快版",
    # 补帧
    "rife-v4.6": "通用·质量最好·推荐",
    "rife-anime": "动漫向·线条不易拉糊",
    "rife-HD": "高清向·720p 以上更稳",
    "rife-UHD": "超高清向·4K 素材用·最慢",
}

DEFAULTS = {
    "sr_model": "realesr-animevideov3",
    "sr_scale": 2,
    "rife_model": "rife-v4.6",
    "rife_mul": 2,
    "target": "1080",
    "crf": 16,
    "chunk_sec": 20,
    "gpu": "auto",
    "keep_work": False,
    "auto_clean": True,
    "rc_noise": 1,
    "pp_deband": 1,
    "pp_deblock": 0,
    "pp_cas": 0.3,
    "lut": 1,
    "scale_algo": 2,
    "lut_contrast": 1.08,
    "lut_sat": 0.85,
    "lut_lift": 0.010,
    "lut_shoulder": 0.25,
    "lut_temp": -0.008,
    "grain": 1,
}


def setup_console():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def hr(ch="="):
    print(ch * 58)


def title():
    os.system("")  # enable ANSI on win10+
    hr()
    print(f"        {APP}  v{VER}   视频超分 · 补帧")
    hr()


def load_cfg():
    c = dict(DEFAULTS)
    if CFG.exists():
        try:
            c.update(json.loads(CFG.read_text(encoding="utf-8-sig")))
        except Exception:
            pass
    return c


def save_cfg(c):
    try:
        CFG.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


CUGAN_LEVEL_MAP = {"no-denoise": -1, "conservative": 0,
                   "denoise1x": 1, "denoise2x": 2, "denoise3x": 3}
CUGAN_LEVEL_NAME = {v: k for k, v in CUGAN_LEVEL_MAP.items()}


def cugan_dir(model):
    return BIN / ("models-pro" if str(model).endswith("-pro") else "models-se")


def cugan_scales(model):
    d = cugan_dir(model)
    out = set()
    if d.is_dir():
        for q in d.glob("up*x-*.param"):
            m = re.match(r"up([234])x-", q.name)
            if m:
                out.add(int(m.group(1)))
    return sorted(out) or [2]


def cugan_levels(model, scale):
    d = cugan_dir(model)
    out = []
    if d.is_dir():
        for q in d.glob(f"up{int(scale)}x-*.param"):
            name = q.stem.split(f"up{int(scale)}x-")[-1]
            if name in CUGAN_LEVEL_MAP:
                out.append(CUGAN_LEVEL_MAP[name])
    return sorted(out) or [-1]


def cugan_param_ok(model, scale, level):
    d = cugan_dir(model)
    name = CUGAN_LEVEL_NAME.get(int(level))
    return bool(name) and (d / f"up{int(scale)}x-{name}.param").exists()


def sr_models():
    """返回 {模型名: {可用倍数}}，模型为 bin\\models\\*.param"""
    found = {}
    d = BIN / "models"
    if d.is_dir():
        for p in sorted(d.glob("*.param")):
            m = re.match(r"^(.+?)-x([234])$", p.stem)
            if m:
                found.setdefault(m.group(1), set()).add(int(m.group(2)))
            else:
                found.setdefault(p.stem, set()).add(4)
    if CUGAN_EXE.exists():
        if (BIN / "models-pro").is_dir():
            found.setdefault("realcugan-pro", set()).update(cugan_scales("realcugan-pro"))
        if (BIN / "models-se").is_dir():
            found.setdefault("realcugan-se", set()).update(cugan_scales("realcugan-se"))
    return found


def rife_models():
    """bin\\ 下以 rife 开头的模型目录"""
    out = []
    if BIN.is_dir():
        for p in sorted(BIN.iterdir()):
            if p.is_dir() and p.name.lower().startswith("rife"):
                out.append(p.name)
    return out


_NO_PAUSE = False


def _rd(prompt=""):
    """读一行；EOF/中断时返回空串，避免崩溃；--auto 时直接返回，不阻塞"""
    if _NO_PAUSE:
        return ""
    if prompt:
        print(prompt, end="", flush=True)
    try:
        return input()
    except EOFError:
        return ""
    except KeyboardInterrupt:
        raise


def ask(msg, default=None, cast=str):
    if QUIET:
        return default
    s = _rd(msg).strip()
    if not s:
        return default
    try:
        return cast(s)
    except Exception:
        return default


def choose(title_txt, items, default_idx=0):
    if QUIET:
        return items[default_idx]
    print()
    print(title_txt)
    for i, it in enumerate(items, 1):
        mark = "  ← 默认" if i - 1 == default_idx else ""
        print(f"  {i}) {it}{mark}")
    s = _rd(f"选择 [1-{len(items)}，回车={default_idx + 1}]：").strip()
    if not s:
        return items[default_idx]
    try:
        k = int(s)
        if 1 <= k <= len(items):
            return items[k - 1]
    except Exception:
        pass
    return items[default_idx]


LAST_TAIL = []
CURRENT_PROC = None
CURRENT_WORK = None


def run(cmd, logf, cwd=None):
    global LAST_TAIL
    logf.write("\n$ " + " ".join(str(c) for c in cmd) + "\n")
    logf.flush()
    global CURRENT_PROC
    p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, cwd=cwd,
                         universal_newlines=True, encoding="utf-8", errors="replace")
    CURRENT_PROC = p
    tail = []
    for line in p.stdout:
        logf.write(line)
        tail.append(line.rstrip())
        if len(tail) > 80:
            tail.pop(0)
    p.wait()
    CURRENT_PROC = None
    LAST_TAIL = tail[-12:]
    return p.returncode


def show_fail(where):
    print(f"\n  {where}失败。日志尾部：")
    for t in LAST_TAIL[-6:]:
        print("    " + t)


GPU_FALLBACK = False


def run_engine(exe, base_args, gpu_args, logf):
    """先按指定 GPU 跑；失败就自动改用 auto，并记住后面都用 auto"""
    global GPU_FALLBACK
    if GPU_FALLBACK:
        gpu_args = []
    rc = run([exe] + base_args + gpu_args, logf, cwd=str(BIN))
    if rc != 0 and gpu_args:
        print("\n  GPU 参数无效，自动改用 auto（本次运行后续都走 auto）...")
        GPU_FALLBACK = True
        rc = run([exe] + base_args, logf, cwd=str(BIN))
    return rc


def ffprobe_info(path: Path):
    """用 ffmpeg -i 解析时长与帧率"""
    cmd = [FFMPEG, "-hide_banner", "-i", str(path)]
    p = subprocess.run([str(c) for c in cmd], capture_output=True,
                       universal_newlines=True, encoding="utf-8", errors="replace")
    txt = (p.stderr or "") + (p.stdout or "")
    dur, fps = 0.0, 24.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", txt)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", txt)
    if m:
        try:
            fps = float(m.group(1))
        except Exception:
            pass
    return dur, fps


def count(d: Path, pat="*.png"):
    return len(list(d.glob(pat)))


def normalize_sequence(d: Path):
    """把目录里的 png 重命名为连续 00000001.png ...，返回数量"""
    files = sorted([p for p in d.glob("*.png")], key=lambda x: x.name)
    if not files:
        return 0
    tmp = d / "_tmp_norm"
    tmp.mkdir(exist_ok=True)
    for i, f in enumerate(files, 1):
        shutil.move(str(f), str(tmp / f"{i:08d}.png"))
    for f in tmp.glob("*.png"):
        shutil.move(str(f), str(d / f.name))
    try:
        tmp.rmdir()
    except Exception:
        pass
    return len(files)


def bar(done, total, prefix="", width=28):
    total = max(total, 1)
    k = min(done / total, 1.0)
    n = int(k * width)
    print(f"\r{prefix}[{'#' * n}{'.' * (width - n)}] {done}/{total} {k*100:5.1f}%", end="", flush=True)


SR_ORDER = [
    "realesr-animevideov3",
    "realcugan-pro",
    "realcugan-se",
    "realesrgan-x4plus",
    "realesrgan-x4plus-anime",
]


def sort_sr(names):
    def key(x):
        return (SR_ORDER.index(x) if x in SR_ORDER else 99, x)
    return sorted(names, key=key)


SR_ABBR = {
    "realesr-animevideov3": "aev3",
    "realesrgan-x4plus": "x4p",
    "realesrgan-x4plus-anime": "x4a",
    "realesr-animevideov3-x2": "aev3",
    "realcugan-pro": "rcp",
    "realcugan-se": "rcs",
}


def sr_abbr(model, scale):
    if int(scale) == 0:
        return "skip"
    return SR_ABBR.get(model, "".join(w[0] for w in model.replace("realesrgan", "x4").split("-"))[:6] or "sr")


def final_out_name(scale, mul, model):
    size_gb = 0.0
    return f"{time.strftime('%m_%d_%H%M')}_{size_gb:.2f}GB_{sr_abbr(model, scale)} x{int(scale)}_x{int(mul)}"


def plan_chunks(dur, sec, fps=24.0, min_keep=1.5):
    """切段：尾段太短就并进上一段，避免出现 1 帧的碎片"""
    if dur <= 0:
        return [(0.0, 0.0)]
    n = max(1, int(math.ceil(dur / sec)))
    bounds = []
    for i in range(n):
        s = i * sec
        e = min(dur, s + sec)
        if e - s > 0.02:
            bounds.append([s, e])
    if not bounds:
        bounds = [[0.0, dur]]
    keep = max(min_keep, 3.0 / max(fps, 1.0))
    while len(bounds) > 1 and (bounds[-1][1] - bounds[-1][0]) < keep:
        bounds[-2][1] = bounds[-1][1]
        bounds.pop()
    return [(s, e - s) for s, e in bounds]


def clean_stale_work(hours=2):
    """启动时清掉上次被强杀留下的旧缓存（只删 2 小时没动过的，不碰正在跑的）"""
    if not WORKROOT.is_dir():
        return
    now = time.time()
    freed = 0
    for d in WORKROOT.iterdir():
        if not d.is_dir():
            continue
        try:
            files = [p for p in d.rglob("*") if p.is_file()]
            mt = max((p.stat().st_mtime for p in files), default=d.stat().st_mtime)
        except Exception:
            mt = d.stat().st_mtime
        if now - mt > hours * 3600:
            try:
                sz = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
                shutil.rmtree(d, ignore_errors=True)
                freed += sz
            except Exception:
                pass
    if freed > 0:
        print(f"  [启动清理] 已清掉上次残留缓存 {freed/1048576:.0f} MB")


HELP_TXT = """
超分辨 · 命令行版
  直接运行：            交互式问答
  超分辨.exe 视频.mp4    指定文件，仍会问答参数
  超分辨.exe --auto 视频.mp4   读取 config.json，跳过所有提问（图形版用这个）
"""



def img_info(p: Path):
    """读图片宽高（用 ffmpeg 解析，不依赖 PIL）"""
    cmd = [FFMPEG, "-hide_banner", "-i", str(p)]
    r = subprocess.run([str(c) for c in cmd], capture_output=True,
                       universal_newlines=True, encoding="utf-8", errors="replace")
    txt = (r.stderr or "") + (r.stdout or "")
    m = re.search(r"(\d{2,5})x(\d{2,5})", txt)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def image_mode(src: Path, cfg):
    """图片超分：直接过 realesrgan，不走拆帧/补帧"""
    if src.is_dir():
        files = [q for q in sorted(src.iterdir())
                 if q.is_file() and q.suffix.lower() in IMG_EXTS]
        if not files:
            print("  这个文件夹里没有图片。")
            _rd("按回车退出...")
            return 1
        print(f"\n输入文件夹：{src}")
        print(f"图片数量：{len(files)} 张")
    else:
        files = [src]
        w, h = img_info(src)
        sz = src.stat().st_size / 1024
        print(f"\n输入：{src.name}")
        print(f"尺寸：{w}×{h}    大小：{sz:.0f} KB")

    srm = sr_models()
    if not srm:
        print("\n[警告] bin\\models 里没有超分模型，无法处理图片。")
        _rd("按回车退出...")
        return 1

    names = sort_sr(list(srm.keys()))
    _im = str(cfg.get("img_model") or cfg.get("sr_model") or "")
    d = names.index(_im) if _im in names else 0

    print()
    print("—— 图片超分（不需要补帧，所以只问这两项）——")
    labels = []
    for n in names:
        sc = "/".join(str(x) for x in sorted(srm[n]))
        labels.append(f"{n}（{MODEL_DESC.get(n, '')}｜可用 ×{sc}）")
    pick = choose("超分模型（写实照片选 x4plus，AI 生成的图选 animevideov3）：", labels, d)
    mdl = names[labels.index(pick)]
    avail = sorted(srm[mdl])
    sc_labels = [f"{x}（放大 {x} 倍）" for x in avail]
    cur = int(cfg.get("img_scale", 2))
    dsc = avail.index(cur) if cur in avail else 0
    pick_s = choose("放大倍数：", sc_labels, dsc)
    scale = int(pick_s.split("（")[0].strip())
    # 只记图片专用的键，不动视频模式的 sr_model / sr_scale
    cfg["img_model"] = mdl
    cfg["img_scale"] = scale
    save_cfg(cfg)

    OUTDIR.mkdir(exist_ok=True)
    LOGDIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    logp = LOGDIR / f"img_{src.stem}_{stamp}.log"
    logf = open(logp, "w", encoding="utf-8")
    gpu = str(cfg.get("gpu", "auto")).strip().lower()
    gpu_args = [] if gpu in ("auto", "") else ["-g", gpu]

    ok = 0
    t0 = time.time()
    for i, f in enumerate(files, 1):
        dst = OUTDIR / f"{f.stem}_up{scale}x.png"
        print(f"  [{i}/{len(files)}] {f.name} → {dst.name}", end="", flush=True)
        rc = run_engine(SR_EXE, ["-i", str(f), "-o", str(dst), "-n", mdl,
                                 "-s", str(scale), "-f", "png"], gpu_args, logf)
        if rc == 0 and dst.exists():
            print("  完成")
            ok += 1
        else:
            print("  失败（看日志）")
    logf.close()

    if not QUIET:
        print(f"\n  完成 {ok} / {len(files)} 张，用时 {time.time() - t0:.1f} 秒")
        print(f"  输出目录：{OUTDIR}")
        print(f"  日志：{logp}")
    if JSON_OUT:
        print(json.dumps({
            "ok": ok == len(files), "type": "image",
            "done": ok, "total": len(files),
            "out_dir": str(OUTDIR),
            "outputs": [str(OUTDIR / f"{f.stem}_up{scale}x.png") for f in files],
            "seconds": round(time.time() - t0, 2),
            "log": str(logp),
        }, ensure_ascii=False))
    _rd("\n按回车退出...")
    return 0 if ok == len(files) else 2



def parse_args(argv):
    """命令行参数
       位置参数     输入文件或文件夹（第一个）
       --auto       无交互，全部用 config.json 的参数
       --quiet      静默（不打印参数菜单与进度条文字，等价于 --auto）
       --json       结束时往 stdout 打一行 JSON（等价于 --quiet）
       --model N    超分模型名
       --scale N    放大倍数
       --rife N     补帧模型名
       --mul N      补帧倍数
       --target N   输出分辨率（1080 / 720 / 原始）
       --crf N      画质
       --out DIR    输出目录（默认 输出\）
       --help       帮助
    """
    o = {"input": None, "auto": False, "quiet": False, "json": False,
         "model": None, "scale": None, "rife": None, "mul": None,
         "target": None, "crf": None, "out": None}
    KEYED = {"--model": "model", "--scale": "scale", "--rife": "rife",
             "--mul": "mul", "--target": "target", "--crf": "crf", "--out": "out"}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("--help", "-h"):
            o["help"] = True
        elif a == "--auto":
            o["auto"] = True
        elif a == "--quiet":
            o["quiet"] = True
            o["auto"] = True
        elif a == "--json":
            o["json"] = True
            o["quiet"] = True
            o["auto"] = True
        elif a in KEYED:
            if i + 1 < len(argv):
                o[KEYED[a]] = argv[i + 1]
                i += 1
        elif a.startswith("--"):
            pass
        elif o["input"] is None:
            o["input"] = a
        i += 1
    return o


def main():
    setup_console()
    global _NO_PAUSE, OUTDIR, QUIET
    args = parse_args(sys.argv)
    if args.get("help"):
        print(HELP_TXT)
        print("\n命令行参数：\n"
              "  --auto        无交互，用 config.json 的参数\n"
              "  --quiet       静默（不打印菜单）\n"
              "  --json        结束时输出一行 JSON（给脚本用）\n"
              "  --model NAME  超分模型\n"
              "  --scale N     放大倍数\n"
              "  --rife NAME   补帧模型\n"
              "  --mul N       补帧倍数\n"
              "  --target N    输出分辨率 1080/720/原始\n"
              "  --crf N       画质 CRF\n"
              "  --out DIR     输出目录\n"
              "例：\n"
              "  超分辨.exe a.mp4 --quiet --model realesr-animevideov3 --scale 2 --mul 2\n"
              "  超分辨.exe pic.png --quiet --scale 4 --out D:\\out\n"
              "  超分辨.exe D:\\imgs --json --scale 2\n")
        return 0

    auto = args["auto"]
    _NO_PAUSE = auto
    QUIET = args["quiet"]
    global JSON_OUT
    JSON_OUT = args["json"]
    pos = [args["input"]] if args["input"] else []

    # --out 覆盖输出目录
    if args.get("out"):
        _o = Path(args["out"]).expanduser()
        if not _o.is_absolute():
            _o = (BASE / _o).resolve()
        OUTDIR = _o
        OUTDIR.mkdir(parents=True, exist_ok=True)

    if not QUIET:
        title()

    missing = [p for p in (SR_EXE, RIFE_EXE, FFMPEG) if not p.exists()]
    if missing:
        print("缺少以下文件（应放在本程序目录的 bin\\ 下）：")
        for p in missing:
            print("   -", p.name)
        print("\n请补全后重新运行。")
        _rd("\n按回车退出...")
        return 1

    clean_stale_work()

    cfg = load_cfg()
    # 命令行参数覆盖配置文件
    if args.get("model"):
        cfg["sr_model"] = args["model"]
        cfg["img_model"] = args["model"]
    if args.get("scale"):
        try:
            cfg["sr_scale"] = int(args["scale"])
            cfg["img_scale"] = int(args["scale"])
        except ValueError:
            pass
    if args.get("rife"):
        cfg["rife_model"] = args["rife"]
    if args.get("mul"):
        try:
            cfg["rife_mul"] = int(args["mul"])
        except ValueError:
            pass
    if args.get("target"):
        cfg["target"] = args["target"]
    if args.get("crf"):
        try:
            cfg["crf"] = int(args["crf"])
        except ValueError:
            pass

    # 输入
    if pos and Path(pos[0]).exists():
        src = Path(pos[0]).resolve()
    else:
        tries = 0
        src = None
        while True:
            s = _rd("\n请拖入视频或图片（也可以拖文件夹批量处理）：").strip().strip('"')
            if s and Path(s).exists():
                src = Path(s).resolve()
                break
            tries += 1
            if (not s) or tries >= 3:
                print("  未提供有效文件，退出。")
                return 0
            print("  文件不存在，请重试。")

    # 图片 / 文件夹 → 走图片模式
    if src.is_dir() or src.suffix.lower() in IMG_EXTS:
        return image_mode(src, cfg)

    dur, fps = ffprobe_info(src)
    if dur <= 0:
        print("  无法读取视频信息，退出。")
        _rd("按回车退出...")
        return 1
    print(f"\n输入：{src.name}")
    print(f"时长：{dur:.1f} 秒    原始帧率：{fps:g} fps    大小：{src.stat().st_size/1048576:.1f} MB")

    # 模型
    srm = sr_models()
    rm = rife_models()
    if not srm:
        print("\n[警告] bin\\models 里没有找到超分模型，将使用默认模型名。")
        srm = {"realesr-animevideov3": {2, 3, 4}}
    if not rm:
        print("\n[警告] 没有找到 RIFE 模型目录，将使用默认模型名。")
        rm = ["rife-v4.6"]

    sr_names = sort_sr(list(srm.keys()))
    ri_names = list(rm)
    d_sr = sr_names.index(cfg["sr_model"]) if cfg["sr_model"] in sr_names else 0
    d_ri = ri_names.index(cfg["rife_model"]) if cfg["rife_model"] in ri_names else 0

    print()
    print("—— 参数设置（直接回车用默认）——")
    print(f"  当前默认：超分 {sr_names[d_sr]} ×{cfg['sr_scale']} ｜ 补帧 {ri_names[d_ri]} ×{cfg['rife_mul']} ｜ 输出 {cfg['target']}p")

    if (not auto) and ask("\n是否修改参数？(y/N)：", "n").lower().startswith("y"):
        labels = []
        for n in sr_names:
            sc = "/".join(str(x) for x in sorted(srm[n]))
            d = MODEL_DESC.get(n, "")
            labels.append(f"{n}（{d}｜可用 ×{sc}）")
        pick = choose("超分模型（越靠上越快；AI 生成的片子选第 1 个）：", labels, d_sr)
        cfg["sr_model"] = sr_names[labels.index(pick)]
        avail = sorted(srm[cfg["sr_model"]])
        scale_labels = ["0（跳过超分，只用 ffmpeg 缩放）"] + [f"{x}（放大 {x} 倍）" for x in avail]
        d_sc = 0
        for i, lb in enumerate(scale_labels):
            if lb.split("（")[0].strip() == str(cfg["sr_scale"]):
                d_sc = i
                break
        pick_s = choose("超分倍数（0＝跳过 AI 超分；源已是 1080p/4K 就选 0）：", scale_labels, d_sc)
        cfg["sr_scale"] = int(pick_s.split("（")[0].strip())
        rlabels = [f"{n}（{MODEL_DESC.get(n, '')}）" for n in ri_names]
        pick_r = choose("补帧模型（拿不准就用 rife-v4.6）：", rlabels, d_ri)
        cfg["rife_model"] = ri_names[rlabels.index(pick_r)]
        cfg["rife_mul"] = int(choose("补帧倍数：", ["2", "3", "4"],
                                     ["2", "3", "4"].index(str(cfg["rife_mul"])) if str(cfg["rife_mul"]) in ["2", "3", "4"] else 0))
        cfg["target"] = choose("输出分辨率：", ["1080", "720", "原始（只按倍数放大）"], 0)
        if cfg["target"] not in ("1080", "720", "原始（只按倍数放大）"):
            cfg["target"] = "1080"
        cfg["crf"] = int(ask(f"画质 CRF [14-20，默认 {cfg['crf']}]：", cfg["crf"], int))
        cfg["chunk_sec"] = int(ask(f"每段处理秒数 [5-30，默认 {cfg['chunk_sec']}]：", cfg["chunk_sec"], int))
        cfg["auto_clean"] = ask(f"自动清理缓存（每段编码完就删中间帧，省硬盘）(Y/n，默认 {'Y' if cfg.get('auto_clean', True) else 'N'})：",
                                "y" if cfg.get("auto_clean", True) else "n").lower().startswith("y")
        if str(cfg.get("sr_model", "")).startswith("realcugan"):
            lv = cugan_levels(cfg["sr_model"], cfg["sr_scale"])
            lbl = {-1: "-1（不降噪·保留噪点）", 0: "0（保守·最轻）", 1: "1（轻）", 2: "2（中）", 3: "3（强）"}
            labels_lv = [lbl.get(x, str(x)) for x in lv]
            d_lv = lv.index(int(cfg.get("rc_noise", 1))) if int(cfg.get("rc_noise", 1)) in lv else 0
            pick_lv = choose(f"Real-CUGAN 降噪档（{cfg['sr_model']} 在 ×{cfg['sr_scale']} 下可用的只有这些）：", labels_lv, d_lv)
            cfg["rc_noise"] = lv[labels_lv.index(pick_lv)]
        print("\n  —— 后处理（会变慢一点，但专治 AI 素材的毛病）——")
        cfg["pp_deband"] = int(ask("  去色带 deband（0 关 / 1 轻 / 2 中）：", cfg.get("pp_deband", 1), int))
        cfg["pp_deblock"] = int(ask("  去压缩块 deblock（0 关 / 1 开）：", cfg.get("pp_deblock", 0), int))
        cfg["pp_cas"] = ask("  锐化 cas（0 关 / 0.3 轻 / 0.6 中）：", str(cfg.get("pp_cas", 0.3)), float)
        print("\n  —— 放大算法（超分倍数=0 时生效；有 AI 超分时只影响最后一步缩放）——")
        cfg["scale_algo"] = int(choose("  放大算法：",
            ["1 lanczos（锐·有轻微振铃）",
             "2 spline36（平滑·振铃少·推荐）",
             "3 bicubic（最柔·绝不出光晕）",
             "4 lanczos 超采样（先 3 倍再缩·最干净·慢）",
             "5 ewa_lanczossharp（libplacebo·传统最强·较慢）"],
            {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}.get(int(cfg.get("scale_algo", 2)), 1)).split()[0])
        print("\n  —— 调色 ——")
        cfg["lut"] = int(ask("  调色 LUT（0 无 / 1 灰黑重工业 / 2 冷蓝档案 / 3 暖橙工业 / 4 阴天纪实 / 5 自定义）：", cfg.get("lut", 1), int))
        if int(cfg.get("lut", 0)) == 5:
            print("    —— 自定义调色（1.0 = 不变）——")
            cfg["lut_contrast"] = ask("    对比度 0.80-1.30（默认 1.08）：", cfg.get("lut_contrast", 1.08), float)
            cfg["lut_sat"] = ask("    饱和度 0.50-1.20（默认 0.85）：", cfg.get("lut_sat", 0.85), float)
            cfg["lut_lift"] = ask("    抬黑 0.00-0.05（默认 0.010）：", cfg.get("lut_lift", 0.010), float)
            cfg["lut_shoulder"] = ask("    高光滚降 0.00-0.60（默认 0.25）：", cfg.get("lut_shoulder", 0.25), float)
            cfg["lut_temp"] = ask("    色温 -0.05~+0.05（负=冷，默认 -0.008）：", cfg.get("lut_temp", -0.008), float)
        cfg["grain"] = int(ask("  胶片颗粒（0 关 / 1 轻 / 2 中）：", cfg.get("grain", 1), int))
        cfg["gpu"] = ask(f"GPU 编号 [auto=自动，或 0/1/2，默认 {cfg['gpu']}]：", cfg["gpu"], str)
        save_cfg(cfg)

    out_fps = fps * int(cfg["rife_mul"])
    target = cfg["target"]
    ALGO = {1: "lanczos", 2: "spline36", 3: "bicubic", 4: "supersample", 5: "ewa_lanczossharp"}
    algo = int(cfg.get("scale_algo", 2))
    if algo not in ALGO:
        algo = 2
    if target == "1080":
        TW, TH = 1920, 1080
    elif target == "720":
        TW, TH = 1280, 720
    else:
        TW, TH = 0, 0

    if TW == 0:
        scale_vf = None
    elif algo == 1:
        scale_vf = f"scale={TW}:{TH}:flags=lanczos"
    elif algo == 2:
        scale_vf = f"format=yuv420p,zscale=w={TW}:h={TH}:filter=spline36"
    elif algo == 3:
        scale_vf = f"format=yuv420p,zscale=w={TW}:h={TH}:filter=bicubic"
    elif algo == 4:
        scale_vf = f"format=yuv420p,scale={TW*3}:{TH*3}:flags=lanczos,zscale=w={TW}:h={TH}:filter=spline36"
    else:
        scale_vf = (f"format=yuv420p,libplacebo=w={TW}:h={TH}:"
                    f"upscaler=ewa_lanczossharp:antiringing=0.95")

    OUTDIR.mkdir(exist_ok=True)
    LOGDIR.mkdir(exist_ok=True)
    WORKROOT.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    work = WORKROOT / f"{src.stem}_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    global CURRENT_WORK
    CURRENT_WORK = work
    logp = LOGDIR / f"{src.stem}_{stamp}.log"
    logf = open(logp, "w", encoding="utf-8")

    out = OUTDIR / f"_tmp_{src.stem}_{stamp}.mp4"

    print()
    if int(cfg.get("sr_scale", 0)) == 0:
        print("  超分：跳过（只用 ffmpeg 缩放）")
    else:
        print(f"  超分：{cfg['sr_model']} ×{cfg['sr_scale']}")
    print(f"  补帧：{cfg['rife_model']} ×{cfg['rife_mul']}  →  {fps:g} → {out_fps:g} fps")
    print(f"  输出：{target}  |  CRF {cfg['crf']}  |  每段 {cfg['chunk_sec']} 秒  |  自动清理：{'开' if cfg.get('auto_clean', True) else '关'}")
    print(f"  后处理：deband={cfg.get('pp_deband', 0)}  deblock={cfg.get('pp_deblock', 0)}  cas={cfg.get('pp_cas', 0)}")
    print(f"  调色：LUT={LUT_NAMES.get(int(cfg.get('lut', 0)), '无')}  颗粒={cfg.get('grain', 0)}  放大={ALGO.get(algo, 'spline36')}")
    print(f"  成片：{out}")
    print(f"  日志：{logp}")
    lut_rel = None
    lutv = int(cfg.get("lut", 0))
    if lutv == 5:
        try:
            gen_custom_lut({
                "contrast": cfg.get("lut_contrast", 1.08),
                "sat": cfg.get("lut_sat", 0.85),
                "lift": cfg.get("lut_lift", 0.010),
                "shoulder": cfg.get("lut_shoulder", 0.25),
                "temp": cfg.get("lut_temp", -0.008),
            }, work / "custom_grade.cube")
            lut_rel = "custom_grade.cube"
        except Exception as e:
            print(f"  [提示] 自定义 LUT 生成失败：{e}")
    elif lutv in LUT_FILES:
        src_lut = LUTDIR / LUT_FILES[lutv]
        if src_lut.exists():
            try:
                shutil.copy2(src_lut, work / "grade.cube")
                lut_rel = "grade.cube"
            except Exception:
                lut_rel = None
        else:
            print(f"  [提示] 找不到 LUT：{src_lut}")

    if auto or not ask("\n开始处理？(Y/n)：", "y").lower().startswith("n"):
        pass
    else:
        print("已取消。")
        _rd("按回车退出...")
        return 0

    t0 = time.time()
    chunks = []
    plan = plan_chunks(dur, float(cfg["chunk_sec"]), fps)
    n_chunk = len(plan)
    for s0, l0 in plan:
        pass
    gpu_args = []
    gs = str(cfg.get("gpu", "auto")).strip().lower()
    if gs in ("auto", "自动", ""):
        gpu_args = []
    else:
        try:
            gpu_args = ["-g", str(int(gs))]
        except Exception:
            gpu_args = []

    for ci, (start, length) in enumerate(plan):
        cdir = work / f"c{ci:03d}"
        fr = cdir / "frames"
        up = cdir / "up"
        itp = cdir / "interp"
        for d in (fr, up, itp):
            d.mkdir(parents=True, exist_ok=True)

        print()
        print(f"[段 {ci+1}/{n_chunk}]  {start:.1f}s - {start+length:.1f}s")

        # 1 抽帧
        rc = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                  "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}",
                  "-fps_mode", "cfr", "-r", f"{fps:.6f}",
                  "-qscale:v", "1", "-qmin", "1", "-qmax", "1",
                  str(fr / "%06d.png")], logf)
        if rc != 0:
            show_fail("抽帧")
            return 2
        n = count(fr)
        if n == 0:
            continue
        print(f"  抽帧 {n} 帧")

        # 2 超分（倍数 0 = 跳过）
        if int(cfg.get("sr_scale", 2)) == 0:
            up = fr
            print("  跳过超分（直接用原帧）")
        else:
            print("  超分中...", end="", flush=True)
            mdl = str(cfg["sr_model"])
            if mdl.startswith("realcugan"):
                mp = "models-pro" if mdl.endswith("-pro") else "models-se"
                lv = int(cfg.get("rc_noise", 1))
                if not cugan_param_ok(mdl, cfg["sr_scale"], lv):
                    avail = cugan_levels(mdl, cfg["sr_scale"])
                    best = min(avail, key=lambda x: abs(x - lv)) if avail else -1
                    print(f"  [提示] 该模型没有降噪档 {lv}，自动改用 {best}")
                    lv = best
                rc = run_engine(CUGAN_EXE, ["-i", str(fr), "-o", str(up), "-m", mp,
                                           "-n", str(lv),
                                           "-s", str(cfg["sr_scale"]), "-f", "png"], gpu_args, logf)
            else:
                rc = run_engine(SR_EXE, ["-i", str(fr), "-o", str(up), "-n", mdl,
                                         "-s", str(cfg["sr_scale"]), "-f", "png"], gpu_args, logf)
            if rc != 0:
                show_fail("超分")
                return 2
            normalize_sequence(up)
            print(f"\r  超分完成 {count(up)} 帧")

        # 3 补帧
        n_up = count(up)
        if n_up < 2:
            print(f"  本段只有 {n_up} 帧，跳过补帧，直接沿用原帧")
            for q in sorted(up.glob("*.png")):
                shutil.copy2(str(q), str(itp / q.name))
            normalize_sequence(itp)
            ni = count(itp)
            print(f"  本段 {ni} 帧（未插帧）")
        else:
            print("  补帧中...", end="", flush=True)
            rm = str(cfg["rife_model"])
            mul = int(cfg["rife_mul"])
            # 只有 rife-v4 系列支持自定义帧数（-n）；老模型只会固定 2 倍
            if rm.lower().startswith("rife-v4"):
                target_frames = max(n_up, int(round(n_up * float(mul))))
                rife_args = ["-i", str(up), "-o", str(itp), "-m", rm, "-n", str(target_frames)]
            else:
                if mul != 2:
                    print(f"  [提示] {rm} 只支持固定 2 倍，已按 ×2 处理（要 ×{mul} 请换 rife-v4.6）")
                    cfg["rife_mul"] = 2
                rife_args = ["-i", str(up), "-o", str(itp), "-m", rm]
            rc = run_engine(RIFE_EXE, rife_args, gpu_args, logf)
            if rc != 0:
                show_fail("补帧")
                return 2
            normalize_sequence(itp)
            ni = count(itp)
            print(f"\r  补帧完成 {ni} 帧")

        # 4 编码本段
        cfile = work / f"chunk_{ci:03d}.mp4"
        enc_bin = FFMPEG_PL if (algo == 5 and FFMPEG_PL.exists()) else FFMPEG
        if algo == 5 and not FFMPEG_PL.exists():
            print("  [提示] 找不到 ffmpeg_pl.exe，回退到普通 ffmpeg")
        enc = [enc_bin, "-hide_banner", "-loglevel", "error", "-y",
               "-framerate", f"{out_fps:g}", "-start_number", "1",
               "-i", str(itp / "%08d.png"),
               "-c:v", "libx264", "-preset", "medium", "-crf", str(cfg["crf"]),
               "-pix_fmt", "yuv420p"]
        vf_list = []
        db = int(cfg.get("pp_deband", 0))
        if db == 1:
            vf_list.append("deband=1thr=0.008:2thr=0.008:3thr=0.008:4thr=0.008")
        elif db >= 2:
            vf_list.append("deband=1thr=0.02:2thr=0.02:3thr=0.02:4thr=0.02")
        if int(cfg.get("pp_deblock", 0)) >= 1:
            vf_list.append("deblock=filter=weak:block=8")
        if lut_rel:
            vf_list.append(f"lut3d=file={lut_rel}:interp=trilinear")
        if scale_vf:
            vf_list.append(scale_vf)
        cas_v = float(cfg.get("pp_cas", 0) or 0)
        if cas_v > 0:
            vf_list.append(f"cas={cas_v:g}")
        gr = int(cfg.get("grain", 0) or 0)
        if gr == 1:
            vf_list.append("noise=alls=6:allf=t+u")
        elif gr >= 2:
            vf_list.append("noise=alls=11:allf=t+u")
        if vf_list:
            enc += ["-vf", ",".join(vf_list)]
        enc += [str(cfile)]
        rc = run(enc, logf, cwd=str(work))
        if rc != 0:
            show_fail("编码")
            return 2
        chunks.append(cfile)
        if cfg.get("auto_clean", True):
            shutil.rmtree(cdir, ignore_errors=True)
            print(f"  本段完成（{time.time()-t0:.0f}s 已用，缓存已自动清理）")
        else:
            print(f"  本段完成（{time.time()-t0:.0f}s 已用）")

    if not chunks:
        print("没有产出任何片段。")
        return 2

    # 拼接
    print()
    print("拼接中...")
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in chunks), encoding="utf-8")
    silent = work / "video_only.mp4"
    rc = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
              "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent)], logf)
    if rc != 0:
        print("拼接失败，见日志。")
        return 2

    # 接音轨
    print("接回原音轨...")
    rc = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
              "-i", str(silent), "-i", str(src),
              "-map", "0:v:0", "-map", "1:a:0?",
              "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
              "-shortest", str(out)], logf)
    if rc != 0:
        print("音轨合并失败，改用无声成片。")
        shutil.copy2(silent, out)

    logf.close()
    try:
        gb = Path(out).stat().st_size / (1024 ** 3)
        name = f"{time.strftime('%m_%d_%H%M')}_{gb:.2f}GB_{sr_abbr(cfg['sr_model'], cfg['sr_scale'])} x{int(cfg['sr_scale'])}_x{int(cfg['rife_mul'])}.mp4"
        final = Path(out).with_name(name)
        n = 2
        while final.exists():
            final = Path(out).with_name(name.replace(".mp4", f"_{n}.mp4"))
            n += 1
        Path(out).replace(final)
        out = final
    except Exception:
        pass
    print()
    hr()
    print("  完成！")
    print(f"  成片：{out}")
    print(f"  用时：{time.time()-t0:.0f} 秒")
    hr()

    if cfg.get("auto_clean", True):
        shutil.rmtree(work, ignore_errors=True)
        print("\n  缓存已自动清理（work 目录已清空）。")
    else:
        if ask("\n删除中间文件（frames/up/interp）？(Y/n)：", "y").lower().startswith("y"):
            shutil.rmtree(work, ignore_errors=True)
            print("  已清理。")

    _rd("\n按回车退出...")
    return 0


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    except KeyboardInterrupt:
        print("\n\n  已中断（Ctrl+C）。")
        try:
            if CURRENT_PROC is not None and CURRENT_PROC.poll() is None:
                print("  停止引擎...", end="", flush=True)
                CURRENT_PROC.terminate()
                for _ in range(20):
                    if CURRENT_PROC.poll() is not None:
                        break
                    time.sleep(0.1)
                if CURRENT_PROC.poll() is None:
                    CURRENT_PROC.kill()
                print(" 已停。", flush=True)
        except Exception:
            pass
        if CURRENT_WORK is not None and Path(CURRENT_WORK).exists():
            print("  正在清理本次缓存...")
            ok = False
            for _ in range(5):
                shutil.rmtree(CURRENT_WORK, ignore_errors=True)
                if not Path(CURRENT_WORK).exists():
                    ok = True
                    break
                time.sleep(0.6)
            print("  本次缓存已清理。" if ok else "  部分缓存被占用，下次启动会自动清理。")
        code = 130
    except Exception:
        import traceback
        traceback.print_exc()
        code = 1
    if code:
        _rd("\n按回车退出...")
    sys.exit(code)
