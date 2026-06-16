---
name: planning-board
description: >-
  Maintain a per-session Kanban planning board for the current Claude Code
  session. Work is grouped into EPICS, and every task is a CARD inside an epic
  that flows across columns: Backlog -> In Progress -> Blocked -> Done. Use this
  whenever you break work into tasks, plan a feature, start/finish/blocked a
  task, or the user asks about progress, "what's next", the plan, or the board.
  A board is auto-created at session start; keep it current.
---

# Planning Board

You maintain a live Kanban board for this coding session so the user can always
see where things stand. Structure: **board → epics → cards**. Every card belongs
to an epic. Columns are **backlog**, **in-progress**, **blocked**, **done**.

The browser view is **read-only**: you own all state changes via the CLI.

## Hard rules

1. **Never hand-edit the board JSON.** Change state only through:
   `python .claude/skills/planning-board/scripts/board.py <subcommand>`.
2. **Group work into epics.** Before adding cards, create an epic per feature /
   workstream with `add-epic`. If everything is one stream, the default "General"
   epic is fine.
3. **Add tasks as cards in an epic** (`add-card --epic <epic-id>`). New cards land
   in **backlog**.
4. **Move before you start.** Right before working a task, move its card to
   **in-progress**. Keep only one or a few in-progress at a time.
5. **Use blocked.** If a card is waiting on something (an API key, a review, an
   external dependency), move it to **blocked** and put the reason in its
   description.
6. **Move to done** when a task is finished *and verified*.
7. **Attach context** so a card is self-explanatory when clicked: `add-link` for
   referenced docs/specs/PRs/URLs, `add-image` for screenshots.
8. **Share the URL** when the board is created or after meaningful updates.
9. Keep titles short; detail goes in the description.

Run `list` whenever you need to recall epic ids, card ids, and current state.

## Commands

Run from the repo root. `--board` is optional (defaults to the active board).

Create / ensure this session's board:
```
python .claude/skills/planning-board/scripts/board.py create --title "Short name" --session "$CLAUDE_SESSION_ID" --start-server
```

Create an epic (prints its id, e.g. `epic-002`):
```
python .claude/skills/planning-board/scripts/board.py add-epic --title "Marketing email consent"
```

Add a card to an epic:
```
python .claude/skills/planning-board/scripts/board.py add-card --epic epic-002 --title "Build opt-in flow" --desc "Firestore entity + checkboxes; auditable" --due 2026-06-20
```

Move a card across columns:
```
python .claude/skills/planning-board/scripts/board.py move-card --id card-007 --to in-progress
python .claude/skills/planning-board/scripts/board.py move-card --id card-007 --to blocked
python .claude/skills/planning-board/scripts/board.py move-card --id card-007 --to done
```

Reassign a card to a different epic:
```
python .claude/skills/planning-board/scripts/board.py set-epic --id card-007 --epic epic-003
```

Attach a referenced document / URL:
```
python .claude/skills/planning-board/scripts/board.py add-link --id card-007 --label "Privacy policy" --url "docs/privacy_policy.md"
python .claude/skills/planning-board/scripts/board.py add-link --id card-007 --label "PR #12" --url "https://github.com/org/repo/pull/12"
```

Attach a screenshot (the file is copied into the board's attachments):
```
python .claude/skills/planning-board/scripts/board.py add-image --id card-007 --path ./screenshots/optin.png --label "Opt-in UI"
```

Inspect / read state:
```
python .claude/skills/planning-board/scripts/board.py list
python .claude/skills/planning-board/scripts/board.py show --id card-007
python .claude/skills/planning-board/scripts/board.py url
```

Preferences (theme is `vscode` or `light`):
```
python .claude/skills/planning-board/scripts/board.py set-pref --key theme --value light
```

## How it works

- State lives in `.claude/boards/<board-id>.json` (one file per session) plus
  `index.json`. Screenshots live in `.claude/boards/attachments/`.
- A local server (`scripts/server.py`, on `127.0.0.1`, auto free port) serves a
  read-only viewer and pushes live updates over SSE whenever a board changes.
- In the viewer each epic is a collapsible panel containing its own four columns;
  clicking a card opens a detail view with its description, linked documents, and
  screenshots.

## Typical flow

1. Session starts → board auto-created; tell the user the URL.
2. Plan → `add-epic` per workstream, then `add-card --epic` per task into backlog.
3. Begin a task → `move-card --to in-progress`; attach links/images for context.
4. Waiting on something → `move-card --to blocked` (reason in the description).
5. Finished & verified → `move-card --to done`.
6. "Where are we?" → `list`, and point the user at the board URL.
