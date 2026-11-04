# -*- coding: utf-8 -*-
"""给竖屏视频加中文字幕（ASS 烧录），并统一成品规格。

默认输出 1080×1920 / 30fps / H.264 + AAC 44.1kHz（与已发布成品一致）：
先 scale+crop 到成品画布，再烧 ASS，避免字号被二次缩放。
源片已是成品规格时加 --no-scale。

两种输入：
  1) --cues cues.json  手工/上游给的 cues：{"cues":[{"start":0.2,"end":1.8,
       "lines":[{"parts":[{"text":"章鱼有"},{"text":"三个心脏","key":true}]}]}]}
  2) --asr asr.json    faster-whisper 结果（含 segments 或 words），自动切行
可选 --head "5秒涨知识" --tail "关注我" 生成片头片尾文字。

只出字幕不烧录：--ass-only。烧录用 ffmpeg，无需额外依赖。
繁转简：装了 opencc 就自动转，没有则跳过（不报错）。
"""
import argparse, json, os, re, subprocess, sys, tempfile

FONT = "Microsoft YaHei"
STYLE = {
    "normal": dict(size=78, c1=(255, 253, 247), c3=(42, 22, 8), bord=7, shad=4),
    "key":    dict(size=96, c1=(255, 210, 74), c3=(58, 32, 0), bord=8, shad=4),
    "head":   dict(size=74, c1=(255, 255, 255), c3=(30, 40, 90), bord=8, shad=4),
    "tail":   dict(size=96, c1=(255, 245, 200), c3=(60, 40, 10), bord=8, shad=4),
}
SAFE_BOTTOM = 420
MARGIN_X = 90


def to_simplified(s):
    try:
        from opencc import OpenCC
    except ImportError:
        return s
    try:
        return OpenCC("t2s").convert(s)
    except Exception:
        return s


def ass_color(rgb):
    r, g, b = rgb
    return "&H00%02X%02X%02X" % (b, g, r)


def ts(t):
    t = max(0.0, t)
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def header(width, height):
    st = STYLE
    return """[Script Info]
ScriptType: v4.00+
PlayResX: %d
PlayResY: %d
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Normal,%s,%d,%s,&H000000FF,%s,&H80000000,1,0,0,0,100,100,0,0,1,%d,%d,2,%d,%d,%d,1
Style: Key,%s,%d,%s,&H000000FF,%s,&H80000000,1,0,0,0,100,100,0,0,1,%d,%d,2,%d,%d,%d,1
Style: Head,%s,%d,%s,&H000000FF,%s,&H80000000,1,0,0,0,100,100,0,0,1,%d,%d,8,%d,%d,60,1
Style: Tail,%s,%d,%s,&H000000FF,%s,&H80000000,1,0,0,0,100,100,0,0,1,%d,%d,2,%d,%d,%d,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" % (
        width, height,
        FONT, st["normal"]["size"], ass_color(st["normal"]["c1"]), ass_color(st["normal"]["c3"]),
        st["normal"]["bord"], st["normal"]["shad"], MARGIN_X, MARGIN_X, SAFE_BOTTOM,
        FONT, st["key"]["size"], ass_color(st["key"]["c1"]), ass_color(st["key"]["c3"]),
        st["key"]["bord"], st["key"]["shad"], MARGIN_X, MARGIN_X, SAFE_BOTTOM,
        FONT, st["head"]["size"], ass_color(st["head"]["c1"]), ass_color(st["head"]["c3"]),
        st["head"]["bord"], st["head"]["shad"], MARGIN_X, MARGIN_X,
        FONT, st["tail"]["size"], ass_color(st["tail"]["c1"]), ass_color(st["tail"]["c3"]),
        st["tail"]["bord"], st["tail"]["shad"], MARGIN_X, MARGIN_X, SAFE_BOTTOM,
    )


def _fade_in(dur_ms=150):
    return r"{\fad(%d,120)\fscx96\fscy96\t(0,%d,\fscx100\fscy100)}" % (dur_ms, dur_ms + 120)


def _bounce(dur_ms=450):
    a = int(dur_ms * 0.40); b = int(dur_ms * 0.70)
    return (r"{\fscx60\fscy60\fad(0,120)\t(0,%d,\fscx118\fscy118\3c&H00FFFFFF)"
            r"\t(%d,%d,\fscx94\fscy94\3c&H003A2000)\t(%d,%d,\fscx102\fscy102)"
            r"\t(%d,%d,\fscx100\fscy100)}" % (a, a, b, b, int(dur_ms * 0.86),
                                              int(dur_ms * 0.86), dur_ms))


def build_ass(cues, width=1080, height=1920, head=None, tail=None, head_time=(0.0, 0.9),
              tail_time=None, video_dur=None):
    out = [header(width, height)]
    for cue in cues:
        text_lines = []
        for line in cue["lines"]:
            seg = ""
            for i, part in enumerate(line["parts"]):
                t = part["text"].replace("\n", "")
                if part.get("key"):
                    seg += r"{\rKey}" + _bounce() + t + r"{\rNormal}"
                else:
                    seg += (_fade_in() if i == 0 else r"{\fad(120,120)}") + t
            text_lines.append(seg)
        out.append("Dialogue: 0,%s,%s,Normal,,%d,%d,%d,,%s" %
                   (ts(cue["start"]), ts(cue["end"]), MARGIN_X, MARGIN_X, SAFE_BOTTOM,
                    r"\N".join(text_lines)))
    if head:
        out.append("Dialogue: 1,%s,%s,Head,,%d,%d,70,,%s%s" %
                   (ts(head_time[0]), ts(head_time[1]), MARGIN_X, MARGIN_X,
                    r"{\fad(150,250)\fscx60\fscy60\t(0,220,\fscx100\fscy100)\t(500,700,\fscx70\fscy70)}",
                    head))
    if tail and tail_time:
        out.append("Dialogue: 0,%s,%s,Tail,,%d,%d,%d,,%s%s" %
                   (ts(tail_time[0]), ts(tail_time[1]), MARGIN_X, MARGIN_X, SAFE_BOTTOM,
                    r"{\fad(200,200)\fscx90\fscy90\t(0,260,\fscx100\fscy100)}", tail))
    return "\n".join(out) + "\n"


def cues_from_asr(asr, max_chars=14, key_words=()):
    """把 faster-whisper 结果切成 cues。优先用 words 词级时间，退化用 segments。"""
    segs = asr.get("segments") or []
    cues = []
    for seg in segs:
        text = to_simplified((seg.get("text") or "").strip())
        if not text:
            continue
        words = seg.get("words") or []
        if words:
            cur, start = [], None
            for w in words:
                wt = to_simplified((w.get("word") or "").strip())
                if not wt:
                    continue
                if start is None:
                    start = w.get("start", seg.get("start", 0))
                cur.append((wt, w.get("end", seg.get("end", 0))))
                if sum(len(x[0]) for x in cur) >= max_chars:
                    cues.append(_mk_cue(cur, start, key_words)); cur, start = [], None
            if cur:
                cues.append(_mk_cue(cur, start, key_words))
        else:
            st, en = seg.get("start", 0), seg.get("end", 0)
            n = max(1, (len(text) + max_chars - 1) // max_chars)
            step = max(0.6, (en - st) / n)
            for i in range(n):
                piece = text[i * max_chars:(i + 1) * max_chars]
                if piece:
                    cues.append({"start": round(st + i * step, 2),
                                 "end": round(min(en, st + (i + 1) * step), 2),
                                 "lines": [{"parts": _split_key(piece, key_words)}]})
    return cues


def _mk_cue(pairs, start, key_words):
    text = "".join(p[0] for p in pairs)
    end = pairs[-1][1]
    return {"start": round(start, 2), "end": round(end, 2),
            "lines": [{"parts": _split_key(text, key_words)}]}


def _split_key(text, key_words):
    if not key_words:
        return [{"text": text}]
    pattern = "(" + "|".join(re.escape(k) for k in key_words) + ")"
    parts = []
    for tok in re.split(pattern, text):
        if not tok:
            continue
        parts.append({"text": tok, "key": tok in key_words})
    return parts or [{"text": text}]


def burn(ffmpeg, video, ass, out, crf=18, preset="medium",
         out_size=None, fps=None, duration=None, scale_flags="lanczos", sharpen=0.5):
    """把 ASS 烧进画面，并统一到成品规格（默认 1080x1920 / 30fps）。

    顺序很重要：先 scale+crop 到成品画布，再烧 ASS，这样 ASS 的 PlayRes
    与画面 1:1 对应，字号不会被二次缩放。字幕滤镜路径需转义（盘符冒号 + 反斜杠）。

    放大策略：源 736x1312 -> 1080x1920 约 1.47 倍，用 lanczos 比默认 bicubic
    锐度约高 8%；再叠 mild unsharp(0.5) 提升边缘观感且不产生白边光晕。
    注意：放大不增加信息量，只是满足平台规格，不是真高清。
    """
    esc = ass.replace("\\", "/").replace(":", "\\:")
    chain = []
    if out_size:
        w, h = out_size
        chain.append("scale=%d:%d:force_original_aspect_ratio=increase:flags=%s" % (w, h, scale_flags))
        chain.append("crop=%d:%d" % (w, h))
        chain.append("setsar=1")
        if sharpen and sharpen > 0:
            chain.append("unsharp=5:5:%.2f:5:5:0.0" % sharpen)
    chain.append("ass='%s'" % esc)
    vf = ",".join(chain)

    cmd = [ffmpeg, "-y", "-i", video, "-vf", vf]
    if fps:
        cmd += ["-r", str(fps)]
    if duration:
        # 精确截断，避免贴纸/字幕序列拖长导致尾部定格
        cmd += ["-t", "%.3f" % duration]
    cmd += ["-c:v", "libx264", "-crf", str(crf), "-preset", preset,
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-b:a", "192k",
            "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0, (r.stderr or "")[-1500:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", default=None, help="输出 mp4；默认同目录 _字幕.mp4")
    ap.add_argument("--cues", default=None)
    ap.add_argument("--asr", default=None)
    ap.add_argument("--ass-out", default=None, help="ASS 保存路径；默认临时文件")
    ap.add_argument("--size", default="1080x1920",
                    help="成品画布，同时作为 ASS 分辨率（默认 1080x1920）")
    ap.add_argument("--fps", type=int, default=30, help="成品帧率，默认 30")
    ap.add_argument("--no-scale", action="store_true",
                    help="不缩放，按源分辨率烧录（如源片已是成品规格）")
    ap.add_argument("--scale-flags", default="lanczos",
                    help="缩放算法：lanczos（默认）/ bicubic / spline")
    ap.add_argument("--sharpen", type=float, default=0.5,
                    help="放大后轻度锐化强度，0 关闭；建议 0.4~0.6，超过 1.0 易出光晕")
    ap.add_argument("--head", default=None)
    ap.add_argument("--tail", default=None)
    ap.add_argument("--tail-from", type=float, default=None, help="片尾开始秒；默认结束前 0.6s")
    ap.add_argument("--key", action="append", default=[], help="重点词，可重复，如 --key 三个心脏")
    ap.add_argument("--max-chars", type=int, default=14, help="ASR 模式下每行最多字数")
    ap.add_argument("--ass-only", action="store_true")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--crf", type=int, default=18)
    a = ap.parse_args()

    W, H = [int(x) for x in a.size.lower().split("x")]

    if a.cues:
        cues = json.load(open(a.cues, encoding="utf-8"))
        if isinstance(cues, dict):
            cues = cues.get("cues", [])
    elif a.asr:
        asr = json.load(open(a.asr, encoding="utf-8"))
        cues = cues_from_asr(asr, a.max_chars, a.key)
    else:
        print("需要 --cues 或 --asr 之一"); sys.exit(2)

    if not cues:
        print("没有可用字幕 cues（可能是原片无配音），跳过"); sys.exit(0)

    dur = None
    try:
        import json as _j
        out = subprocess.check_output([a.ffmpeg.replace("ffmpeg", "ffprobe"), "-v", "error",
                                       "-show_entries", "format=duration", "-of", "json", a.video],
                                      timeout=60)
        dur = float(_j.loads(out)["format"]["duration"])
    except Exception:
        pass

    tail_time = None
    if a.tail and dur:
        t0 = a.tail_from if a.tail_from is not None else max(0.0, dur - 0.6)
        tail_time = (t0, dur)

    ass_text = build_ass(cues, W, H, a.head, a.tail, tail_time=tail_time)
    ass_path = a.ass_out or os.path.join(tempfile.mkdtemp(), "sub.ass")
    os.makedirs(os.path.dirname(os.path.abspath(ass_path)), exist_ok=True)
    open(ass_path, "w", encoding="utf-8-sig").write(ass_text)
    print("ASS 已生成：%s（%d 条字幕）" % (ass_path, len(cues)))
    if a.ass_only:
        return

    out_mp4 = a.out or os.path.splitext(a.video)[0] + "_字幕.mp4"
    out_size = None if a.no_scale else (W, H)
    ok, err = burn(a.ffmpeg, a.video, ass_path, out_mp4, a.crf,
                   out_size=out_size, fps=(None if a.no_scale else a.fps), duration=dur,
                   scale_flags=a.scale_flags, sharpen=a.sharpen)
    if ok:
        print("烧录成功：%s（%s / %sfps）" %
              (out_mp4, ("%dx%d" % (W, H)) if out_size else "源分辨率",
               a.fps if out_size else "源"))
    else:
        print("烧录失败：\n" + err)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
