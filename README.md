# planning-board

A per-session Kanban board (Backlog → In Progress → Done) for **Claude Code**.
Every session gets its own board; Claude is instructed to create cards as it plans
work and move them across columns as it goes, so you never lose track of where a
build stands. The board renders in your browser and updates **live** — all local,
no server account, no database, no commits required.

## What you get

- A **skill** (`planning-board`) that tells Claude to drive the board.
- A **SessionStart hook** that auto-creates a board and starts the viewer every session.
- A tiny **local server** (Python stdlib) that serves a read-only board viewer and
  pushes live updates over Server-Sent Events.
- A `board.py` **CLI** that is the only thing that writes board state.

The browser view is read-only by design: Claude owns the board, which is what keeps
it honest about progress.

## Requirements

- Python 3 on your PATH (`python` or `python3`).
- Claude Code.

## Install (per project)

This is the flow the skill is designed around:

1. **Clone this repo** somewhere stable, e.g. your home directory:
   ```
   git clone <repo-url> ~/planning-board
   ```
2. In the project where you want a board, copy the skill into the project's
   `.claude/` directory (or symlink it):
   ```
   mkdir -p .claude/skills
   cp -r ~/planning-board/.claude/skills/planning-board .claude/skills/
   ```
3. **Add the SessionStart hook** to the project's `.claude/settings.json` (create the
   file if it doesn't exist):
   ```json
   {
     "hooks": {
       "SessionStart": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "python .claude/skills/planning-board/scripts/board.py create --auto --start-server --from-hook-stdin"
             }
           ]
         }
       ]
     }
   }
   ```
   If your Python is `python3`, use that in the command instead of `python`.
4. **Restart the Claude Code session.** On start, the hook creates a board for the
   session, launches the viewer, and tells Claude the board URL and the rules.

> Prefer it everywhere automatically? Install globally instead: put the
> `planning-board` folder in `~/.claude/skills/` and the same hook (with an
> **absolute** path to `board.py`) in `~/.claude/settings.json`. Then every project
> gets a board with no per-repo setup.

## Running multiple sessions at once

Multiple Claude Code sessions on one machine cannot share a port, so the server
**auto-selects a free port** starting at `7842` and scanning upward. The chosen port
is recorded in `<project>/.claude/boards/.runtime.json`, and the URL Claude shows you
always matches it. In practice:

- **Different projects** → each gets its own server on its own port (7842, 7843, …)
  serving only that project's boards.
- **Multiple sessions in the same project** → they share one server/port; each
  session still gets its own board, selectable from the picker in the viewer.

To pin a starting port, set `PLANNING_BOARD_PORT` in the environment before the
session starts.

## Using it

Work is organized as **board → epics → cards**. Every card lives in an epic and
flows across four columns: **Backlog → In Progress → Blocked → Done**. In the
viewer each epic is a collapsible panel with its own columns, and clicking a card
opens a detail view with its description, linked documents, and screenshots.

Once a session is running, just work normally — Claude creates epics, adds cards,
and moves them. You can also drive it yourself from the project root:

```
python .claude/skills/planning-board/scripts/board.py add-epic  --title "Checkout"
python .claude/skills/planning-board/scripts/board.py add-card  --epic epic-002 --title "Do the thing" --desc "details" --due 2026-07-01
python .claude/skills/planning-board/scripts/board.py move-card --id card-003 --to in-progress
python .claude/skills/planning-board/scripts/board.py move-card --id card-003 --to blocked
python .claude/skills/planning-board/scripts/board.py move-card --id card-003 --to done
python .claude/skills/planning-board/scripts/board.py add-link  --id card-003 --label "Spec" --url "docs/spec.md"
python .claude/skills/planning-board/scripts/board.py add-image --id card-003 --path ./shot.png --label "UI"
python .claude/skills/planning-board/scripts/board.py list
python .claude/skills/planning-board/scripts/board.py url            # print the viewer URL
python .claude/skills/planning-board/scripts/board.py set-pref  --key theme --value light
```

Open the printed URL (e.g. `http://127.0.0.1:7842`) in your browser. The board
refreshes the instant Claude or you change anything — no reload needed. Boards
created by older versions are upgraded automatically (blocked column + a default
epic are added on first write).

## How state is stored

```
<project>/.claude/boards/
  index.json          registry of boards + the active board
  <board-id>.json     one file per session board (epics, cards, columns, prefs)
  attachments/        screenshots attached to cards (served by the viewer)
  .runtime.json       the live server's port + pid (auto-managed)
```

The board and the skill are personal, local tooling — not part of your product —
so they should not be committed to the consuming project's repo. On session start
the board automatically adds this block to the project's `.gitignore` (only inside
a git repo, and only once):

```
# planning-board (Claude Code task board) — local only, do not commit
.claude/boards/
.claude/skills/planning-board/
```

If you'd rather version the skill itself (but never the board state), remove the
second line and keep `.claude/boards/` ignored.

Cards carry `created_at` and `updated_at`; the viewer sorts each column by **most
recently updated first**, and shows the update time on every card (full timestamps
in the card detail view).

## Layout of this repo

```
.claude/
  settings.json                         example SessionStart hook
  skills/planning-board/
    SKILL.md                            the rules Claude follows
    scripts/board.py                    the CLI (state writer)
    scripts/server.py                   local viewer server + live updates
    web/index.html                      the board viewer
PLAN.md                                 design notes
README.md                               this file
```

## Notes & limitations

- **Local only.** The viewer is bound to `127.0.0.1`; it is not reachable from other
  machines by design.
- The SessionStart `additionalContext` injection works with **project- or user-level
  hooks** (the path used here). There is a known Claude Code bug where the same field
  is dropped when the hook is defined inside a *plugin's* `hooks.json`, so don't ship
  this as a plugin hook.
- No card editing from the browser (read-only view). Edit via the CLI.
- Cards are clickable in the viewer to see description, referenced documents, and
  screenshots; epics are collapsible panels.
- No automatic cleanup of old boards yet.
