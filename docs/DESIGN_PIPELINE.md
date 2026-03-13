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
All tokens follow the **Gluestack UI v3** naming convention — palette scale
(`{color}-{shade}`) for Tailwind utility classes, and
`--color-{color}-{shade}` for CSS variables in `config.ts`.

> QueueTube is **dark-mode first**. The dark-mode values below are the
> defaults; light-mode overrides are listed where they differ.

### Colors

| Token | Tailwind class | Dark value | Light value | Usage |
|---|---|---|---|---|
| `background-dark` | `bg-background-dark` | `#181719` | — | Page background, nav |
| `background-0` | `bg-background-0` | `#121212` | — | Cards, modals, bottom sheets |
| `background-50` | `bg-background-50` | `#272625` | — | Elevated surfaces, sidebars |
| `background-800` | `bg-background-800` | `#f2f1f1` | `#f2f1f1` | Light-mode page background |
| `primary-500` | `bg-primary-500` | `#E94560` ¹ | `#E94560` ¹ | CTAs, active states, FAB |
| `primary-400` | `bg-primary-400` | `#f05a72` ¹ | `#f05a72` ¹ | Button hover state |
| `primary-600` | `bg-primary-600` | `#c73550` ¹ | `#c73550` ¹ | Button pressed state |
| `secondary-0` | `bg-secondary-0` | `#141414` | — | Overlay backgrounds |
| `secondary-400` | `bg-secondary-400` | `#383939` | — | Inactive tab, muted surface |
| `typography-900` | `text-typography-900` | `#f5f5f5` | — | Body text (on dark bg) |
| `typography-0` | `text-typography-0` | `#171717` | — | Body text (on light bg) |
| `typography-400` | `text-typography-400` | `#8c8c8c` | `#8c8c8c` | Secondary text, labels |
| `typography-600` | `text-typography-600` | `#d4d4d4` | `#d4d4d4` | Placeholder, disabled text |
| `outline-300` | `border-outline-300` | `#737474` | — | Card borders, dividers |
| `outline-100` | `border-outline-100` | `#414141` | — | Subtle borders on dark bg |
| `error-400` | `bg-error-400` | `#e63535` | `#e63535` | Destructive actions |
| `success-500` | `bg-success-500` | `#489766` | `#489766` | Success toasts, confirmed |
| `info-400` | `bg-info-400` | `#0da6f2` | `#0da6f2` | Info badges, links |
| `warning-500` | `bg-warning-500` | `#fb954b` | `#fb954b` | Warning alerts |
| `background-error` | `bg-background-error` | `#422b2b` | — | Error toast background |
| `background-success` | `bg-background-success` | `#1c2b21` | — | Success toast background |
| `background-info` | `bg-background-info` | `#1a282e` | — | Info toast background |

¹ `primary` is **overridden** from the Gluestack v3 default (grey scale) to
QueueTube's accent red `#E94560`. Update `--color-primary-500` in
`gluestack-ui-provider/config.ts` — see [Customising Theme](#customising-theme).

### Radius

Gluestack v3 defers to **Tailwind CSS border-radius** utilities.

| Tailwind class | Value | Usage |
|---|---|---|
| `rounded-xl` | `12px` | Queue cards, panels, modals |
| `rounded-lg` | `8px` | Buttons, input fields, tags |
| `rounded-full` | `9999px` | Avatars, FAB, badge pills |
| `rounded-md` | `6px` | Small chips, tooltips |

### Typography

| Tailwind class | Value | Usage |
|---|---|---|
| `font-sans` | `Inter` (web) / `Roboto` (native) | All text |
| `font-roboto` | `Roboto` | Native fallback (added by gluestack) |
| `text-2xs` | `10px` | Tiny labels, timestamps (added by gluestack) |
| `text-xs` | `12px` | Captions, badges |
| `text-sm` | `14px` | Secondary text |
| `text-base` | `16px` | Body text |
| `text-xl` | `20px` | Card headings |
| `text-2xl` | `24px` | Screen titles |
| `font-extrablack` | `950` | Display headings (added by gluestack) |

### Customising Theme

Override `primary` in `components/ui/gluestack-ui-provider/config.ts`:

```ts
import { vars } from 'nativewind';

export const config = {
  dark: vars({
    '--color-primary-0':   '#7a0a22',
    '--color-primary-50':  '#8c0f27',
    '--color-primary-100': '#a01430',
    '--color-primary-200': '#b8193b',
    '--color-primary-300': '#cf1f45',
    '--color-primary-400': '#f05a72',  // hover
    '--color-primary-500': '#E94560',  // ← QueueTube accent
    '--color-primary-600': '#c73550',  // pressed
    '--color-primary-700': '#a02540',
    '--color-primary-800': '#7a1830',
    '--color-primary-900': '#550f20',
    '--color-primary-950': '#3a0a16',
  }),
  light: vars({
    '--color-primary-500': '#E94560',
    '--color-primary-400': '#f05a72',
    '--color-primary-600': '#c73550',
  }),
};
```

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
