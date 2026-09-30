"""One-off: run the local moderation check (feed_poller.fit_to_show) against a
synthetic labeled set for issue-2 (no real production moderation calls exist —
FEED_POLL_HOURS has been 0 the whole time, so there is no Opus baseline to
compare against; this is a local-only accuracy check, not a blind A/B).

Run from the TrashBot repo root: .venv/bin/python tools/gen_feedpoll_local.py
"""
import json, os, sys, time, datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["LLM_BACKEND"] = "local"

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import feed_poller as fp

SRC = "/root/homelab/trashbot-eval/issue2/feed_poller_samples.json"
OUT = "/root/homelab/trashbot-eval/issue2/feed_poller_results.json"
BLOCK_START, BLOCK_END = dt.time(4, 15), dt.time(5, 30)


def wait_if_blocked():
    while True:
        now = dt.datetime.now(dt.timezone.utc).time()
        if BLOCK_START <= now <= BLOCK_END:
            print(f"[{now}] blocked window, sleeping 5 min", flush=True)
            time.sleep(300)
        else:
            return


def main():
    samples = json.load(open(SRC))
    results = []
    for s in samples:
        wait_if_blocked()
        verdict = "SHOW" if fp.fit_to_show(s["text"]) else "HIDE"
        ok = verdict == s["expected"]
        results.append({**s, "local_verdict": verdict, "match": ok})
        print(s["id"], s["expected"], "->", verdict, "OK" if ok else "MISMATCH", flush=True)

    json.dump(results, open(OUT, "w"), indent=2, ensure_ascii=False)
    n_ok = sum(r["match"] for r in results)
    print(f"done {n_ok}/{len(results)} matched expected label")


if __name__ == "__main__":
    main()
