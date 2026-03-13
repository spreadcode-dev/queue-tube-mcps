# QueueTube — Design Pipeline

Automated design generation: GitHub Issue → Claude AI → Figma.

---

## How It Works

```
Developer writes design spec
         │
         ▼
GitHub Issue  (label: design-spec)
         │
         ▼  triggers
GitHub Actions  (.github/workflows/design-sync.yml)
         │
         ▼  calls
scripts/design_agent.py
         │
         ├── Anthropic API (Claude claude-sonnet-4-20250514)
         │        │
         │        └── Figma MCP Server  ──► Figma File created/updated
         │
         ▼
GitHub Issue Comment  ◄── Figma URL posted back automatically
```

---

## Quick Start

### 1. Set GitHub Secrets

Go to **Settings → Secrets and variables → Actions** in your repo and add:

| Secret | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys |
| `FIGMA_ACCESS_TOKEN` | Figma → Settings → Account → Personal Access Tokens |
| `FIGMA_TEAM_ID` | Figma URL when viewing your team: `figma.com/files/team/{TEAM_ID}/` |

### 2. Create a Design Spec Issue

Use the **🎨 Design Spec** issue template:

1. Click **Issues → New Issue → 🎨 Design Spec**
2. Fill in the form — describe the screen, its elements, states, and platforms
3. Submit — the `design-spec` label is added automatically
4. Wait ~2–3 minutes for the bot comment with the Figma URL

### 3. Trigger a Re-sync

Already have an issue open and want to re-run the agent?
Post a comment on the issue containing exactly:

```
/design sync
```

The workflow will re-run against the current issue body.

---

## Repository Structure

```
queuestube/
├── .github/
│   ├── workflows/
│   │   └── design-sync.yml          # GitHub Actions pipeline
│   └── ISSUE_TEMPLATE/
│       └── design-spec.yml          # Structured issue form
│
├── scripts/
│   └── design_agent.py              # Claude + Figma MCP agent
│
└── docs/
    └── design-specs/                # Optional: markdown specs for
        ├── README.md                # batch or offline use
        └── *.md
```

---

## Design Specs as Markdown Files (Alternative)

For specs that don't need GitHub Issue tracking, place a markdown file in
`docs/design-specs/` and trigger the workflow manually:

```bash
gh workflow run design-sync.yml \
  -f spec_file=docs/design-specs/queue-player.md
```

> **Note:** The workflow currently reads from the Issue body. Markdown file
> support requires adding a `workflow_dispatch` trigger — see the workflow
> file comments for the extension point.

---

## QueueTube Design Tokens

The agent is pre-loaded with these tokens. Reference them in your specs.

| Token | Value | Usage |
|---|---|---|
| `--color-primary` | `#1A1A2E` | Page backgrounds, nav |
| `--color-surface` | `#16213E` | Cards, modals |
| `--color-accent` | `#E94560` | CTAs, active states, badges |
| `--color-text` | `#EAEAEA` | Body text |
| `--color-text-muted` | `#8892A4` | Secondary text, labels |
| `--radius-card` | `12px` | Queue cards, panels |
| `--radius-btn` | `8px` | Buttons, tags |
| `--font-family` | `Inter` | All text |

---

## Troubleshooting

**The workflow didn't trigger**
- Check the issue has the `design-spec` label — without it the job is skipped.

**`FIGMA_URL:` not found in bot comment**
- Expand the "Agent notes" section in the comment for the raw response.
- Check the Actions log for the full Claude output and any MCP errors.

**Figma MCP connection failed**
- Verify `FIGMA_ACCESS_TOKEN` is valid and has `file_content:write` scope.
- Confirm `FIGMA_TEAM_ID` is correct (numeric ID from the Figma URL).

**Rate limits**
- Anthropic: default tier allows ~50 req/min — fine for this use case.
- Figma API: 100 req/min per token — also fine.

---

## Extending the Pipeline

| Goal | What to change |
|---|---|
| Add Slack notification | Append a `curl` step to the workflow after the Python script |
| Support multiple Figma files | Pass `FIGMA_FILE_KEY` as an issue field and read it in the agent |
| Review gate before posting | Add a `workflow_dispatch` approval step between agent and comment |
| Store specs in a DB | Replace the Issue body read with a DB fetch in `design_agent.py` |
