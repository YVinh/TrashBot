"""One-off: regenerate local (gemma4/mbp-writer) yousuf outputs for the 16 real
pre-switch contexts extracted from feed.json, for the issue-2 blind test.
Avoids CT210 during 04:15-05:30 UTC (morning brief window).

Input: ../../homelab/trashbot-eval/issue2/yousuf_samples_raw.json (or wherever the
homelab checkout is — override SRC/OUT below if it moved).
Run from the TrashBot repo root: .venv/bin/python tools/gen_yousuf_local.py
"""
import json, os, sys, time, datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["LLM_BACKEND"] = "local"

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import yousuf_agent as ya

SRC = "/root/homelab/trashbot-eval/issue2/yousuf_samples_raw.json"
OUT = "/root/homelab/trashbot-eval/issue2/yousuf_samples_local.json"

BLOCK_START = dt.time(4, 15)
BLOCK_END = dt.time(5, 30)


def wait_if_blocked():
    while True:
        now = dt.datetime.now(dt.timezone.utc).time()
        if BLOCK_START <= now <= BLOCK_END:
            print(f"[{now}] in CT210 blocked window, sleeping 5 min", flush=True)
            time.sleep(300)
        else:
            return


def main():
    samples = json.load(open(SRC))
    results = []
    if os.path.exists(OUT):
        results = json.load(open(OUT))
    done_ids = {r["yousuf_id"] for r in results}

    for s in samples:
        if s["yousuf_id"] in done_ids:
            continue
        wait_if_blocked()
        print(f"generating {s['kind']} for {s['yousuf_id']}...", flush=True)
        try:
            if s["kind"] == "comment_on_marc":
                marc_c, _ = ya.generate_comments(s["marc_text"], s["giselle_text"] or "")
                text = marc_c
            elif s["kind"] == "comment_on_giselle":
                _, gis_c = ya.generate_comments(s["marc_text"], s["giselle_text"] or "")
                text = gis_c
            elif s["kind"] == "followup":
                text = ya.generate_followup(s["reply_to_text"])
            else:
                print("skip unknown kind", s["yousuf_id"])
                continue
            results.append({**s, "local_text": text})
            json.dump(results, open(OUT, "w"), indent=2, ensure_ascii=False)
            print("  ->", text[:80], flush=True)
        except Exception as e:
            print("  FAILED:", e, flush=True)
            results.append({**s, "local_text": None, "error": str(e)})
            json.dump(results, open(OUT, "w"), indent=2, ensure_ascii=False)

    print("done", len(results), "of", len(samples))


if __name__ == "__main__":
    main()
