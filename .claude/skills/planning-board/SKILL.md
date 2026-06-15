---
name: planning-board
description: >-
  Maintain a per-session Kanban planning board (Backlog / In Progress / Done)
  for the current Claude Code session. Use this whenever you break work into
  tasks, plan a feature, start or finish a task, or the user asks about progress,
  "what's next", the plan, or the board. A board is auto-created at session start;
  keep it current by adding cards and moving them between columns as work proceeds.
---

# Planning Board

You maintain a live Kanban board for this coding session so the user can always
see where things stand. The board has three columns: **backlog**, **in-progress**,
**done**. Cards are work items.

## Hard rules

1. **Never hand-edit the board JSON.** Always change state through the CLI:
   `python .claude/skills/planning-board/scripts/board.py <subcommand>`.
2. **Break work into cards.** When you plan a task or feature, add one card per
   discrete work item to **backlog**.
3. **Move before you start.** Right before working on a task, move its card to
   **in-progress**. Keep only one or a few cards in-progress at a time.
4. **Move when done.** When a task is finished *and verified*, move its card to
   **done**.
5. **Share the URL.** When the board is created or after a meaningful update, tell
   the user the board URL so they can open it.
6. Keep card **titles short**; put detail in the description.

If you are unsure whether a board exists for this session, run `list` (below). If
it errors with no active board, run `create`.

## Commands

Run from the repo root. The `--board` flag is optional; it defaults to the active
board.

Create / ensure a board for this session:
```
python .claude/skills/planning-board/scripts/board.py create --title "Short project name" --session "$CLAUDE_SESSION_ID" --start-server
```

Add a card to backlog:
```
python .claude/skills/planning-board/scripts/board.py add-card --title "Extract pricing logic" --desc "Move calc out of controller; add unit tests" --due 2026-06-20
```

Move a card between columns:
```
python .claude/skills/planning-board/scripts/board.py move-card --id card-003 --to in-progress
python .claude/skills/planning-board/scripts/board.py move-card --id card-003 --to done
```

Read current state (use this to recall card ids and where things stand):
```
python .claude/skills/planning-board/scripts/board.py list
```

Set a preference (theme is `dark` or `light`):
```
python .claude/skills/planning-board/scripts/board.py set-pref --key theme --value light
```

Print the viewer URL:
```
python .claude/skills/planning-board/scripts/board.py url
```

## How it works

- State lives in `.claude/boards/<board-id>.json`, one file per session, plus
  `index.json` (registry + active board).
- A local server (`scripts/server.py`, bound to `127.0.0.1:7842`) serves a
  read-only viewer and pushes live updates over Server-Sent Events whenever a
  board file changes — no commit required.
- The browser view is **read-only**: you (Claude) own all card moves via the CLI.

## Typical flow

1. Session starts → board auto-created by the SessionStart hook; tell the user the URL.
2. You plan the work → `add-card` for each task into backlog.
3. You begin a task → `move-card --to in-progress`.
4. You finish and verify it → `move-card --to done`.
5. User asks "where are we?" → `list`, and point them at the board URL.
