#!/usr/bin/env python3
"""One-shot helper: bucket an existing board's cards into epics by keyword.

Older boards (or boards built before epics existed) put every card in the
default "General" epic. Run this once, in the project whose board you want to
reorganize, to auto-create epics and move matching cards into them.

Usage:
    python .claude/skills/planning-board/scripts/migrate_epics.py [--board BOARD_ID] [--dry-run]

Edit the RULES list below to fit your project. Rules are evaluated top to
bottom; the first epic whose keywords appear in a card's title or description
wins. Cards that match nothing stay in "General".
"""
import argparse
import datetime as dt
import json
import os
import sys

# (epic title, [keywords]) — first match wins. Tuned for the weather app board;
# edit freely for other projects.
RULES = [
    ("Marketing email consent",
     ["brevo", "webhook", "consent", "opt-in", "opt in", "privacy", "marketing",
      "email", "unsubscribe", "data safety"]),
    ("Subscriptions & paywall",
     ["trial", "paywall", "revenuecat", "subscription", "play console", "offer",
      "billing", "entitlement", "version", "bump"]),
    ("Firestore & backend",
     ["firestore", "cloud function", "security rule", "firebase", "deploy"]),
    ("App polish & monitoring",
     ["crashlytics", "activity card", "truncation", "ui", "screen", "layout"]),
]


def boards_dir():
    return os.environ.get("PLANNING_BOARD_DIR") or os.path.join(
        os.getcwd(), ".claude", "boards"
    )


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bd = boards_dir()
    idx_path = os.path.join(bd, "index.json")
    if not os.path.exists(idx_path):
        sys.exit(f"No boards found at {bd}")
    idx = load(idx_path)
    board_id = args.board or idx.get("active")
    if not board_id:
        sys.exit("No active board; pass --board")
    bpath = os.path.join(bd, board_id + ".json")
    board = load(bpath)

    board.setdefault("epics", [])
    if not board["epics"]:
        board["epics"] = [{"id": "epic-001", "title": "General", "order": 0}]

    # map existing epic titles -> id, creating epics as rules require
    title_to_id = {e["title"]: e["id"] for e in board["epics"]}

    def epic_id_for(title):
        if title in title_to_id:
            return title_to_id[title]
        n = len(board["epics"]) + 1
        eid = f"epic-{n:03d}"
        while eid in {e["id"] for e in board["epics"]}:
            n += 1
            eid = f"epic-{n:03d}"
        board["epics"].append({"id": eid, "title": title, "order": len(board["epics"])})
        title_to_id[title] = eid
        return eid

    moves = []
    for card in board.get("cards", []):
        hay = (card.get("title", "") + " " + card.get("description", "")).lower()
        for epic_title, kws in RULES:
            if any(k in hay for k in kws):
                eid = epic_id_for(epic_title)
                if card.get("epic") != eid:
                    moves.append((card["id"], card.get("title", ""), epic_title))
                    if not args.dry_run:
                        card["epic"] = eid
                        card["updated_at"] = now()
                break

    if args.dry_run:
        print(f"DRY RUN — {len(moves)} card(s) would move:")
    else:
        board["updated_at"] = now()
        save(bpath, board)
        print(f"Reorganized {len(moves)} card(s) into epics:")
    for cid, title, epic in moves:
        print(f"  {cid}  ->  {epic}   ({title})")
    if not moves:
        print("  (nothing matched — edit RULES at the top of this script)")


if __name__ == "__main__":
    main()
