# 超分辨（Chaofenbian）

视频超分 + 补帧 + 图片超分，Windows 下开箱即用，全中文界面，纯本地运行。

[![GitHub stars](https://img.shields.io/github/stars/acev500/ADCE?style=social)](https://github.com/acev500/ADCE)
[![License](https://img.shields.io/badge/license-MIT%20%2B%20third--party-blue)](https://github.com/acev500/ADCE)

---

# 🔽 下载安装

## 不会技术的，照着下面四步做

### 第 1 步 · 点这个链接下载

### 👉 **[点我下载安装包](https://github.com/acev500/ADCE/releases/latest)**

打开后是一个英文页面，找文件名 **`Chaofenbian-v1.2-Setup.exe`**，点它。

```
文件大小   321 MB
下载耗时   视网速而定，慢的话十几分钟
```

### 第 2 步 · 双击那个 exe

Windows 可能会弹出蓝色的「Windows 已保护你的电脑」：

```
点「更多信息」→ 点「仍要运行」
```

这不是病毒，是因为个人开发者买不起代码签名证书（一年几千块），所有没签名的程序都会这么提示。

### 第 3 步 · 选个安装位置

弹窗里选一个文件夹，**建议装在 D 盘**，比如 `D:\超分辨`。点确定。

等一两分钟，进度条走完会弹出一个黑色的窗口，让它自己跑完。

### 第 4 步 · 装好了，桌面上多了两个图标

```
超分辨              双击打开，把视频或图片拖进窗口
超分辨 命令行        把文件拖到图标上，直接开始处理
```

处理完的结果在**安装目录下的「输出」文件夹**里。

---

## 安装包里有什么

```
超分辨_图形版.exe     图形界面
超分辨.exe            命令行版（支持 --quiet / --json）
bin\                  Real-ESRGAN、Real-CUGAN、RIFE、FFmpeg 与全部模型
lut\                  四套调色 LUT（灰黑重工业 / 冷蓝档案 / 暖橙工业 / 阴天纪实）
使用说明.txt           中文手册
```

解压后约 554 MB，装完可以删掉那个安装包。

## 校验（不放心的话可以核对）

```
SHA256 4F1489006772205D2C75AF122C3A389205DA27A8BFF6030003F7656CA337984F
```

在 PowerShell 里跑：

```powershell
Get-FileHash .\Chaofenbian-v1.2-Setup.exe -Algorithm SHA256
```

两个值一样就说明文件没被篡改。

---

## 系统要求

| 项目 | 要求 |
|---|---|
| 系统 | Windows 10 / 11（64 位） |
| NVIDIA | GTX 600 系列及以后 |
| AMD | HD 7000 / GCN 架构及以后 |
| Intel | HD 4000 核显及以后 |
| 纯 CPU | **不支持**（引擎依赖 Vulkan，必须用显卡） |

需要安装对应显卡的最新驱动。嵌入式设备（如 ESP32、树莓派）不适用。

---

## 从源码运行（给会用命令行的）

```bash
git clone https://github.com/acev500/ADCE.git
cd ADCE
```

然后按下面的「快速开始」准备 `bin\` 目录。

---

![界面](界面截图.png)

---

## 功能

| 功能 | 说明 |
|---|---|
| 视频超分 | 2/3/4 倍放大，可选 Real-ESRGAN（通用/动漫/写实）或 Real-CUGAN（保守，不易重画人脸） |
| 视频补帧 | RIFE 2/3/4 倍插帧（24 → 48 / 72 / 96 fps） |
| 图片超分 | 单张或整个文件夹批量，输出 PNG 无损 |
| 后处理 | 去色带 deband、去压缩块 deblock、锐化 CAS |
| 调色 | 三套内置 LUT（灰黑重工业 / 冷蓝档案 / 暖橙工业）+ 自定义参数 |
| 分段处理 | 长视频按段拆开再合并，控制磁盘占用 |
| 无头调用 | 支持 `--quiet` / `--json` / 指定参数，方便脚本和批量流水线 |

---

## 快速开始

### 1. 准备 `bin\`（**必须**，不放仓库）

`bin\` 里是引擎和模型，加起来 500 MB 以上，不进 Git。自己下好放进去：

```
bin\
  realesrgan-ncnn-vulkan.exe          https://github.com/xinntao/Real-ESRGAN/releases
  realcugan-ncnn-vulkan.exe           https://github.com/nihui/realcugan-ncnn-vulkan/releases
  rife-ncnn-vulkan.exe                https://github.com/nihui/rife-ncnn-vulkan/releases
  ffmpeg.exe                          https://www.gyan.dev/ffmpeg/builds/  （或 BtbN 的静态版）
  vcomp140.dll / vcomp140d.dll        （ncnn 运行库，引擎包里通常自带）
  models\                             超分模型（*.param + *.bin）
  models-pro\ models-se\              Real-CUGAN 模型
  rife-v4.6\ rife-anime\ rife-HD\ rife-UHD\   补帧模型
```

模型文件从对应引擎的 release 包里拿，解压到同名目录即可。

### 2. 用图形版

双击 `超分辨_图形版.exe`。

**最上面先选「处理对象」**：视频或图片，选哪个下面就只显示哪一套参数。

```
处理对象   ○ 视频（超分 + 补帧）      ● 图片（只超分，不补帧）
```

### 3. 用命令行版

```
超分辨.exe D:\video\a.mp4
```

拖文件到 exe 图标上也行。交互式会问你参数，直接回车走默认。

---

## 无头调用（脚本 / 批处理 / CI）

```bash
# 视频：静默，指定模型、倍数、输出目录
超分辨.exe D:\in\a.mp4 --quiet --model realesr-animevideov3 --scale 2 --mul 2 --out D:\out

# 图片：单张放大 4 倍
超分辨.exe D:\in\pic.png --quiet --scale 4 --out D:\out

# 图片：整个文件夹批量，结果用 JSON 回给脚本
超分辨.exe D:\in\imgs --json --scale 2
```

`--json` 会在结束时往 stdout 打一行 JSON：

```json
{"ok": true, "type": "image", "done": 3, "total": 3,
 "out_dir": "D:\\out",
 "outputs": ["D:\\out\\a_up2x.png", "D:\\out\\b_up2x.png", "D:\\out\\c_up2x.png"],
 "seconds": 4.21,
 "log": "D:\\超分辨\\日志\\img_imgs_20261114_122236.log"}
```

退出码：`0` 成功，`2` 有文件失败，`1` 环境/参数错误。

### 参数表

| 参数 | 说明 |
|---|---|
| `--auto` | 无交互，全部用 `config.json` 里存的参数 |
| `--quiet` | 静默，不打印参数菜单（隐含 `--auto`） |
| `--json` | 结束时输出一行 JSON（隐含 `--quiet`） |
| `--model NAME` | 超分模型名，如 `realesr-animevideov3` |
| `--scale N` | 放大倍数 2/3/4 |
| `--rife NAME` | 补帧模型名，如 `rife-v4.6` |
| `--mul N` | 补帧倍数 2/3/4 |
| `--target N` | 输出分辨率 `1080` / `720` / `原始` |
| `--crf N` | 画质 CRF，越小越好越大 |
| `--out DIR` | 输出目录（默认 `输出\`） |
| `--help` | 帮助 |

---

## 目录结构

```
超分辨.exe          命令行版
超分辨_图形版.exe    图形版（tkinter）
src\
  chaofenbian.py    命令行主程序（视频 + 图片 + 无头）
  gui.py            图形界面
  installer.py      安装辅助
bin\                引擎与模型（自己准备，见上）
lut\                调色 LUT（.cube）
work\               中间文件（可删）
输出\               成片与超分后的图片
日志\               每次运行的完整日志
config.json         记住的参数（删掉恢复默认）
```

---

## 注意事项

1. **先超分补帧，最后叠字幕**。字幕先烧进去再超分，字会糊。
2. 补帧会让 AI 生成画面的瑕疵更明显，24 → 48 fps 通常够用，别贪。
3. `work\` 会涨到几十 GB，处理完记得清。
4. 中文路径没问题，但路径里别带 `&`、`|` 这类 shell 特殊字符。
5. 图片模式不走 LUT 和颗粒，只做超分；要调色处理完自己叠。

---

## 许可

本仓库代码（`src\`）为自用工具，随便改。

依赖的第三方组件各自许可：

| 组件 | 许可 |
|---|---|
| Real-ESRGAN（realesrgan-ncnn-vulkan） | BSD-3-Clause，可商用 |
| Real-CUGAN（realcugan-ncnn-vulkan） | MIT，可商用 |
| RIFE（rife-ncnn-vulkan） | MIT，可商用 |
| FFmpeg | LGPL / GPL（按构建而定），可商用 |

模型文件版权归各上游项目所有，本仓库不附带。

---

## 更新记录

- **v1.2** 图形版顶部加「处理对象」切换；补 `BASE` 路径判定
- **v1.1** 加入图片超分（单张 + 文件夹批量）
- **v1.0** 视频超分 + 补帧
