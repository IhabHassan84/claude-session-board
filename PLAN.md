# Claude Code Planning Board — Design Plan (Local-only)

A per-session Kanban board (Trello-style) that Claude Code is forced to keep up to
date, so you never lose track of where you are in a build. Runs locally with live
updates, enforced via a skill + a session-start hook. View-only in the browser.

---

## 1. Goals & non-goals

**Goals**

- Every Claude Code session gets its own board, created automatically at session start.
- Task breakdowns become cards. Cards start in **Backlog**, move to **In Progress**, then **Done**.
- Board state (cards, columns, prefs) persists across sessions — survives restarts.
- Board viewable in a browser on the local machine, with **live updates** (no commit needed).
- Claude is reliably *forced* to use the board, not just reminded when convenient.

**Non-goals**

- No remote access, no GitHub Pages, no tunnels — **local machine only**.
- No live multi-user collaboration, no login/auth.
- No separate database — state is plain JSON files on disk.
- No board cleanup/archiving in v1.

---

## 2. Architecture at a glance

Four pieces, no real backend logic:

1. **State** — one JSON file per session board on disk + a small registry file.
2. **Server** — a tiny local HTTP server that serves the viewer and the JSON, and pushes
   live updates to the browser when a board file changes.
3. **Skill** — `SKILL.md` instructing Claude to drive the board through a CLI.
4. **Hook** — a SessionStart hook that auto-creates the board and starts the server.

The browser is a **read-only view**. Claude owns all state changes (creating cards, moving
them between columns) via the CLI. This is consistent with the goal of forcing Claude to
keep the board current.

---

## 3. Live updates without commits

Because everything is local, there is no push latency at all. The flow:

- Claude calls the CLI, which writes the board JSON on disk.
- The local server watches the boards directory (file-watch or simple mtime poll).
- On change, it notifies the open browser via **Server-Sent Events (SSE)** (one-way,
  simplest) or a short poll, and the page re-renders instantly.

No git involvement is required for the board to work. The board files still live inside the
repo so they're versioned with your code if you choose to commit them, but commits are
incidental, not part of the update path.

---

## 4. Repository / file layout

```
<your-repo>/
  .claude/
    skills/
      planning-board/
        SKILL.md                <- instructions that force board usage
        scripts/
          board.py              <- CLI: create / add-card / move-card / set-pref / list
          server.py             <- local HTTP server + live updates (SSE), stdlib only
        web/
          index.html            <- board viewer (picker + 3 columns + live render)
    boards/
      index.json                <- registry of boards (id, title, created, counts, active)
      <board-id>.json           <- one file per session board
    settings.json               <- registers the SessionStart hook
```

Everything lives under `.claude/` so it travels with the repo and stays out of your app's
source tree. Boards are served by `server.py` from `.claude/boards/`.

---

## 5. Data model

### Board file — `.claude/boards/<board-id>.json`

```json
{
  "id": "2026-06-15-a1b2c3",
  "title": "Checkout refactor",
  "session_id": "<claude-code-session-id-or-generated>",
  "created_at": "2026-06-15T09:30:00Z",
  "updated_at": "2026-06-15T11:05:00Z",
  "columns": ["backlog", "in-progress", "done"],
  "prefs": { "theme": "dark", "show_due_dates": true },
  "cards": [
    {
      "id": "card-001",
      "title": "Extract pricing logic into module",
      "description": "Move calc out of controller; add unit tests.",
      "column": "backlog",
      "due_date": null,
      "created_at": "2026-06-15T09:31:00Z",
      "updated_at": "2026-06-15T09:31:00Z",
      "order": 0
    }
  ]
}
```

### Registry — `.claude/boards/index.json`

```json
{
  "boards": [
    { "id": "2026-06-15-a1b2c3", "title": "Checkout refactor",
      "created_at": "2026-06-15T09:30:00Z",
      "card_counts": { "backlog": 3, "in-progress": 1, "done": 5 } }
  ],
  "active": "2026-06-15-a1b2c3"
}
```

The registry powers the board picker and tells the viewer which board is current.

---

## 6. Per-session identity

At SessionStart we use the Claude Code session id if it's exposed to the hook; otherwise we
generate our own id (date + short random suffix, e.g. `2026-06-15-a1b2c3`) and persist it
for the session. Either way each session deterministically maps to exactly one board, so a
session reconnecting reuses its board rather than creating a duplicate.

---

## 7. The skill — `SKILL.md`

Makes board edits mechanical so Claude does them correctly every time. Claude **never
hand-edits the JSON** — it calls `board.py`, which keeps the schema valid and timestamps/
ordering correct.

`SKILL.md` contents (sketch):

- **Trigger**: keywords like "plan", "task breakdown", "what's next", "progress", plus the
  directive that it applies whenever a board exists for the current session.
- **Rules Claude must follow**:
  1. Session start: if no board exists for this session, create one.
  2. When breaking work into tasks, add each as a card in **backlog**.
  3. Before starting a task, move its card to **in-progress** (keep only one/few there).
  4. When a task is finished and verified, move its card to **done**.
  5. Short titles; detail goes in the description.
  6. Tell the user the local board URL when the board is created.

### Helper CLI — `scripts/board.py` (stdlib only)

```
board.py create    --title T [--session S]       -> creates board + registry entry, prints id + URL
board.py add-card  --board B --title T [--desc D] [--due DATE]
board.py move-card --board B --id CARD --to COLUMN
board.py set-pref  --board B --key theme --value dark
board.py list      [--board B]                    -> prints columns + cards so Claude can read state
```

Each write updates `updated_at` and recomputes `index.json` counts. No git involved.

---

## 8. The server — `scripts/server.py` (stdlib only)

A minimal local HTTP server (Python `http.server`), bound to `127.0.0.1` only:

- Serves `web/index.html` at `/`.
- Serves board JSON and `index.json` from `.claude/boards/`.
- Exposes an SSE endpoint (`/events`) that emits a message whenever a board file's mtime
  changes, so the browser re-renders live.
- Started by the SessionStart hook if not already running; logs its URL (e.g.
  `http://127.0.0.1:7842`). Single instance shared across sessions; the picker switches
  between session boards.

---

## 9. The frontend — `web/index.html`

One self-contained HTML file (HTML + CSS + JS, no build step):

- On load: fetch `index.json`, populate a board picker, default to `active`.
- Fetch the selected board JSON, render **Backlog / In Progress / Done** columns with cards.
- Subscribe to `/events` (SSE); re-fetch and re-render on change → live updates.
- Honor `prefs` (theme, show due dates). **View-only** — no drag-and-drop persistence.

---

## 10. Enforcement — skill + SessionStart hook

The skill triggers on relevance, which isn't guaranteed every session; the hook makes it
reliable.

`.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command",
            "command": "python .claude/skills/planning-board/scripts/board.py create --auto --start-server" }
        ]
      }
    ]
  }
}
```

`--auto` creates a board for the session if one doesn't exist; `--start-server` ensures the
local server is running and prints the board URL. The hook also injects a short reminder of
the board rules into the session context, which nudges Claude to keep using the skill
throughout. We'll verify the exact SessionStart hook payload/format against current Claude
Code docs before building.

---

## 11. Build phases (once approved)

1. **Schema + CLI** — implement `board.py` (create/add-card/move-card/set-pref/list) + JSON
   files; unit-test the CLI.
2. **Server** — `server.py` with static serving + SSE file-watch.
3. **Viewer** — `web/index.html` with picker, 3-column render, live SSE updates.
4. **Skill** — write `SKILL.md` rules + command reference.
5. **Hook** — add `.claude/settings.json` SessionStart hook; verify format vs. docs.
6. **End-to-end test** — fresh session auto-creates a board, cards flow backlog →
   in-progress → done, browser updates live without any commit.

---

## 12. Summary

Local-only makes this clean: JSON files are the database, a tiny stdlib HTTP server serves a
read-only viewer with live SSE updates (no commits in the update path), a Python CLI is the
write layer that Claude drives, the skill defines the behavior, and a SessionStart hook
guarantees a board exists and the server is running every session. No backend service, no
remote hosting, no git latency.
