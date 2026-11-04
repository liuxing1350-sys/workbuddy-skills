# -*- coding: utf-8 -*-
"""批量串行生成竖屏科普短视频（ComfyUI + MiniMax-H3 + Pika LoRA）。

用法：
  python batch_generate.py --prompts prompts.json --outdir "L:\\...\\第二批" --ids 21-40
  python batch_generate.py --prompts prompts.json --outdir out --ids all --resume
  python batch_generate.py --prompts prompts.json --outdir out --ids 62 --dry-run

每条独立提交、独立保存；失败自动重试，含字幕时自动升级"禁止文字"约束后重试。
"""
import argparse, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfy_h3 as H


def parse_ids(spec, available):
    if not spec or spec == "all":
        return list(available)
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return [i for i in available if i in set(out)]


def log_write(path, log):
    json.dump(log, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def run_one(cfg, item, outdir, max_attempts=3):
    t0 = time.time()
    dest = os.path.join(outdir, item["filename"])
    res = {"id": item["id"], "filename": item["filename"], "title": item.get("title", ""),
           "status": "FAIL", "attempts": 0, "error": None, "file": dest}
    for attempt in range(1, max_attempts + 1):
        res["attempts"] = attempt
        # 第 1 次用标准约束；出现字幕等画面文字问题后升级为强约束
        strong = attempt > 1
        prompt = H.build_prompt(cfg, H.build_text(item, strong=strong))
        r, err = H.post_prompt(cfg, prompt)
        if err:
            res["error"] = "submit:" + err
            print("  [%s] 提交失败(第%d次): %s" % (item["id"], attempt, err[:600]), flush=True)
            continue
        pid = r.get("prompt_id")
        res["prompt_id"] = pid
        print("  [%s] 已提交 %s (第%d次)%s，等待生成..." %
              (item["id"], pid, attempt, "，强约束" if strong else ""), flush=True)
        rec, werr = H.wait_done(cfg, pid)
        if werr:
            res["error"] = "wait:" + werr
            continue
        if rec.get("status", {}).get("status_str") == "error":
            msgs = [m for m in rec["status"].get("messages", []) if m[0] == "execution_error"]
            res["error"] = "exec:" + json.dumps(msgs, ensure_ascii=False)[:1500]
            print("  [%s] 执行错误: %s" % (item["id"], res["error"][:300]), flush=True)
            continue
        f = H.find_video(rec)
        if not f:
            res["error"] = "no_output_file"
            print("  [%s] 无输出文件: %s" % (item["id"], json.dumps(rec.get("outputs", {}), ensure_ascii=False)[:300]), flush=True)
            continue
        try:
            H.download(cfg, f, dest)
        except Exception as e:
            res["error"] = "download:" + str(e)
            continue
        ok, detail = H.verify(cfg, dest)
        res.update(detail)
        res["elapsed_sec"] = round(time.time() - t0, 1)
        if ok:
            res["status"] = "SUCCESS"; res["error"] = None
            print("  [%s] 成功 dur=%s %sx%s audio=%s 字幕rows=%s 耗时%.0fs" %
                  (item["id"], detail["probe"].get("dur"), detail["probe"].get("w"),
                   detail["probe"].get("h"), detail["probe"].get("has_audio"),
                   detail.get("subtitle_rows"), res["elapsed_sec"]), flush=True)
            return res
        res["error"] = "verify_failed:" + ",".join(detail.get("fail", []))
        print("  [%s] 验收未过(%s) 字幕rows=%s，重试" %
              (item["id"], res["error"], detail.get("subtitle_rows")), flush=True)
    res["status"] = "NEEDS_REVIEW"
    res["elapsed_sec"] = round(time.time() - t0, 1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True, help="提示词 JSON 数组，字段 id/filename/integrated/soundscape/music/voice/dialogue")
    ap.add_argument("--outdir", required=True, help="成品输出目录")
    ap.add_argument("--ids", default="all", help="all | 21-40 | 21,22,30")
    ap.add_argument("--config", default=None, help="覆盖默认配置的 JSON")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--resume", action="store_true", help="跳过已存在且验收通过的成品")
    ap.add_argument("--dry-run", action="store_true", help="只构建并打印提示词，不提交")
    a = ap.parse_args()

    cfg = H.load_config(a.config)
    st = H.server_ready(cfg)
    if "error" in st:
        print("ComfyUI 不可用：%s\n请先启动 ComfyUI 并确认 --config 中的 base 地址。" % st["error"])
        sys.exit(2)
    dev = (st.get("devices") or [{}])[0]
    print("ComfyUI 就绪 | GPU=%s | VRAM 空闲 %.1f/%.1f GB" %
          (dev.get("name"), dev.get("vram_free", 0) / 1e9, dev.get("vram_total", 0) / 1e9))
    q = H.queue_state(cfg)
    if q["running"] or q["pending"]:
        print("警告：队列非空 running=%d pending=%d，将排队执行" % (q["running"], q["pending"]))

    items = json.load(open(a.prompts, encoding="utf-8"))
    ids = parse_ids(a.ids, [it["id"] for it in items])
    sel = [it for it in items if it["id"] in set(ids)]
    if not sel:
        print("没有匹配的条目，检查 --ids 与提示词文件"); sys.exit(2)
    print("本次任务 %d 条：%s" % (len(sel), ",".join(str(i["id"]) for i in sel)))

    if a.dry_run:
        for it in sel:
            print("\n=== %s %s ===\n%s" % (it["id"], it["filename"], H.build_text(it)))
        return

    os.makedirs(a.outdir, exist_ok=True)
    log_path = os.path.join(a.outdir, "run_log.json")
    log = json.load(open(log_path, encoding="utf-8")) if os.path.exists(log_path) else {}
    t_all = time.time(); done = 0

    for it in sel:
        dest = os.path.join(a.outdir, it["filename"])
        if a.resume and os.path.exists(dest):
            ok, _ = H.verify(cfg, dest)
            if ok:
                print("=== 跳过 %s（已存在且验收通过）===" % it["id"], flush=True)
                log[str(it["id"])] = dict(log.get(str(it["id"]), {}), status="SUCCESS",
                                          file=dest, skipped=True)
                log_write(log_path, log); done += 1
                continue
        print("=== 开始 %s %s ===" % (it["id"], it["filename"]), flush=True)
        r = run_one(cfg, it, a.outdir, a.max_attempts)
        log[str(it["id"])] = r
        log_write(log_path, log)
        if r["status"] == "SUCCESS":
            done += 1
        print("=== 完成 %s -> %s 耗时 %ss ===" % (it["id"], r["status"], r.get("elapsed_sec")), flush=True)

    total = round(time.time() - t_all, 1)
    succ = sum(1 for v in log.values() if v.get("status") == "SUCCESS")
    print("\n===== 汇总 =====")
    print("成功 %d / %d，总耗时 %.1f 分钟，平均 %.1f 分钟/条" %
          (done, len(sel), total / 60, total / 60 / max(1, len(sel))))
    print("日志：%s" % log_path)
    print("（日志内为全量累计成功数 %d）" % succ)


if __name__ == "__main__":
    main()
