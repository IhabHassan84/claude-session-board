#!/usr/bin/env python3
"""planning-board CLI.

Single source of truth for board state. Claude drives the board through this
script; it never hand-edits the JSON. Stdlib only.

Board state lives in the CURRENT PROJECT at <cwd>/.claude/boards/, independent of
where this script is cloned/installed. Each project gets its own boards and its
own local server on an automatically chosen free port, so multiple Claude Code
sessions on one machine never collide.

Model:
  board -> epics -> cards. Every card belongs to an epic.
  columns: backlog -> in-progress -> blocked -> done
  cards may carry links (referenced docs/URLs) and images (screenshots).

Subcommands:
  create     --title T [--session S] [--auto] [--start-server] [--from-hook-stdin]
  add-epic   --title T [--board B]                         -> prints epic id
  add-card   --title T [--epic E] [--desc D] [--due DATE] [--board B]
  move-card  --id CARD --to backlog|in-progress|blocked|done [--board B]
  set-epic   --id CARD --epic E [--board B]
  add-link   --id CARD --label L --url U [--board B]
  add-image  --id CARD --path FILE [--label L] [--board B]
  set-pref   --key K --value V [--board B]
  list       [--board B]
  show       --id CARD [--board B]
  url        [--board B]
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import shutil
import socket
import string
import sys

COLUMNS = ["backlog", "in-progress", "blocked", "done"]
PORT_BASE = int(os.environ.get("PLANNING_BOARD_PORT", "7842"))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def project_root():
    return os.environ.get("PLANNING_BOARD_PROJECT") or os.getcwd()


def boards_dir():
    return os.environ.get("PLANNING_BOARD_DIR") or os.path.join(
        project_root(), ".claude", "boards"
    )


def attachments_dir():
    return os.path.join(boards_dir(), "attachments")


def index_path():
    return os.path.join(boards_dir(), "index.json")


def runtime_path():
    return os.path.join(boards_dir(), ".runtime.json")


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def ensure_dirs():
    os.makedirs(boards_dir(), exist_ok=True)


GITIGNORE_BLOCK = (
    "# planning-board (Claude Code task board) — local only, do not commit\n"
    ".claude/boards/\n"
    ".claude/skills/planning-board/\n"
)
GITIGNORE_MARK = "# planning-board (Claude Code task board)"


def ensure_gitignore():
    """Add the board's local artifacts to the project's .gitignore.

    The board state and the skill itself are personal/local tooling and should
    not be committed to the project's repo. Only acts inside a git repo (or when
    a .gitignore already exists); idempotent.
    """
    root = project_root()
    gi = os.path.join(root, ".gitignore")
    is_git = os.path.isdir(os.path.join(root, ".git"))
    if not is_git and not os.path.exists(gi):
        return  # not a git project; don't litter
    try:
        existing = ""
        if os.path.exists(gi):
            with open(gi, "r", encoding="utf-8") as f:
                existing = f.read()
        if GITIGNORE_MARK in existing:
            return
        sep = "" if (not existing or existing.endswith("\n")) else "\n"
        with open(gi, "a", encoding="utf-8") as f:
            f.write(sep + "\n" + GITIGNORE_BLOCK)
    except OSError:
        pass


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


# ---- schema upgrade --------------------------------------------------------

def normalize(board):
    """Upgrade older boards in place to the current schema."""
    cols = board.get("columns") or ["backlog", "in-progress", "done"]
    if "blocked" not in cols:
        # insert blocked just before done (or append)
        if "done" in cols:
            cols.insert(cols.index("done"), "blocked")
        else:
            cols.append("blocked")
    board["columns"] = cols

    board.setdefault("epics", [])
    if not board["epics"]:
        board["epics"] = [{"id": "epic-001", "title": "General", "order": 0}]

    default_epic = board["epics"][0]["id"]
    for card in board.get("cards", []):
        card.setdefault("epic", default_epic)
        card.setdefault("links", [])
        card.setdefault("images", [])
        card.setdefault("created_at", card.get("updated_at") or now())
        card.setdefault("updated_at", card.get("created_at") or now())
        # repair cards pointing at a now-missing epic
        if card["epic"] not in [e["id"] for e in board["epics"]]:
            card["epic"] = default_epic
    return board


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
    return normalize(b)


def write_board(board):
    board["updated_at"] = now()
    save_json(board_path(board["id"]), board)
    refresh_index(board)


def find_card(board, card_id):
    for c in board["cards"]:
        if c["id"] == card_id:
            return c
    sys.exit(f"Card not found: {card_id}")


def next_id(items, prefix):
    n = len(items) + 1
    existing = {i["id"] for i in items}
    while f"{prefix}-{n:03d}" in existing:
        n += 1
    return f"{prefix}-{n:03d}"


# ---- server / port helpers -------------------------------------------------

def port_alive(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def running_port():
    rt = load_json(runtime_path(), None)
    if rt and isinstance(rt.get("port"), int) and port_alive(rt["port"]):
        return rt["port"]
    return None


def viewer_url(board_id):
    port = running_port() or PORT_BASE
    return f"http://127.0.0.1:{port}/?board={board_id}"


def maybe_start_server():
    if running_port():
        return
    import subprocess
    server = os.path.join(SCRIPT_DIR, "server.py")
    env = dict(os.environ)
    env["PLANNING_BOARD_DIR"] = boards_dir()
    try:
        kwargs = {"env": env}
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000008 | 0x00000200
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
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        data = json.loads(sys.stdin.read() or "{}")
        return data.get("session_id") or data.get("sessionId")
    except Exception:
        return None


def cmd_create(args):
    ensure_dirs()
    ensure_gitignore()
    if args.from_hook_stdin and not args.session:
        args.session = session_from_stdin()

    repo = os.path.basename(os.path.normpath(project_root())) or "project"

    existing = find_board_by_session(args.session) if args.session else None
    if existing:
        board = normalize(existing)
        save_json(board_path(board["id"]), board)
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
            "epics": [{"id": "epic-001", "title": "General", "order": 0}],
            "prefs": {"theme": "vscode", "show_due_dates": True},
            "cards": [],
        }
        save_json(board_path(bid), board)
        refresh_index(board)
        created = True

    if args.start_server:
        maybe_start_server()
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
            "WORKFLOW: group work under epics (add-epic), then add each task as a "
            "card in an epic (add-card --epic). Move cards backlog -> in-progress "
            "-> done as you go; use 'blocked' when a card is waiting on something. "
            "Attach context with add-link (docs/URLs) and add-image (screenshots). "
            "Always update the board via the planning-board board.py CLI; never "
            "hand-edit the JSON."
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


def cmd_add_epic(args):
    board = get_board(args.board)
    eid = next_id(board["epics"], "epic")
    board["epics"].append({
        "id": eid, "title": args.title, "order": len(board["epics"]),
    })
    write_board(board)
    print(f"Added epic {eid}: {args.title}")


def cmd_add_card(args):
    board = get_board(args.board)
    epic = args.epic or board["epics"][0]["id"]
    if epic not in [e["id"] for e in board["epics"]]:
        sys.exit(f"Epic not found: {epic} (use add-epic first or omit --epic)")
    cid = next_id(board["cards"], "card")
    card = {
        "id": cid,
        "title": args.title,
        "description": args.desc or "",
        "epic": epic,
        "column": "backlog",
        "due_date": args.due,
        "links": [],
        "images": [],
        "created_at": now(),
        "updated_at": now(),
        "order": sum(1 for c in board["cards"] if c["column"] == "backlog"),
    }
    board["cards"].append(card)
    write_board(board)
    print(f"Added {cid} to backlog [{epic}]: {card['title']}")


def cmd_move_card(args):
    if args.to not in COLUMNS:
        sys.exit(f"--to must be one of {COLUMNS}")
    board = get_board(args.board)
    card = find_card(board, args.id)
    card["column"] = args.to
    card["updated_at"] = now()
    write_board(board)
    print(f"Moved {card['id']} -> {args.to}")


def cmd_set_epic(args):
    board = get_board(args.board)
    if args.epic not in [e["id"] for e in board["epics"]]:
        sys.exit(f"Epic not found: {args.epic}")
    card = find_card(board, args.id)
    card["epic"] = args.epic
    card["updated_at"] = now()
    write_board(board)
    print(f"Moved {card['id']} to epic {args.epic}")


def cmd_add_link(args):
    board = get_board(args.board)
    card = find_card(board, args.id)
    card["links"].append({"label": args.label, "url": args.url})
    card["updated_at"] = now()
    write_board(board)
    print(f"Added link to {card['id']}: {args.label} -> {args.url}")


def cmd_add_image(args):
    src = args.path
    if not os.path.isfile(src):
        sys.exit(f"File not found: {src}")
    board = get_board(args.board)
    card = find_card(board, args.id)
    os.makedirs(attachments_dir(), exist_ok=True)
    base = re.sub(r"[^a-zA-Z0-9._-]", "_", os.path.basename(src))
    stored = f"{board['id']}_{card['id']}_{len(card['images'])+1}_{base}"
    shutil.copy2(src, os.path.join(attachments_dir(), stored))
    card["images"].append({
        "name": stored,
        "label": args.label or os.path.basename(src),
        "src": os.path.abspath(src),
        "added": now(),
    })
    card["updated_at"] = now()
    write_board(board)
    print(f"Attached image to {card['id']}: {stored}")


def cmd_set_pref(args):
    board = get_board(args.board)
    val = args.value
    if val.lower() in ("true", "false"):
        val = val.lower() == "true"
    board["prefs"][args.key] = val
    write_board(board)
    print(f"Set pref {args.key} = {val!r}")


def cmd_list(args):
    board = get_board(args.board)
    print(f"# {board['title']} ({board['id']})")
    by_epic = {e["id"]: e for e in board["epics"]}
    for e in board["epics"]:
        ecards = [c for c in board["cards"] if c.get("epic") == e["id"]]
        print(f"\n=== EPIC {e['id']}: {e['title']} ({len(ecards)} cards) ===")
        for col in board["columns"]:
            cards = [c for c in ecards if c["column"] == col]
            if not cards:
                continue
            print(f"  [{col}]")
            for c in cards:
                due = f" (due {c['due_date']})" if c.get("due_date") else ""
                extra = []
                if c.get("links"):
                    extra.append(f"{len(c['links'])} link(s)")
                if c.get("images"):
                    extra.append(f"{len(c['images'])} image(s)")
                tail = f"  [{', '.join(extra)}]" if extra else ""
                print(f"    - {c['id']}: {c['title']}{due}{tail}")


def cmd_show(args):
    board = get_board(args.board)
    card = find_card(board, args.id)
    epic = next((e for e in board["epics"] if e["id"] == card.get("epic")), None)
    print(f"{card['id']}: {card['title']}")
    print(f"  epic:   {epic['title'] if epic else card.get('epic')}")
    print(f"  column: {card['column']}")
    if card.get("due_date"):
        print(f"  due:    {card['due_date']}")
    if card.get("description"):
        print(f"  description:\n    {card['description']}")
    for ln in card.get("links", []):
        print(f"  link:   {ln['label']} -> {ln['url']}")
    for im in card.get("images", []):
        print(f"  image:  {im['label']} ({im['name']})")


def cmd_url(args):
    board = get_board(args.board)
    print(viewer_url(board["id"]))


def main():
    p = argparse.ArgumentParser(description="planning-board CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--title"); c.add_argument("--session")
    c.add_argument("--auto", action="store_true")
    c.add_argument("--start-server", action="store_true")
    c.add_argument("--from-hook-stdin", action="store_true")
    c.set_defaults(func=cmd_create)

    e = sub.add_parser("add-epic")
    e.add_argument("--board"); e.add_argument("--title", required=True)
    e.set_defaults(func=cmd_add_epic)

    a = sub.add_parser("add-card")
    a.add_argument("--board"); a.add_argument("--title", required=True)
    a.add_argument("--epic"); a.add_argument("--desc"); a.add_argument("--due")
    a.set_defaults(func=cmd_add_card)

    m = sub.add_parser("move-card")
    m.add_argument("--board"); m.add_argument("--id", required=True)
    m.add_argument("--to", required=True)
    m.set_defaults(func=cmd_move_card)

    se = sub.add_parser("set-epic")
    se.add_argument("--board"); se.add_argument("--id", required=True)
    se.add_argument("--epic", required=True)
    se.set_defaults(func=cmd_set_epic)

    al = sub.add_parser("add-link")
    al.add_argument("--board"); al.add_argument("--id", required=True)
    al.add_argument("--label", required=True); al.add_argument("--url", required=True)
    al.set_defaults(func=cmd_add_link)

    ai = sub.add_parser("add-image")
    ai.add_argument("--board"); ai.add_argument("--id", required=True)
    ai.add_argument("--path", required=True); ai.add_argument("--label")
    ai.set_defaults(func=cmd_add_image)

    s = sub.add_parser("set-pref")
    s.add_argument("--board"); s.add_argument("--key", required=True)
    s.add_argument("--value", required=True)
    s.set_defaults(func=cmd_set_pref)

    l = sub.add_parser("list")
    l.add_argument("--board")
    l.set_defaults(func=cmd_list)

    sh = sub.add_parser("show")
    sh.add_argument("--board"); sh.add_argument("--id", required=True)
    sh.set_defaults(func=cmd_show)

    u = sub.add_parser("url")
    u.add_argument("--board")
    u.set_defaults(func=cmd_url)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
