"""
QueueTube — Code Agent
======================
Orchestrates the full Code Sync pipeline:

  1. context_loader.load_context()  — assemble codebase context
  2. Claude (claude-sonnet-4-6)     — generate code from context + story
  3. git_delivery.deliver()         — branch, commit, draft PR in queue-tube-web

Triggered by GitHub Actions (.github/workflows/code-sync.yml) when the
`code-ready` label is applied to a story issue, or when `/code sync` is posted.

Environment variables consumed:
  ANTHROPIC_API_KEY              — Anthropic API key
  GH_PERSONAL_ACCESS_TOKEN   — PAT with contents:write + pull-requests:write on WEB_REPO
  GITHUB_TOKEN                   — auto-provided; issues:write on MCPS_REPO
  ISSUE_NUMBER                   — source story issue number
  ISSUE_TITLE                    — source story issue title
  ISSUE_BODY                     — source story issue body
  WEB_REPO                       — target app repo (e.g. spreadcode-dev/queue-tube-web)
  MCPS_REPO                      — pipeline repo   (e.g. spreadcode-dev/queue-tube-mcps)
  MAX_CONTEXT_TOKENS             — context token budget (default: 6000)
  CONTEXT_FILE                   — optional: path to pre-assembled context (skips loader)
"""

import os
import re
import sys
import json
from pathlib import Path

import anthropic

# Sibling modules
sys.path.insert(0, str(Path(__file__).parent))
import context_loader
import git_delivery


# ── Configuration ─────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192


# ── Environment ───────────────────────────────────────────────────────────────


def _get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _require_env(name: str) -> str:
    value = _get_env(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Set it before running this script."
        )
    return value


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a senior React / TypeScript engineer on the QueueTube project.
Your task is to generate production-ready code that implements a user story.

You will receive:
  1. A codebase baseline snapshot (directory tree, dependencies, token config, reference component)
  2. Zero to three existing source files from the codebase (for context)
  3. The full user story with acceptance criteria and technical notes

Your output MUST be a single JSON object — no prose, no markdown fences, just raw JSON:

{
  "files": {
    "<path/to/File.tsx>": "<full file content as a string>",
    "<path/to/File.test.tsx>": "<full file content as a string>"
  },
  "notes": "<free-text summary of assumptions made, ACs not fully addressed, or decisions taken>"
}

Rules:
- Use the exact file paths and import aliases shown in the baseline context (@/* maps to src/)
- Use gluestack-ui v3 primitives imported from @/components/ui — never from @gluestack-ui/themed directly
- Style exclusively with NativeWind Tailwind utility classes using the QueueTube token aliases
  (e.g. bg-background-0, text-typography-900) — never raw hex values
- Write one test file per component using @testing-library/react + Vitest
- Follow Conventional Commits scope naming (kebab-case component name)
- Only generate the files needed to satisfy the story's acceptance criteria — no extras
- If a detail is ambiguous, make a reasonable assumption and document it in "notes"
"""


# ── Claude call ───────────────────────────────────────────────────────────────


def run_code_agent(context: str, api_key: str) -> tuple[dict[str, str], str]:
    """
    Call Claude with the assembled context and return (files_dict, notes).

    files_dict maps file path → file content.
    notes is the agent's free-text summary for the PR reviewer section.

    Raises ValueError if Claude's response cannot be parsed as the expected JSON.
    """
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
    )

    raw = response.content[0].text.strip()

    # Strip accidental markdown fences Claude might add despite instructions
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Claude returned non-JSON output. Parse error: {exc}\n\nRaw output:\n{raw[:500]}"
        ) from exc

    files = payload.get("files", {})
    notes = payload.get("notes", "")

    if not isinstance(files, dict):
        raise ValueError(f"Expected 'files' to be a dict, got: {type(files)}")

    print(f"✓ Claude generated {len(files)} file(s): {list(files.keys())}")
    return files, notes


# ── Step summary ──────────────────────────────────────────────────────────────


def write_step_summary(
    issue_number: str, issue_title: str, files: dict, notes: str
) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = [
        "## 🤖 Code Agent — Generation Summary\n",
        f"| | |",
        f"|---|---|",
        f"| **Issue** | #{issue_number} — {issue_title} |",
        f"| **Model** | `{MODEL}` |",
        f"| **Files generated** | {len(files)} |",
        "",
    ]
    if files:
        lines.append("### Generated Files\n")
        for path in files:
            lines.append(f"- `{path}`")
        lines.append("")
    if notes:
        lines.append("### Agent Notes\n")
        lines.append(notes)
        lines.append("")

    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    print("🤖 Code Agent — starting")

    # ── Environment ───────────────────────────────────────────────────────────
    api_key = _require_env("ANTHROPIC_API_KEY")
    issue_number = _require_env("ISSUE_NUMBER")
    issue_title = _get_env("ISSUE_TITLE", "Untitled")
    issue_body = _get_env("ISSUE_BODY", "")
    web_repo = _require_env("WEB_REPO")
    max_tokens = int(_get_env("MAX_CONTEXT_TOKENS", "6000"))

    story_text = f"{issue_title}\n\n{issue_body}".strip()
    print(f"   Issue #{issue_number}: {issue_title}")

    # ── Step 1: Context loading ───────────────────────────────────────────────
    context_file = _get_env("CONTEXT_FILE")
    if context_file and Path(context_file).exists():
        # Context was pre-assembled by the workflow's "Load codebase context" step
        context = Path(context_file).read_text(encoding="utf-8")
        print(f"✓ Context loaded from file: {context_file} ({len(context):,} chars)")
    else:
        # Fallback: assemble context inline (e.g. local run without the workflow step)
        gh_pat = _require_env("GH_PERSONAL_ACCESS_TOKEN")
        owner, repo = web_repo.split("/", 1)
        context = context_loader.load_context(
            story_text=story_text,
            owner=owner,
            repo=repo,
            gh_token=gh_pat,
            max_tokens=max_tokens,
        )

    # ── Step 2: Code generation ───────────────────────────────────────────────
    print("🤖 Calling Claude …")
    files, notes = run_code_agent(context, api_key)

    if not files:
        print("⚠️  Claude returned no files — aborting delivery.", file=sys.stderr)
        sys.exit(1)

    write_step_summary(issue_number, issue_title, files, notes)

    # ── Step 3: Git delivery ──────────────────────────────────────────────────
    result = git_delivery.deliver(
        files=files,
        issue_number=issue_number,
        issue_title=issue_title,
        story_text=story_text,
        notes=notes,
    )

    print(f"✅ Code Agent done — PR: {result['pr_url']}")


if __name__ == "__main__":
    main()
