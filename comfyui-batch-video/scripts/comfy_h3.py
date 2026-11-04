# -*- coding: utf-8 -*-
"""ComfyUI MiniMax-H3 文生视频客户端库。

封装：提示词构建 -> /prompt 提交 -> /history 轮询 -> /view 下载 -> ffprobe/抽帧/字幕检测。
所有函数通过 cfg 字典传参，cfg 由 load_config() 合并默认值与用户配置得到。
"""
import json, os, subprocess, tempfile, time, urllib.error, urllib.parse, urllib.request

# ---------------------------------------------------------------- 默认配置
DEFAULTS = {
    "base": "http://127.0.0.1:8200",
    "client_id": "wb-h3-producer",
    "ffprobe": "",
    "ffmpeg": "",
    # 已验证的生成参数（MiniMax-H3 + Pika turbo 8step LoRA，纯文生视频）
    "width": 736,
    "height": 1312,
    "length": 124,
    "fps": 24,
    "seed": 20261030,
    "sampler": "lcm",
    "sigmas": "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0",
    "models": {
        "unet": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "lora": "pika_h3_flex_turbo_8step_hd_fl2va.safetensors",
        "clip": "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors",
        "clip_type": "minimax",
        "vae_video": "minimax_h3_video_vae_int8_convrot.safetensors",
        "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
        "vae_sol": "minimax_h3_sol_vae_int8_convrot.safetensors",
    },
    "attention": {
        "selection": "sol-attn",
        "selection.tau": 1.3,
        "start_percent": 0.0,
        "end_percent": 1.0,
        "dense_blocks": "",
        "min_tokens": 12288,
        "extra_tokens": 256,
        "sink_conditioning": "exact_kv_and_rows",
        "verbose": False,
    },
    "filename_prefix": "video/Pika_H3_Flex_T2V",
    "timeout_sec": 2400,
    "poll_sec": 5,
    # 验收阈值
    "expect_dur": [4.5, 6.0],
    "expect_aspect": [0.54, 0.58],   # w/h，9:16≈0.5625
    "subtitle_rows_max": 2,          # >=2 判定为画面含文字
    "subtitle_samples": [0.8, 1.6, 2.4, 3.2, 4.0, 4.8],
}

# 强化"画面禁止出现文字"的约束（模型偶尔会把台词烧成字幕）
STRONG_NO_TEXT = (
    "\n\nIMPORTANT: Absolutely no subtitles, no captions, no on-screen text, no written words, "
    "no letters, no numbers, no signs, no labels, no logos, no watermarks anywhere in the frame. "
    "The dialogue is spoken audio only and must never appear as visible text on screen. "
    "Keep the image completely free of any text-like graphic."
)
BASE_NO_TEXT = "\n\nNo subtitles, no visible text, no logos."


def load_config(path=None):
    cfg = json.loads(json.dumps(DEFAULTS))
    if path and os.path.exists(path):
        user = json.load(open(path, encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    _resolve_ffmpeg(cfg)
    return cfg


def _resolve_ffmpeg(cfg):
    """ffmpeg/ffprobe 缺失时自动探测：PATH -> ComfyUI 便携版常见路径。"""
    import shutil
    if not cfg.get("ffmpeg"):
        cfg["ffmpeg"] = shutil.which("ffmpeg") or ""
    if not cfg.get("ffprobe"):
        cfg["ffprobe"] = shutil.which("ffprobe") or ""
    candidates = [
        r"N:\ComfyUI_portable_TE_v260619\python_embeded\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg.exe",
        r"N:\ComfyUI_portable_TE_v260619\python_embeded\Lib\site-packages\torchcodec\ffprobe.exe",
    ]
    if not cfg["ffmpeg"]:
        for c in candidates:
            if "ffmpeg" in c and os.path.exists(c):
                cfg["ffmpeg"] = c
                break
    if not cfg["ffprobe"]:
        for c in candidates:
            if "ffprobe" in c and os.path.exists(c):
                cfg["ffprobe"] = c
                break


# ---------------------------------------------------------------- 提示词
def build_text(item, strong=False):
    """把四段式素材拼成单节点提示词。字段：integrated / soundscape / music / voice / dialogue。"""
    t = (item["integrated"]
         + "\n\noverall_soundscape\n" + item["soundscape"]
         + "\n\nnon_diegetic_music\n" + item["music"]
         + "\n\nvoiceover\nLanguage: Mandarin Chinese.\nVoice: " + item["voice"]
         + "\nDialogue: \"" + item["dialogue"] + "\""
         + BASE_NO_TEXT)
    return t + STRONG_NO_TEXT if strong else t


def build_prompt(cfg, text):
    """构建 /prompt 需要的 API 格式图（节点 id 与已验证工作流一致）。"""
    m, a = cfg["models"], cfg["attention"]
    w, h, ln = cfg["width"], cfg["height"], cfg["length"]
    return {
        "2": {"class_type": "UNETLoader", "inputs": {"unet_name": m["unet"], "weight_dtype": "default"}},
        "3": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["2", 0], "lora_name": m["lora"], "strength_model": 1.0}},
        "4": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": m["clip"], "type": m["clip_type"], "device": "default"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae_video"]}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae_audio"]}},
        "17": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae_sol"]}},
        "9": {"class_type": "MiniMaxH3ImageToVideo",
              "inputs": {"clip": ["4", 0], "vae": ["5", 0], "prompt": text,
                         "width": w, "height": h, "length": ln}},
        "10": {"class_type": "BlockSparseAttention", "inputs": dict({"model": ["3", 0]}, **a)},
        "11": {"class_type": "BasicGuider", "inputs": {"model": ["10", 0], "conditioning": ["9", 0]}},
        "12": {"class_type": "RandomNoise", "inputs": {"noise_seed": cfg["seed"]}},
        "13": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": cfg["sampler"]}},
        "14": {"class_type": "ManualSigmas", "inputs": {"sigmas": cfg["sigmas"]}},
        "15": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["12", 0], "guider": ["11", 0], "sampler": ["13", 0],
                          "sigmas": ["14", 0], "latent_image": ["9", 1]}},
        "16": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["15", 0], "vae": ["6", 0]}},
        "18": {"class_type": "VAEDecode", "inputs": {"samples": ["15", 0], "vae": ["17", 0]}},
        "19": {"class_type": "CreateVideo",
               "inputs": {"images": ["18", 0], "audio": ["16", 0], "fps": cfg["fps"],
                          "bit_depth": "auto", "color_space": "sRGB",
                          "chroma_subsampling": "auto", "codec": "auto"}},
        "20": {"class_type": "SaveVideo",
               "inputs": {"video": ["19", 0], "filename_prefix": cfg["filename_prefix"],
                          "format": "auto", "format.codec": "auto", "codec": "auto"}},
    }


# ---------------------------------------------------------------- HTTP
def _get(cfg, path, timeout=30):
    return json.load(urllib.request.urlopen(cfg["base"] + path, timeout=timeout))


def server_ready(cfg):
    try:
        return _get(cfg, "/system_stats", 10)
    except Exception as e:
        return {"error": str(e)}


def queue_state(cfg):
    q = _get(cfg, "/queue", 15)
    return {"running": len(q.get("queue_running", [])), "pending": len(q.get("queue_pending", []))}


def post_prompt(cfg, prompt):
    data = json.dumps({"prompt": prompt, "client_id": cfg["client_id"]}).encode()
    req = urllib.request.Request(cfg["base"] + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=30)), None
    except urllib.error.HTTPError as e:
        # ComfyUI 会在入队前校验节点与模型，错误信息直接给出缺哪个模型
        return None, "HTTP %d: %s" % (e.code, e.read().decode(errors="replace")[:3000])
    except Exception as e:
        return None, "submit:" + str(e)


def wait_done(cfg, pid):
    t0 = time.time()
    while time.time() - t0 < cfg["timeout_sec"]:
        try:
            h = _get(cfg, "/history/" + pid, 30)
        except Exception:
            time.sleep(cfg["poll_sec"]); continue
        if pid in h:
            rec = h[pid]; st = rec.get("status", {})
            if st.get("completed") or st.get("status_str") in ("success", "error"):
                return rec, None
        time.sleep(cfg["poll_sec"])
    return None, "timeout(%ss)" % cfg["timeout_sec"]


def find_video(rec):
    for _, out in rec.get("outputs", {}).items():
        for key in ("images", "video", "gifs", "videos"):
            for f in out.get(key, []) or []:
                if isinstance(f, dict) and f.get("filename", "").lower().endswith((".mp4", ".webm", ".mov")):
                    return f
    return None


def download(cfg, f, dest):
    q = urllib.parse.urlencode({"filename": f["filename"],
                                "subfolder": f.get("subfolder", ""),
                                "type": f.get("type", "output")})
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(cfg["base"] + "/view?" + q, timeout=300) as r, open(dest, "wb") as w:
        w.write(r.read())


# ---------------------------------------------------------------- 验收
def ffprobe(cfg, path):
    try:
        out = subprocess.check_output(
            [cfg["ffprobe"], "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path], timeout=90)
        j = json.loads(out)
        v = next((s for s in j["streams"] if s.get("codec_type") == "video"), {})
        a = next((s for s in j["streams"] if s.get("codec_type") == "audio"), None)
        return {"dur": round(float(j["format"].get("duration", 0)), 2),
                "w": v.get("width"), "h": v.get("height"), "fps": v.get("r_frame_rate"),
                "vcodec": v.get("codec"), "has_audio": a is not None,
                "acodec": a.get("codec") if a else None}
    except Exception as e:
        return {"error": str(e)}


def grab_frame(cfg, path, t, out_png):
    subprocess.run([cfg["ffmpeg"], "-y", "-ss", str(t), "-i", path, "-frames:v", "1", out_png],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    return out_png if os.path.exists(out_png) else None


def frame_check(cfg, path, dur):
    """抽 3 帧，检测黑屏与静态画面（缩到 64x64 比亮度与帧差）。"""
    try:
        from PIL import Image
        tmp = tempfile.mkdtemp()
        frames = []
        for i, t in enumerate([0.4, max(0.5, dur * 0.5), max(0.5, dur - 0.4)]):
            fp = os.path.join(tmp, "f%d.png" % i)
            if grab_frame(cfg, path, t, fp):
                im = Image.open(fp).convert("L").resize((64, 64))
                frames.append(list(im.getdata()))
        if len(frames) < 2:
            return {"ok": False, "reason": "frames_extract_fail"}
        mean = lambda fr: sum(fr) / len(fr)
        diff = lambda a, b: sum(abs(x - y) for x, y in zip(a, b)) / len(a)
        means = [round(mean(f), 1) for f in frames]
        diffs = [round(diff(frames[i], frames[i + 1]), 2) for i in range(len(frames) - 1)]
        black = all(m < 8 for m in means)
        static = all(d < 1.0 for d in diffs)
        return {"ok": not black and not static, "brightness": means,
                "frame_diff": diffs, "black": black, "static": static}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _subtitle_rows_pil(path):
    """无 numpy 时的退化实现：统计下部区域的亮暗强反差行。"""
    from PIL import Image
    im = Image.open(path).convert("L")
    W, H = im.size
    px = im.load()
    y0, y1 = int(H * 0.55), int(H * 0.95)
    x0, x1 = int(W * 0.04), int(W * 0.96)
    bw = x1 - x0
    best = run = 0
    for y in range(y0, y1):
        tr = br = 0
        prev = px[x0, y]
        prev_b = prev >= 215
        prev_d = prev <= 110
        for x in range(x0 + 1, x1):
            v = px[x, y]
            b = v >= 215; d = v <= 110
            if (b and prev_d) or (d and prev_b):
                tr += 1
            if b:
                br += 1
            prev_b, prev_d = b, d
        if tr >= 12 and br >= bw * 0.03:
            run += 1; best = max(best, run)
        else:
            run = 0
    return best


def _subtitle_rows_np(path):
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(path).convert("L"), dtype=np.uint8)
    H, W = a.shape
    band = a[int(H * 0.55):int(H * 0.95), int(W * 0.04):int(W * 0.96)].astype(np.int16)
    bright = band >= 215; dark = band <= 110
    tb = (bright[:, 1:] & dark[:, :-1]) | (dark[:, 1:] & bright[:, :-1])
    row_tr = tb.sum(axis=1); row_bright = bright.sum(axis=1)
    bw = band.shape[1]
    cand = (row_tr >= 12) & (row_bright >= bw * 0.03)
    best = run = 0
    for v in cand:
        run = run + 1 if v else 0
        best = max(best, run)
    return int(best)


def subtitle_score(cfg, path, dur=None):
    """返回画面上"文字行"的最长连续行数。>=2 视为含字幕/文字。

    原理：中文字幕是白色字形+深色描边，在画面下部形成大量亮暗强反差跳变，
    且这些跳变集中在连续若干行内。纯画面内容极少同时满足"高跳变+高亮占比+连续行"。
    """
    try:
        fn = _subtitle_rows_np
        try:
            import numpy  # noqa: F401
        except ImportError:
            fn = _subtitle_rows_pil
        tmp = tempfile.mkdtemp()
        worst = 0
        for t in cfg["subtitle_samples"]:
            tt = t if dur is None else min(t, max(0.3, dur - 0.2))
            fp = os.path.join(tmp, "s%.1f.png" % t)
            if grab_frame(cfg, path, tt, fp):
                worst = max(worst, fn(fp))
        return worst
    except Exception:
        return -1


def verify(cfg, path):
    """完整验收：文件 -> 探测 -> 帧检 -> 字幕。返回 (ok, detail)。"""
    d = {"file": path, "size": 0}
    if not os.path.exists(path):
        return False, {"reason": "file_missing"}
    d["size"] = os.path.getsize(path)
    if d["size"] < 50000:
        return False, {"reason": "file_too_small", "size": d["size"]}
    info = ffprobe(cfg, path)
    d["probe"] = info
    if "error" in info:
        return False, d
    lo, hi = cfg["expect_dur"]
    ar_lo, ar_hi = cfg["expect_aspect"]
    ar = (info["w"] / info["h"]) if info.get("w") and info.get("h") else 0
    d["aspect"] = round(ar, 4)
    fc = frame_check(cfg, path, info.get("dur", 5))
    d["frame_check"] = fc
    rows = subtitle_score(cfg, path, info.get("dur", 5))
    d["subtitle_rows"] = rows
    ok = (lo <= info.get("dur", 0) <= hi
          and ar_lo <= ar <= ar_hi
          and info.get("has_audio")
          and fc.get("ok")
          and 0 <= rows < cfg["subtitle_rows_max"])
    if not ok:
        d["fail"] = [k for k, bad in [
            ("duration", not (lo <= info.get("dur", 0) <= hi)),
            ("aspect", not (ar_lo <= ar <= ar_hi)),
            ("no_audio", not info.get("has_audio")),
            ("frame_check", not fc.get("ok")),
            ("subtitle", not (0 <= rows < cfg["subtitle_rows_max"])),
        ] if bad]
    return ok, d
