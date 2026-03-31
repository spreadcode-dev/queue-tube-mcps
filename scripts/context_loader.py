"""
QueueTube — Context Loader
==========================
Assembles the context block injected into the Code Sync agent prompt before
code generation begins. Uses a two-layer hybrid strategy:

  Layer 1 — Curated baseline (docs/code-context.md): always injected.
  Layer 2 — Dynamic file fetching: scans the story for component name
             identifiers and fetches up to MAX_DYNAMIC_FILES matching source
             files from the GitHub repo tree.
  Layer 3 — Assembly + logging: combines the layers in a fixed order and
             writes a GitHub Actions step summary.

Output order: (1) baseline → (2) dynamic files → (3) story content

Local test mode (no GitHub / Claude calls):
  python scripts/context_loader.py --issue-body "QueueCard VideoItem ..."
"""

import argparse
import os
import re
import sys
from pathlib import Path

import requests


# ── Configuration ─────────────────────────────────────────────────────────────

GITHUB_API_BASE = "https://api.github.com"

# Path to the curated baseline, relative to the repo root (fallback)
BASELINE_PATH = Path(__file__).parent.parent / "docs" / "code-context.md"

# Path in the source repo where a project-specific baseline may live
SOURCE_BASELINE_FILE = "docs/code-context.md"

# Maximum number of dynamic files fetched per run
MAX_DYNAMIC_FILES = 3

# Token estimation heuristic: characters / 4
CHARS_PER_TOKEN = 4

# Regex to extract PascalCase identifiers (likely component/screen names)
IDENTIFIER_PATTERN = re.compile(r"\b([A-Z][a-zA-Z0-9]{2,})\b")

# File extensions to consider when searching the repo tree
SOURCE_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js"}

# Baseline token hard limit — warn if exceeded
BASELINE_TOKEN_LIMIT = 2_000


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


# ── Token estimation ──────────────────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """Character-count heuristic: len(text) / 4. No external tokenizer needed."""
    return max(1, len(text) // CHARS_PER_TOKEN)


# ── Layer 1: Curated baseline ─────────────────────────────────────────────────


def _fetch_remote_baseline(owner: str, repo: str, gh_token: str) -> str | None:
    """
    Try to fetch docs/code-context.md from the source repo.
    Returns the file content on success, None if the file doesn't exist or
    any network/auth error occurs (soft failure — caller falls back to local).
    """
    import base64

    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{SOURCE_BASELINE_FILE}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        raw = base64.b64decode(resp.json()["content"]).decode("utf-8", errors="replace")
        return raw
    except Exception as exc:
        print(f"⚠️  Could not fetch remote baseline: {exc}", file=sys.stderr)
        return None


def load_baseline(owner: str = "", repo: str = "", gh_token: str = "") -> str:
    """
    Load the curated baseline context.

    Priority:
      1. docs/code-context.md from the SOURCE_REPO (if owner/repo/token are provided)
      2. docs/code-context.md bundled in queue-tube-mcps (fallback)

    Warns (but does not raise) if the token budget is exceeded.
    """
    content: str | None = None
    source_label = ""

    if owner and repo and gh_token:
        content = _fetch_remote_baseline(owner, repo, gh_token)
        if content is not None:
            source_label = f"{owner}/{repo}"
            print(f"✓ Baseline loaded from {source_label} ({SOURCE_BASELINE_FILE})")

    if content is None:
        if not BASELINE_PATH.exists():
            raise FileNotFoundError(
                f"Curated baseline not found at {BASELINE_PATH}. "
                "Create docs/code-context.md before running the Code Sync agent."
            )
        content = BASELINE_PATH.read_text(encoding="utf-8")
        source_label = "queue-tube-mcps (local fallback)"
        print(f"✓ Baseline loaded from {source_label}")

    tokens = estimate_tokens(content)
    if tokens > BASELINE_TOKEN_LIMIT:
        print(
            f"⚠️  Baseline token budget exceeded: {tokens} tokens "
            f"(limit: {BASELINE_TOKEN_LIMIT}). Trim docs/code-context.md.",
            file=sys.stderr,
        )

    print(f"  ({len(content):,} chars, ~{tokens} tokens)")
    return content


# ── Layer 2: Dynamic file fetching ────────────────────────────────────────────


def extract_identifiers(text: str) -> list[str]:
    """
    Scan text for PascalCase identifiers that look like component or screen names.
    Returns a deduplicated list in order of first appearance.
    """
    seen: set[str] = set()
    result: list[str] = []
    for match in IDENTIFIER_PATTERN.finditer(text):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def fetch_repo_tree(owner: str, repo: str, gh_token: str) -> list[dict]:
    """
    Fetch the full recursive repo tree from the GitHub REST API.
    Returns a list of tree entry dicts with at least 'path' and 'url'.
    """
    # Get the default branch HEAD SHA first
    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    repo_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    resp = requests.get(repo_url, headers=headers, timeout=15)
    resp.raise_for_status()
    sha = resp.json()["default_branch"]

    # Resolve the branch to a commit SHA
    branch_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/branches/{sha}"
    resp = requests.get(branch_url, headers=headers, timeout=15)
    resp.raise_for_status()
    commit_sha = resp.json()["commit"]["sha"]

    # Fetch the recursive tree
    tree_url = (
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{commit_sha}" "?recursive=1"
    )
    resp = requests.get(tree_url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("truncated"):
        print(
            "⚠️  GitHub tree response was truncated. Large monorepos may return "
            "incomplete results.",
            file=sys.stderr,
        )

    return [entry for entry in data.get("tree", []) if entry.get("type") == "blob"]


def score_file_match(path: str, identifiers: list[str]) -> int:
    """
    Score a file path against a list of identifiers.
    Returns the length of the best-matching identifier found in the filename
    (longer match = higher score). Returns 0 if no match.
    """
    filename = Path(
        path
    ).stem  # e.g. "QueueCard" from "apps/mobile/src/components/QueueCard.tsx"
    for identifier in identifiers:
        # Case-insensitive substring match between identifier and filename
        if (
            identifier.lower() in filename.lower()
            or filename.lower() in identifier.lower()
        ):
            return len(identifier)
    return 0


def select_dynamic_files(
    tree_entries: list[dict], identifiers: list[str]
) -> tuple[list[dict], list[str]]:
    """
    Select up to MAX_DYNAMIC_FILES tree entries that best match the identifiers.
    Returns (selected_entries, unmatched_identifiers).
    """
    # Filter to source files only
    source_entries = [
        e for e in tree_entries if Path(e["path"]).suffix in SOURCE_EXTENSIONS
    ]

    # Score every source file against all identifiers
    scored = [(score_file_match(e["path"], identifiers), e) for e in source_entries]
    scored = [(score, e) for score, e in scored if score > 0]
    scored.sort(key=lambda x: x[0], reverse=True)

    selected = [e for _, e in scored[:MAX_DYNAMIC_FILES]]
    selected_paths = {Path(e["path"]).stem.lower() for e in selected}

    # Determine which identifiers had no match
    unmatched = [
        ident
        for ident in identifiers
        if not any(ident.lower() in p or p in ident.lower() for p in selected_paths)
    ]

    return selected, unmatched


def fetch_file_content(owner: str, repo: str, path: str, gh_token: str) -> str:
    """Fetch a single file's raw content from GitHub."""
    import base64

    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return raw


def load_dynamic_files(
    story_text: str,
    owner: str,
    repo: str,
    gh_token: str,
) -> tuple[list[tuple[str, str]], list[str]]:
    """
    Scan story_text for identifiers, fetch matching files from the repo.
    Returns (list of (path, content) tuples, list of unmatched identifiers).
    Falls back to empty list on any error — never halts the pipeline.
    """
    identifiers = extract_identifiers(story_text)
    print(f"✓ Identifiers extracted: {identifiers or '(none)'}")

    if not identifiers:
        return [], []

    try:
        repo_parts = f"{owner}/{repo}".split("/")
        tree = fetch_repo_tree(repo_parts[0], repo_parts[1], gh_token)
    except Exception as exc:
        print(f"⚠️  Could not fetch repo tree: {exc}", file=sys.stderr)
        return [], identifiers

    selected, unmatched = select_dynamic_files(tree, identifiers)
    print(f"✓ Dynamic files selected: {[e['path'] for e in selected] or '(none)'}")
    if unmatched:
        print(f"  ↳ Unmatched identifiers: {unmatched}")

    fetched: list[tuple[str, str]] = []
    for entry in selected:
        try:
            content = fetch_file_content(
                repo_parts[0], repo_parts[1], entry["path"], gh_token
            )
            fetched.append((entry["path"], content))
            print(f"  ✓ Fetched: {entry['path']} ({len(content):,} chars)")
        except Exception as exc:
            print(f"  ⚠️  Could not fetch {entry['path']}: {exc}", file=sys.stderr)

    return fetched, unmatched


# ── Layer 3: Assembly + logging ───────────────────────────────────────────────


def assemble_context(
    baseline: str,
    dynamic_files: list[tuple[str, str]],
    story_content: str,
    max_tokens: int,
) -> str:
    """
    Assemble the final context block in fixed order:
      1. Curated baseline
      2. Dynamic files (0–3)
      3. Story content

    Truncates dynamic file content if the total would exceed max_tokens.
    Never truncates the baseline or the story.
    """
    parts = [
        "## Codebase Baseline Context\n\n" + baseline,
    ]

    for path, content in dynamic_files:
        ext = Path(path).suffix.lstrip(".")
        parts.append(f"## Source File: `{path}`\n\n```{ext}\n{content}\n```")

    parts.append("## User Story\n\n" + story_content)

    assembled = "\n\n---\n\n".join(parts)

    # Enforce max_tokens budget — trim dynamic file blocks if needed
    total = estimate_tokens(assembled)
    if total > max_tokens and dynamic_files:
        # Rebuild without dynamic files to see the floor
        floor = "\n\n---\n\n".join([parts[0], parts[-1]])
        floor_tokens = estimate_tokens(floor)
        budget_for_dynamic = max_tokens - floor_tokens

        trimmed_dynamic: list[tuple[str, str]] = []
        remaining = budget_for_dynamic * CHARS_PER_TOKEN
        for path, content in dynamic_files:
            if remaining <= 0:
                break
            allowed = min(len(content), remaining)
            truncated = content[:allowed]
            if allowed < len(content):
                truncated += "\n… (truncated to fit token budget)"
            trimmed_dynamic.append((path, truncated))
            remaining -= allowed

        return assemble_context(
            baseline, trimmed_dynamic, story_content, max_tokens + 1
        )

    return assembled


def write_step_summary(
    baseline_tokens: int,
    dynamic_files: list[tuple[str, str]],
    unmatched: list[str],
    total_tokens: int,
    max_tokens: int,
) -> None:
    """
    Write a GitHub Actions step summary if GITHUB_STEP_SUMMARY is set.
    Safe to call locally — silently skips if the env var is absent.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = [
        "## 🧠 Code Context Loader — Summary\n",
        f"| | |",
        f"|---|---|",
        f"| **Total tokens (estimated)** | {total_tokens} / {max_tokens} |",
        f"| **Baseline tokens** | {baseline_tokens} |",
        f"| **Dynamic files fetched** | {len(dynamic_files)} / {MAX_DYNAMIC_FILES} |",
        "",
    ]

    if dynamic_files:
        lines.append("### Dynamic Files Included\n")
        for path, content in dynamic_files:
            lines.append(f"- `{path}` (~{estimate_tokens(content)} tokens)")
        lines.append("")

    if unmatched:
        lines.append("### Unmatched Identifiers\n")
        lines.append(
            "> These identifiers were found in the story but no source file matched.\n"
        )
        for ident in unmatched:
            lines.append(f"- `{ident}`")
        lines.append("")

    summary_text = "\n".join(lines)

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(summary_text)

    print("✓ Step summary written.")


# ── Public API ────────────────────────────────────────────────────────────────


def load_context(
    story_text: str,
    owner: str,
    repo: str,
    gh_token: str,
    max_tokens: int,
) -> str:
    """
    Entry point for code_agent.py. Returns the fully assembled context string.

    Args:
        story_text:  Full text of the story issue (title + body + ACs).
        owner:       GitHub repo owner (e.g. "spreadcode-dev").
        repo:        GitHub repo name (e.g. "queue-tube").
        gh_token:    GitHub PAT with contents:read scope.
        max_tokens:  Hard upper bound on total injected context tokens.

    Returns:
        Assembled context block as a single string.
    """
    print("── Context Loader ──────────────────────────────────────────────")

    # Layer 1
    baseline = load_baseline(owner, repo, gh_token)
    baseline_tokens = estimate_tokens(baseline)

    # Layer 2
    dynamic_files, unmatched = load_dynamic_files(story_text, owner, repo, gh_token)

    # Layer 3
    context = assemble_context(baseline, dynamic_files, story_text, max_tokens)
    total_tokens = estimate_tokens(context)

    print(f"✓ Context assembled: ~{total_tokens} tokens (limit: {max_tokens})")

    write_step_summary(
        baseline_tokens, dynamic_files, unmatched, total_tokens, max_tokens
    )

    print("────────────────────────────────────────────────────────────────")
    return context


# ── CLI / local test mode ─────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "QueueTube Context Loader — assemble codebase context for the Code Sync agent.\n\n"
            "Local test mode: prints the assembled context and token estimate without "
            "calling Claude or creating any GitHub resources."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--issue-body",
        metavar="TEXT",
        default="",
        help="Story issue body text (used to extract identifiers for dynamic fetching).",
    )
    parser.add_argument(
        "--issue-title",
        metavar="TEXT",
        default="",
        help="Story issue title (included in identifier extraction).",
    )
    parser.add_argument(
        "--repo",
        metavar="OWNER/REPO",
        default="",
        help=(
            "GitHub repo to search for dynamic files (e.g. spreadcode-dev/queue-tube). "
            "If omitted, dynamic fetching is skipped and only the baseline is loaded."
        ),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("MAX_CONTEXT_TOKENS", "6000")),
        help="Maximum total context tokens (default: MAX_CONTEXT_TOKENS env var or 6000).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    story_text = f"{args.issue_title}\n\n{args.issue_body}".strip()
    max_tokens = args.max_tokens

    print(f"🧠 Context Loader — local test mode")
    print(f"   Story text length : {len(story_text):,} chars")
    print(f"   Max tokens        : {max_tokens}")

    # Layer 2: dynamic fetching only if --repo is given and GH_PERSONAL_ACCESS_TOKEN is set
    dynamic_files: list[tuple[str, str]] = []
    unmatched: list[str] = []
    owner, repo, gh_token = "", "", ""

    if args.repo and "/" in args.repo:
        gh_token = _get_env("GH_PERSONAL_ACCESS_TOKEN")
        if not gh_token:
            print(
                "⚠️  GH_PERSONAL_ACCESS_TOKEN not set — skipping dynamic file fetching.",
                file=sys.stderr,
            )
        else:
            owner, repo = args.repo.split("/", 1)
            dynamic_files, unmatched = load_dynamic_files(
                story_text, owner, repo, gh_token
            )

    if not args.repo and story_text:
        identifiers = extract_identifiers(story_text)
        print(f"✓ Identifiers found (no repo specified, skipping fetch): {identifiers or '(none)'}")

    # Layer 1: load baseline — prefer source repo, fall back to local
    baseline = load_baseline(owner, repo, gh_token)
    baseline_tokens = estimate_tokens(baseline)

    # Layer 3: assemble + print
    context = assemble_context(
        baseline, dynamic_files, story_text or "(no story provided)", max_tokens
    )
    total_tokens = estimate_tokens(context)

    print("\n" + "=" * 64)
    print(context)
    print("=" * 64)
    print(f"\n📊 Summary:")
    print(f"   Baseline tokens   : ~{baseline_tokens}")
    print(f"   Dynamic files     : {len(dynamic_files)}")
    print(f"   Total tokens      : ~{total_tokens} / {max_tokens}")
    if unmatched:
        print(f"   Unmatched idents  : {unmatched}")


if __name__ == "__main__":
    main()
