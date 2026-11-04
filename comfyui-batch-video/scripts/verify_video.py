# -*- coding: utf-8 -*-
"""对成品目录做批量复检：参数一致性、音轨、黑屏/静态、画面文字。

用法：
  python verify_video.py --dir "L:\\工作流\\儿童科普视频\\第三批"
  python verify_video.py --dir out --json audit.json --expect 736x1312
退出码 0 表示全部通过，1 表示存在不合格项。
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfy_h3 as H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--json", default=None, help="把明细写入该 JSON")
    ap.add_argument("--expect", default=None, help="期望分辨率，如 736x1312")
    ap.add_argument("--skip-subtitle", action="store_true", help="跳过画面文字检测（更快）")
    a = ap.parse_args()

    cfg = H.load_config(a.config)
    files = sorted(f for f in os.listdir(a.dir) if f.lower().endswith(".mp4"))
    if not files:
        print("目录内没有 mp4：%s" % a.dir); sys.exit(2)

    rows, bad = [], []
    for f in files:
        p = os.path.join(a.dir, f)
        info = H.ffprobe(cfg, p)
        ar = round(info["w"] / info["h"], 4) if info.get("w") and info.get("h") else 0
        fc = H.frame_check(cfg, p, info.get("dur", 5))
        rows_n = -1 if a.skip_subtitle else H.subtitle_score(cfg, p, info.get("dur", 5))
        problems = []
        if "error" in info:
            problems.append("probe_fail")
        else:
            lo, hi = cfg["expect_dur"]; alo, ahi = cfg["expect_aspect"]
            if not (lo <= info.get("dur", 0) <= hi): problems.append("duration")
            if not (alo <= ar <= ahi): problems.append("aspect")
            if not info.get("has_audio"): problems.append("no_audio")
        if not fc.get("ok"): problems.append("frame:" + str(fc.get("reason") or "black/static"))
        if rows_n >= cfg["subtitle_rows_max"]: problems.append("on_screen_text")
        if a.expect:
            ew, eh = a.expect.lower().split("x")
            if (info.get("w"), info.get("h")) != (int(ew), int(eh)): problems.append("resolution")
        rec = {"file": f, "dur": info.get("dur"), "res": "%sx%s" % (info.get("w"), info.get("h")),
               "fps": info.get("fps"), "audio": info.get("has_audio"),
               "size": os.path.getsize(p), "subtitle_rows": rows_n,
               "brightness": fc.get("brightness"), "frame_diff": fc.get("frame_diff"),
               "problems": problems}
        rows.append(rec)
        if problems: bad.append(rec)

    print("%-38s %6s %10s %5s %6s %8s %s" % ("文件", "时长", "分辨率", "音轨", "文字行", "大小MB", "结论"))
    for r in rows:
        print("%-38s %6s %10s %5s %6s %8.1f %s" %
              (r["file"][:38], r["dur"], r["res"], "有" if r["audio"] else "无",
               r["subtitle_rows"], r["size"] / 1048576,
               "OK" if not r["problems"] else "FAIL:" + ",".join(r["problems"])))
    print("\n合计 %d 条，合格 %d 条，不合格 %d 条" % (len(rows), len(rows) - len(bad), len(bad)))
    if bad:
        print("不合格清单：")
        for r in bad:
            print("  - %s -> %s" % (r["file"], ",".join(r["problems"])))
    if a.json:
        json.dump(rows, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("明细已写入 %s" % a.json)
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
