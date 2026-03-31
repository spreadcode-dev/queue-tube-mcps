# QueueTube — MCP Pipelines

AI-augmented SDLC tooling for the QueueTube app. This repo contains GitHub Actions
pipelines that connect Figma, Claude, and GitHub Issues to automate design and
specification workflows.

---

## Pipelines

| Pipeline | Direction | Status |
|---|---|---|
| [Story Sync](#story-sync-pipeline) | Figma design → GitHub user story | ✅ Active |
| [Design Sync](#design-sync-pipeline) | GitHub issue spec → Figma design | ⚠️ Pending (Figma write access) |
| [Code Sync](#code-sync-pipeline) | Story issue → branch + PR | ✅ Active |

---

## Story Sync Pipeline

> **Figma screen → structured user story → GitHub Issue**

A designer shares a link to a finished Figma screen. The Story Agent fetches the
design context (screenshot + node structure) from the Figma REST API, passes it to
Claude, and creates a developer-ready user story as a new GitHub Issue.

### Flow

```
GitHub Issue
(contains Figma URL + node-id)
        │
        │  label: story-ready  ← human gate
        ▼
GitHub Actions
(.github/workflows/story-sync.yml)
        │
        ├── Figma REST API ──► node JSON + 2× PNG screenshot
        │
        ├── Anthropic API (Claude claude-sonnet-4-6)
        │        └── screenshot + node JSON + QueueTube design system context
        │                  └── structured user story with ACs + tech notes
        │
        ├── New GitHub Issue created
        │        └── label: story-draft
        │        └── body: user story + Figma reference
        │
        └── Comment posted on original issue
                 └── cross-reference link to the new story issue
```

### Label State Machine

| Label | Applied by | Meaning |
|---|---|---|
| `story-ready` | Human | Design is stable — trigger story generation |
| `story-draft` | Story Agent | Generated, pending human review |
| `story-approved` | Human | Reviewed — move to active backlog |
| `story-needs-revision` | Human | Send back to designer |

The `story-ready` label is removed from the source issue once the agent runs.
`story-draft` is applied to the **new story issue**, not the source issue.

### Usage

#### 1. Set GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys |
| `FIGMA_ACCESS_TOKEN` | Figma → Settings → Account → Personal Access Tokens |

> `FIGMA_ACCESS_TOKEN` requires at least `file_content:read` scope.

#### 2. Create a Figma Screen Issue

1. Click **Issues → New Issue → 📐 Figma Screen → User Story**
2. Paste the Figma share URL for the specific screen or component
   (right-click the frame in Figma → **Copy link to selection** — must include `node-id`)
3. Fill in the screen name, type, and any context notes
4. Submit the issue

#### 3. Trigger Story Generation

Add the `story-ready` label to the issue when the design is stable.

The workflow will run within ~1–2 minutes and:
- Create a new issue titled `[Story] <original title>` tagged `story-draft`
- Post a comment on your issue linking to the new story

#### 4. Re-run on Demand

To re-run the agent against the current issue body (e.g. after updating the Figma URL),
post a comment containing exactly:

```
/story sync
```

### What the Agent Produces

The agent creates **one GitHub Issue per user story** found in the design.
Each issue contains:

- **User story** in standard format (`As a … I want to … So that …`)
- **Acceptance criteria** — testable, component-specific, referencing design tokens
- **Technical notes** — gluestack-ui v3 component suggestions, token names, platform scope, edge cases
- **Figma reference** — direct link back to the source node

Example acceptance criteria output:
```
- [ ] Queue card uses bg-background-0 (#121212) background with border-outline-300 border
- [ ] Active queue uses bg-primary-500 (#E94560) left border accent
- [ ] Loading state renders skeleton cards matching the 2-column grid layout
- [ ] Empty state displays when API returns 0 queues
```

A summary comment is posted on the **source issue** linking to every generated story issue.

---

## Testing

### Option 1 — Run the script locally

The fastest feedback loop. Hits the real Figma API, real Claude API, and creates real GitHub Issues.

**1. Copy `.env.example` to `.env` and fill in your credentials:**

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `FIGMA_ACCESS_TOKEN` | Figma Personal Access Token (`file_content:read` scope) |
| `GITHUB_TOKEN` | GitHub Personal Access Token (`repo` scope — needs `issues:write`) |
| `REPO_FULL_NAME` | e.g. `spreadcode-dev/queue-tube-mcps` |
| `ISSUE_NUMBER` | Number of an existing issue to receive the cross-reference comment |
| `ISSUE_TITLE` | Human-readable title used in the story issue titles |
| `ISSUE_BODY` | Full issue body — must contain at least one Figma URL with `node-id` |

**2. Activate the virtual environment and run:**

```bash
source .venv/bin/activate
python scripts/story_agent.py
```

The script will print each step as it runs:

```
🚀 Story Agent — Issue #2: Queue List Home
📋 Issue body length: 1657 characters
✓ Figma file key: eAP0G94LO7SHwymq1Dw8wI  node ID: 13664:51
  Fetching Figma node data …
  Fetching Figma screenshot …
  Screenshot: 36,807 bytes
🤖 Calling Claude …
✓ Story generated.
✓ 4 user stories parsed.
✅ Story issue created: #7 — https://github.com/…
✅ Story issue created: #8 — https://github.com/…
✅ Comment posted: https://github.com/…
✓ Label removed from #2: story-ready
```

---

### Option 2 — Simulate the full Actions pipeline with `act`

[`act`](https://github.com/nektos/act) runs GitHub Actions locally inside Docker.
Use this to verify the workflow YAML, environment variable wiring, and step ordering
before merging to `main`.

**Prerequisites:** Docker running, `act` installed (`brew install act`).

**1. Edit `tests/story-sync-event.json`** to match the issue you want to test:

```json
{
  "action": "labeled",
  "label": { "name": "story-ready" },
  "issue": {
    "number": 2,
    "title": "Queue List Home",
    "body": "... issue body with Figma URL ..."
  },
  "repository": {
    "full_name": "spreadcode-dev/queue-tube-mcps",
    "name": "queue-tube-mcps",
    "owner": { "login": "spreadcode-dev" }
  },
  "sender": { "login": "spreadcode-dev" }
}
```

The `issue.body` must contain a Figma design URL with a `node-id` parameter, e.g.:
```
https://www.figma.com/design/eAP0G94LO7SHwymq1Dw8wI/QueueTube?node-id=13664-51
```

**2. Run `act`** with your `.env` as the secret file:

```bash
act issues \
  -e tests/story-sync-event.json \
  --container-architecture linux/amd64 \
  --secret-file .env
```

> **Note:** The `Post Set up Python` step will fail with `node: command not found` —
> this is a known `act` limitation with `setup-python@v5`'s cache step and does
> not affect the workflow logic. All pipeline steps pass cleanly.

---

## Code Sync Pipeline

> **Story issue → codebase context → code generation → branch + draft PR**

The Code Sync agent picks up a `story-approved` issue, loads a curated snapshot of
the QueueTube codebase, and passes it to Claude to generate integrable code.
The context loader runs first to ensure Claude always has the minimum necessary
context to produce code that matches existing architecture, imports, and tokens.

### Flow

```
GitHub Issue (story-approved)
        │
        │  label: code-ready  ← human gate
        ▼
GitHub Actions
(.github/workflows/code-sync.yml)
        │
        ├── context_loader.py
        │        ├── Layer 1: docs/code-context.md (curated baseline, always injected)
        │        ├── Layer 2: repo tree scan → up to 3 matching source files fetched
        │        └── Layer 3: assemble + write GitHub Actions step summary
        │
        ├── code_agent.py
        │        └── Claude generates code from assembled context + story
        │
        └── Branch + commit + draft PR created in queue-tube-web
```

### Label State Machine

| Label | Applied by | Meaning |
|---|---|---|
| `story-approved` | Human | Story reviewed — eligible for code generation |
| `code-ready` | Human | Trigger Code Sync agent |
| `code-draft` | Code Agent | Branch + draft PR created — pending human review |
| `code-approved` | Human | PR reviewed — ready to merge |
| `code-needs-revision` | Human | Post `/code sync` comment to re-trigger the agent |

### Context Loading Strategy

Context is assembled in three layers before code generation begins:

**Layer 1 — Curated Baseline (always injected)**
`docs/code-context.md` contains a manually maintained orientation guide:
- Top-2-level directory tree
- `package.json` dependency list
- Gluestack UI v3 provider config excerpt
- A reference component example
- Naming conventions and file organisation rules

Token budget: **≤ 2,000 tokens**. Must be updated by the team when the project
structure changes significantly.

**Layer 2 — Dynamic File Fetching (story-driven)**
The loader scans the story title and body for PascalCase identifiers (e.g.
`QueueCard`, `VideoItem`), searches the repo tree via the GitHub REST API, and
fetches up to **3 matching source files**. If no files match, the agent proceeds
with the baseline only — no error is thrown.

**Layer 3 — Assembly + Logging**
Final context order: `(1) baseline → (2) dynamic files → (3) story content`.
Total context is capped at `MAX_CONTEXT_TOKENS` (default: `6000`). A step summary
is written to GitHub Actions on every run listing token count, files included, and
any unmatched identifiers.

### Usage

#### 1. Set GitHub Secrets

| Secret | Purpose | Required scopes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key for code generation | — |
| `GH_PERSONAL_ACCESS_TOKEN` | Fine-grained PAT for `queue-tube-web` | `contents:write`, `pull-requests:write` |

> `GITHUB_TOKEN` (auto-generated by GitHub Actions) handles `issues:write` on this pipeline repo — no extra setup needed.
>
> ⚠️ The `GH_PERSONAL_ACCESS_TOKEN` for Code Sync needs **write** access to `queue-tube-web` — broader than Story Sync's read-only token. Use a dedicated fine-grained PAT scoped to that repo only.

#### 2. (Optional) Set Repository Variable

Set `MAX_CONTEXT_TOKENS` in **Settings → Variables → Actions** to override the
default context budget of `6000` tokens.

#### 3. Trigger Code Generation

Add the `code-ready` label to a `story-approved` issue.

The workflow will:
1. Load and log the context block (baseline + dynamic files)
2. Call Claude to generate code
3. Open a draft PR in `queue-tube-web` tagged `code-draft`

#### 4. Re-run on Demand

Post a comment containing exactly:

```
/code sync
```

#### 5. Local Test Mode (context loader only)

```bash
source .venv/bin/activate

# Baseline only (no GitHub calls)
python scripts/context_loader.py --issue-body "Build a QueueCard component"

# With dynamic file fetching
GH_PERSONAL_ACCESS_TOKEN=<your-token> python scripts/context_loader.py \
  --issue-title "QueueCard redesign" \
  --issue-body  "Update QueueCard to show VideoItem count below the title." \
  --repo        spreadcode-dev/queue-tube-web \
  --max-tokens  6000
```

The script prints the full assembled context and a token summary without calling
Claude or creating any GitHub resources.

**Git delivery dry run (branch name, commit message, and PR body — no API calls):**

```bash
source .venv/bin/activate

python scripts/git_delivery.py \
  --issue-number 10 \
  --issue-title  "[Story] Display QueueCard list on the Queue List Home screen" \
  --issue-body   "$(cat tests/code-sync-event.json | python3 -c \"import sys,json; print(json.load(sys.stdin)['issue']['body'])\")" \
  --files        src/components/QueueCard.tsx src/components/VideoItem.tsx
```

The script prints the derived branch name, scope, commit messages (first run and re-run), and the full PR body without making any GitHub API calls.

#### 6. Simulate the Full Actions Pipeline with `act`

[`act`](https://github.com/nektos/act) runs GitHub Actions locally inside Docker.
Use this to verify the workflow YAML, environment variable wiring, and step ordering
before merging to `main`.

**Prerequisites:** Docker running, `act` installed (`brew install act`).

**1. Edit `tests/code-sync-event.json`** to match the story issue you want to test:

```json
{
  "action": "labeled",
  "label": { "name": "code-ready" },
  "issue": {
    "number": 10,
    "title": "[Story] Display QueueCard list on the Queue List Home screen",
    "body": "... story body with component names like QueueCard, VideoItem ..."
  },
  "repository": {
    "full_name": "spreadcode-dev/queue-tube-mcps",
    "name": "queue-tube-mcps",
    "owner": { "login": "spreadcode-dev" }
  },
  "sender": { "login": "spreadcode-dev" }
}
```

The `issue.body` should contain the story's acceptance criteria and technical notes — the context loader
extracts PascalCase component identifiers (e.g. `QueueCard`, `VideoItem`) from this text.

**2. Run `act`** with your `.env` as the secret file:

```bash
act issues \
  -e tests/code-sync-event.json \
  --container-architecture linux/amd64 \
  --secret-file .env
```

> **Note:** The `Post Set up Python` step will fail with `node: command not found` —
> this is a known `act` limitation with `setup-python@v5`'s cache step and does
> not affect the workflow logic. All pipeline steps pass cleanly.
>
> **Note:** The label step will return a `410 Gone` when using the test payload
> (issue #10 doesn't exist in the repo). This is expected — all other steps pass cleanly.

---

### Maintaining the Baseline

`docs/code-context.md` is the agent's orientation guide. Keep it accurate:

- **Update** the directory tree when new packages or apps are added
- **Update** the dependency list when key packages change
- **Update** the reference component when conventions evolve
- **Never let it exceed 2,000 tokens** — check with:
  ```bash
  python -c "print(len(open('docs/code-context.md').read()) // 4, 'tokens')"
  ```

---

## Design Sync Pipeline

> **GitHub issue spec → Figma design** *(write path — pending Figma MCP write access)*

Reads a structured design spec from a GitHub Issue and uses Claude + the Figma MCP
server to create or update a Figma file.

**Trigger:** add the `design-spec` label to an issue created from the **🎨 Design Spec** template.

See [`docs/DESIGN_PIPELINE.md`](docs/DESIGN_PIPELINE.md) for full documentation.

---

## Repository Structure

```
queue-tube-mcps/
├── .github/
│   ├── workflows/
│   │   ├── story-sync.yml       # Figma → User Story pipeline
│   │   ├── design-sync.yml      # Spec → Figma pipeline
│   │   └── code-sync.yml        # Story → Code pipeline
│   └── ISSUE_TEMPLATE/
│       ├── figma-screen.yml     # Template for Story Sync
│       └── design-spec.yml      # Template for Design Sync
│
├── scripts/
│   ├── story_agent.py           # Story Sync agent (Figma REST API + Claude)
│   ├── design_agent.py          # Design Sync agent (Claude + Figma MCP)
│   ├── context_loader.py        # Code Sync — context loading module
│   ├── git_delivery.py          # Code Sync — branch, commit, and draft PR delivery
│   └── code_agent.py            # Code Sync — code generation (orchestrates above two)
│
├── docs/
│   ├── DESIGN_PIPELINE.md       # Design Sync documentation + design tokens
│   ├── code-context.md          # Curated baseline for Code Sync agent (maintained by team)
│   └── design-specs/            # Markdown specs for offline/batch use
│
└── requirements.txt
```

---

## Design System Reference

QueueTube uses **Gluestack UI v3** (NativeWind / Tailwind utility classes), dark-mode first.
All agent prompts are pre-loaded with the full token set — see
[`docs/DESIGN_PIPELINE.md#queuestube-design-tokens`](docs/DESIGN_PIPELINE.md#queuestube-design-tokens)
for the complete reference.

Key tokens:

| Token | Value | Usage |
|---|---|---|
| `bg-background-dark` | `#181719` | Page background, nav |
| `bg-background-0` | `#121212` | Cards, modals, bottom sheets |
| `bg-primary-500` | `#E94560` | CTAs, FAB, active states |
| `text-typography-900` | `#f5f5f5` | Body text on dark bg |
| `rounded-xl` | `12px` | Cards, panels, modals |
| `rounded-lg` | `8px` | Buttons, inputs |

---

## Requirements

- Python 3.12+
- GitHub Actions (secrets: `ANTHROPIC_API_KEY`, `FIGMA_ACCESS_TOKEN`)
- Figma Personal Access Token with `file_content:read` scope

Install dependencies locally:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
