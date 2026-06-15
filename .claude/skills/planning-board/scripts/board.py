#!/usr/bin/env python3
"""planning-board CLI.

Single source of truth for board state. Claude drives the board through this
script; it never hand-edits the JSON. Stdlib only.

Board state lives in the CURRENT PROJECT at <cwd>/.claude/boards/, independent of
where this script is cloned/installed. Each project therefore gets its own boards
and its own local server on an automatically chosen free port, so multiple Claude
Code sessions on one machine never collide.

Subcommands:
  create    --title T [--session S] [--auto] [--start-server] [--from-hook-stdin]
  add-card  --board B --title T [--desc D] [--due YYYY-MM-DD]
  move-card --board B --id CARD --to backlog|in-progress|done
  set-pref  --board B --key K --value V
  list      [--board B]
  url       [--board B]
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import socket
import string
import sys

COLUMNS = ["backlog", "in-progress", "done"]
PORT_BASE = int(os.environ.get("PLANNING_BOARD_PORT", "7842"))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def project_root():
    # Allow explicit override; otherwise the directory the session runs in.
    return os.environ.get("PLANNING_BOARD_PROJECT") or os.getcwd()


def boards_dir():
    return os.environ.get("PLANNING_BOARD_DIR") or os.path.join(
        project_root(), ".claude", "boards"
    )


def index_path():
    return os.path.join(boards_dir(), "index.json")


def runtime_path():
    return os.path.join(boards_dir(), ".runtime.json")


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def ensure_dirs():
    os.makedirs(boards_dir(), exist_ok=True)


def board_path(board_id):
    return os.path.join(boards_dir(), board_id + ".json")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_index():
    return load_json(index_path(), {"boards": [], "active": None})


def gen_id():
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return dt.date.today().isoformat() + "-" + suffix


def slug_session(s):
    return re.sub(r"[^a-zA-Z0-9_-]", "-", s)[:40] if s else None


def counts(board):
    c = {col: 0 for col in board["columns"]}
    for card in board["cards"]:
        c[card["column"]] = c.get(card["column"], 0) + 1
    return c


def refresh_index(board):
    idx = load_index()
    entry = {
        "id": board["id"],
        "title": board["title"],
        "created_at": board["created_at"],
        "card_counts": counts(board),
    }
    found = False
    for i, b in enumerate(idx["boards"]):
        if b["id"] == board["id"]:
            idx["boards"][i] = entry
            found = True
            break
    if not found:
        idx["boards"].append(entry)
    idx["active"] = board["id"]
    save_json(index_path(), idx)


def find_board_by_session(session_id):
    if not session_id:
        return None
    sid = slug_session(session_id)
    bd = boards_dir()
    if not os.path.isdir(bd):
        return None
    for fn in os.listdir(bd):
        if not fn.endswith(".json") or fn == "index.json":
            continue
        b = load_json(os.path.join(bd, fn), None)
        if b and slug_session(b.get("session_id") or "") == sid:
            return b
    return None


def get_board(board_id):
    if not board_id:
        board_id = load_index().get("active")
    if not board_id:
        sys.exit("No board specified and no active board found.")
    b = load_json(board_path(board_id), None)
    if b is None:
        sys.exit(f"Board not found: {board_id}")
    return b


# ---- server / port helpers -------------------------------------------------

def port_alive(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def running_port():
    """Port of a live server already serving this project's boards, or None."""
    rt = load_json(runtime_path(), None)
    if rt and isinstance(rt.get("port"), int) and port_alive(rt["port"]):
        return rt["port"]
    return None


def viewer_url(board_id):
    port = running_port() or PORT_BASE
    return f"http://127.0.0.1:{port}/?board={board_id}"


def maybe_start_server():
    if running_port():
        return  # already serving this project's boards
    import subprocess
    server = os.path.join(SCRIPT_DIR, "server.py")
    env = dict(os.environ)
    env["PLANNING_BOARD_DIR"] = boards_dir()
    try:
        kwargs = {"env": env}
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED|NEW_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(
            [sys.executable, server],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs,
        )
    except Exception as e:
        print(f"(could not auto-start server: {e})", file=sys.stderr)


# ---- commands --------------------------------------------------------------

def session_from_stdin():
    """SessionStart hooks receive JSON on stdin including session_id."""
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        data = json.loads(sys.stdin.read() or "{}")
        return data.get("session_id") or data.get("sessionId")
    except Exception:
        return None


def cmd_create(args):
    ensure_dirs()
    if args.from_hook_stdin and not args.session:
        args.session = session_from_stdin()

    repo = os.path.basename(os.path.normpath(project_root())) or "project"

    existing = find_board_by_session(args.session) if args.session else None
    if existing:
        board = existing
        created = False
    else:
        bid = gen_id()
        board = {
            "id": bid,
            "title": args.title or f"{repo} — {bid}",
            "session_id": args.session,
            "created_at": now(),
            "updated_at": now(),
            "columns": list(COLUMNS),
            "prefs": {"theme": "dark", "show_due_dates": True},
            "cards": [],
        }
        save_json(board_path(bid), board)
        refresh_index(board)
        created = True

    if args.start_server:
        maybe_start_server()
        # give the server a moment to bind and write its runtime file
        import time
        for _ in range(20):
            if running_port():
                break
            time.sleep(0.1)

    url = viewer_url(board["id"])
    if args.auto:
        msg = (
            f"Planning board ready for '{repo}': {board['title']} ({board['id']}). "
            f"View it at {url}. "
            "RULES: break work into cards in 'backlog'; move a card to 'in-progress' "
            "before starting it; move it to 'done' when finished and verified. "
            "Always update the board via the planning-board board.py CLI "
            "(never hand-edit the JSON)."
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": msg,
            }
        }))
    else:
        print(f"{'Created' if created else 'Using'} board {board['id']}")
        print(f"Title: {board['title']}")
        print(f"URL:   {url}")


def cmd_add_card(args):
    board = get_board(args.board)
    n = len(board["cards"]) + 1
    card = {
        "id": f"card-{n:03d}",
        "title": args.title,
        "description": args.desc or "",
        "column": "backlog",
        "due_date": args.due,
        "created_at": now(),
        "updated_at": now(),
        "order": sum(1 for c in board["cards"] if c["column"] == "backlog"),
    }
    board["cards"].append(card)
    board["updated_at"] = now()
    save_json(board_path(board["id"]), board)
    refresh_index(board)
    print(f"Added {card['id']} to backlog: {card['title']}")


def cmd_move_card(args):
    if args.to not in COLUMNS:
        sys.exit(f"--to must be one of {COLUMNS}")
    board = get_board(args.board)
    for card in board["cards"]:
        if card["id"] == args.id:
            card["column"] = args.to
            card["order"] = sum(
                1 for c in board["cards"] if c["column"] == args.to and c["id"] != card["id"]
            )
            card["updated_at"] = now()
            board["updated_at"] = now()
            save_json(board_path(board["id"]), board)
            refresh_index(board)
            print(f"Moved {card['id']} -> {args.to}")
            return
    sys.exit(f"Card not found: {args.id}")


def cmd_set_pref(args):
    board = get_board(args.board)
    val = args.value
    if val.lower() in ("true", "false"):
        val = val.lower() == "true"
    board["prefs"][args.key] = val
    board["updated_at"] = now()
    save_json(board_path(board["id"]), board)
    print(f"Set pref {args.key} = {val!r}")


def cmd_list(args):
    board = get_board(args.board)
    print(f"# {board['title']} ({board['id']})")
    for col in board["columns"]:
        cards = [c for c in board["cards"] if c["column"] == col]
        print(f"\n## {col} ({len(cards)})")
        for c in sorted(cards, key=lambda x: x.get("order", 0)):
            due = f" [due {c['due_date']}]" if c.get("due_date") else ""
            print(f"  - {c['id']}: {c['title']}{due}")


def cmd_url(args):
    board = get_board(args.board)
    print(viewer_url(board["id"]))


def main():
    p = argparse.ArgumentParser(description="planning-board CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--title")
    c.add_argument("--session")
    c.add_argument("--auto", action="store_true")
    c.add_ar