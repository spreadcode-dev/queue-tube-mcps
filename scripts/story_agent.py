"""
QueueTube — Story Agent
=======================
Triggered by GitHub Actions when an issue is labeled 'story-ready'.
Extracts a Figma node URL from the issue body, fetches design context and a
screenshot from the Figma REST API, and asks Claude to generate a structured
user story.  The story is created as a new GitHub Issue (labeled 'story-draft')
and a cross-reference comment is posted on the original issue.

Label state machine (original issue):
  story-ready        → triggers this agent
  story-draft        → applied to the NEW story issue after generation

Flow:
  GitHub Issue (label: story-ready, body contains Figma URL with node-id)
      → GitHub Actions (this script)
          → Figma REST API  ──► node JSON + rendered PNG
          → Anthropic API (Claude)  ──► structured user story
          → New GitHub Issue (story-draft label)
          → Original issue gets a cross-reference comment
"""

import base64
import json
import os
import re
import requests
import anthropic


# ── Environment ───────────────────────────────────────────────────────────────


def get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    raise RuntimeError(
        f"Missing required environment variable: {name}. "
        "Configure the matching GitHub Actions secret before running this job."
    )


ANTHROPIC_API_KEY = get_required_env("ANTHROPIC_API_KEY")
FIGMA_ACCESS_TOKEN = get_required_env("FIGMA_ACCESS_TOKEN")
GITHUB_TOKEN = get_required_env("GITHUB_TOKEN")
ISSUE_NUMBER = get_required_env("ISSUE_NUMBER")
ISSUE_TITLE = os.environ.get("ISSUE_TITLE", "Untitled")
ISSUE_BODY = os.environ.get("ISSUE_BODY", "")
REPO_FULL_NAME = get_required_env("REPO_FULL_NAME")

GITHUB_API_BASE = "https://api.github.com"
FIGMA_API_BASE = "https://api.figma.com/v1"
MODEL = "claude-sonnet-4-6"

# Max characters of Figma node JSON passed to Claude alongside the screenshot
FIGMA_JSON_CHAR_LIMIT = 6_000


# ── Figma URL parsing ─────────────────────────────────────────────────────────


def extract_figma_node(text: str) -> tuple[str, str] | tuple[None, None]:
    """
    Parse a Figma design URL from text and return (file_key, node_id).
    Handles both /design/ and /file/ URL shapes.
    URL node-id uses '-' separators; the Figma REST API expects ':'.
    Returns (None, None) if no valid URL is found.
    """
    patterns = [
        r"figma\.com/design/([A-Za-z0-9]+)[^?\s]*\?[^#\s]*node-id=([0-9A-Za-z%\-]+)",
        r"figma\.com/file/([A-Za-z0-9]+)[^?\s]*\?[^#\s]*node-id=([0-9A-Za-z%\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            file_key = match.group(1)
            node_id = match.group(2).replace("%3A", ":").replace("-", ":")
            return file_key, node_id
    return None, None


# ── Figma REST API ────────────────────────────────────────────────────────────


def _figma_headers() -> dict:
    return {"X-Figma-Token": FIGMA_ACCESS_TOKEN}


def fetch_figma_node_json(file_key: str, node_id: str) -> str:
    """
    Fetch node structure from the Figma files API and return a condensed
    JSON string (truncated to FIGMA_JSON_CHAR_LIMIT characters).
    """
    url = f"{FIGMA_API_BASE}/files/{file_key}/nodes"
    resp = requests.get(url, headers=_figma_headers(), params={"ids": node_id})
    resp.raise_for_status()
    data = resp.json()
    condensed = json.dumps(data, indent=2)
    if len(condensed) > FIGMA_JSON_CHAR_LIMIT:
        condensed = condensed[:FIGMA_JSON_CHAR_LIMIT] + "\n… (truncated)"
    return condensed


def fetch_figma_screenshot(file_key: str, node_id: str) -> bytes | None:
    """
    Request a 2× PNG render of the node from the Figma images API.
    Returns raw PNG bytes, or None if the render is unavailable.
    """
    url = f"{FIGMA_API_BASE}/images/{file_key}"
    resp = requests.get(
        url,
        headers=_figma_headers(),
        params={"ids": node_id, "format": "png", "scale": "2"},
    )
    resp.raise_for_status()
    data = resp.json()

    # The response keys use ':' matching the node_id we sent
    image_url = data.get("images", {}).get(node_id)
    if not image_url:
        print("⚠️  No image URL returned by Figma for this node.")
        return None

    img_resp = requests.get(image_url, timeout=30)
    img_resp.raise_for_status()
    return img_resp.content


# ── Claude ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are a product specification agent for QueueTube — a video queue management app.
Your job is to translate Figma designs into structured, developer-ready user stories.

You will be given:
- A screenshot of the Figma screen or component
- The Figma node JSON (structure, layers, text content)
- The original GitHub issue context written by the designer/PM

From this you MUST:
1. Identify every primary user action visible in the design.
2. Produce one user story per primary action.
   If the screen covers multiple distinct actions, output multiple stories separated by ---

Each user story MUST use this exact format:

### User Story: <short imperative title>

**As a** <type of user>
**I want to** <goal>
**So that** <benefit>

#### Acceptance Criteria
- [ ] <testable, specific criterion>
- [ ] <reference token names where relevant, e.g. "Active card uses bg-primary-500 (#E94560) border">
- [ ] Include an AC for each distinct UI state: empty, loading, error, success

#### Technical Notes
- **Components:** <gluestack-ui v3 primitives — e.g. Pressable, FlatList, ActionSheet, BottomSheet>
- **Tokens used:** <list token names visible in the design — e.g. bg-background-0, rounded-xl>
- **Platform:** <Web / Mobile / Both — note responsive breakpoints if web>
- **Edge cases:** <empty state, loading skeleton, error state, offline behaviour>

#### Figma Reference
- Node: included in context
- File: included in context

---

QueueTube design system (Gluestack UI v3, dark-mode first):

Color tokens:
  bg-background-dark   (#181719)  — page background, nav
  bg-background-0      (#121212)  — cards, modals, bottom sheets
  bg-background-50     (#272625)  — elevated surfaces, sidebars
  bg-primary-500       (#E94560)  — CTAs, FAB, active states, badges
  bg-primary-400       (#f05a72)  — hover
  bg-primary-600       (#c73550)  — pressed
  text-typography-900  (#f5f5f5)  — body text on dark bg
  text-typography-400  (#8c8c8c)  — secondary text, labels
  text-typography-600  (#d4d4d4)  — placeholder, disabled text
  border-outline-300   (#737474)  — card borders, dividers
  border-outline-100   (#414141)  — subtle borders
  bg-error-400         (#e63535)  — destructive actions
  bg-success-500       (#489766)  — success states
  bg-info-400          (#0da6f2)  — info badges / links

Radius: rounded-xl (12px — cards/panels), rounded-lg (8px — buttons/inputs), rounded-full (avatars, FAB)
Typography: font-sans/font-roboto, text-2xs (10px) → text-2xl (24px), font-extrablack (950) for display

App context:
- Multiple named queues (e.g. "News", "Music") each holding YouTube-compatible video URLs.
- Users can play, reorder, rename, delete queues and their video items.
- Auth via AWS Cognito. Platforms: Web (Next.js, desktop-first ≥1280px) + React Native (Expo).

RULES FOR ACCEPTANCE CRITERIA:
- Every AC must be testable by a developer or QA engineer.
- Never write vague ACs like "the button looks correct" or "UI is consistent".
- Always reference token names, component names, and measurable behaviour.
"""


def run_story_agent(
    file_key: str,
    node_id: str,
    issue_context: str,
    node_json: str,
    screenshot_bytes: bytes | None,
) -> str:
    """
    Call Claude with the Figma screenshot + node JSON and return the
    generated user story text.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    text_block = {
        "type": "text",
        "text": (
            f"## Issue #{ISSUE_NUMBER}: {ISSUE_TITLE}\n\n"
            f"{issue_context}\n\n"
            f"---\n\n"
            f"**Figma file key:** `{file_key}`\n"
            f"**Figma node ID:** `{node_id}`\n\n"
            f"## Figma Node Structure\n\n"
            f"```json\n{node_json}\n```\n\n"
            f"Please generate the user stories based on the screenshot and node data above."
        ),
    }

    content: list[dict] = []

    if screenshot_bytes:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(screenshot_bytes).decode(),
            },
        })

    content.append(text_block)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    return response.content[0].text


# ── Story parser ─────────────────────────────────────────────────────────────


def split_stories(story_text: str) -> list[tuple[str, str]]:
    """
    Split Claude's output into individual (title, body) pairs.
    Each story block starts with '### User Story: <title>'.
    Leading '---' separators between blocks are stripped.
    Returns a list of (title, body) tuples in document order.
    """
    parts = re.split(r"(?=^### User Story:)", story_text, flags=re.MULTILINE)
    stories = []
    for part in parts:
        part = re.sub(r"^-{3,}\s*\n", "", part.strip()).strip()
        if not part:
            continue
        title_match = re.match(r"^### User Story:\s*(.+)$", part, re.MULTILINE)
        if title_match:
            stories.append((title_match.group(1).strip(), part))
    return stories


# ── GitHub helpers ────────────────────────────────────────────────────────────


def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def post_github_comment(issue_number: str, body: str) -> None:
    url = f"{GITHUB_API_BASE}/repos/{REPO_FULL_NAME}/issues/{issue_number}/comments"
    resp = requests.post(url, headers=_gh_headers(), json={"body": body})
    resp.raise_for_status()
    print(f"✅ Comment posted: {resp.json()['html_url']}")


def add_label(issue_number: str, label: str) -> None:
    url = f"{GITHUB_API_BASE}/repos/{REPO_FULL_NAME}/issues/{issue_number}/labels"
    resp = requests.post(url, headers=_gh_headers(), json={"labels": [label]})
    resp.raise_for_status()
    print(f"✓ Label added to #{issue_number}: {label}")


def remove_label(issue_number: str, label: str) -> None:
    url = f"{GITHUB_API_BASE}/repos/{REPO_FULL_NAME}/issues/{issue_number}/labels/{label}"
    resp = requests.delete(url, headers=_gh_headers())
    if resp.status_code not in (200, 204, 404):
        resp.raise_for_status()
    print(f"✓ Label removed from #{issue_number}: {label}")


def create_github_issue(title: str, body: str, labels: list[str]) -> dict:
    """Create a new GitHub Issue and return the API response dict."""
    url = f"{GITHUB_API_BASE}/repos/{REPO_FULL_NAME}/issues"
    resp = requests.post(
        url,
        headers=_gh_headers(),
        json={"title": title, "body": body, "labels": labels},
    )
    resp.raise_for_status()
    issue = resp.json()
    print(f"✅ Story issue created: #{issue['number']} — {issue['html_url']}")
    return issue


# ── Content builders ──────────────────────────────────────────────────────────


def build_story_issue_body(
    story_text: str, file_key: str, node_id: str, source_issue_number: str
) -> str:
    figma_url = f"https://www.figma.com/design/{file_key}?node-id={node_id.replace(':', '-')}"
    return (
        f"> **Auto-generated from Figma design** · "
        f"Source: #{source_issue_number} · "
        f"[Open in Figma]({figma_url})\n\n"
        f"> Review and approve before moving to the backlog. "
        f"Add `story-approved` when ready, or `story-needs-revision` to send back.\n\n"
        f"---\n\n"
        f"{story_text}\n\n"
        f"---\n"
        f"*Generated by the QueueTube Story Agent · Powered by Claude*"
    )


def build_link_comment(created_issues: list[dict]) -> str:
    count = len(created_issues)
    issue_lines = "\n".join(
        f"→ **#{i['number']}** {i['title']} — {i['html_url']}"
        for i in created_issues
    )
    return (
        f"## 📋 Story Agent — {count} User {'Story' if count == 1 else 'Stories'} Created\n\n"
        f"Draft {'story' if count == 1 else 'stories'} generated from the linked Figma design:\n\n"
        f"{issue_lines}\n\n"
        f"Review each issue and add `story-approved` to move it to the backlog, "
        f"or `story-needs-revision` to send it back for redesign.\n\n"
        f"---\n"
        f"*Generated by the QueueTube Story Agent · Powered by Claude + Figma REST API*"
    )


def build_error_comment(reason: str) -> str:
    return (
        f"## ⚠️ Story Agent — Generation failed\n\n"
        f"**Issue #{ISSUE_NUMBER} — {ISSUE_TITLE}**\n\n"
        f"{reason}\n\n"
        f"**To retry:** ensure the issue body contains a valid Figma design URL "
        f"with a `node-id` parameter, e.g.:\n"
        f"```\nhttps://www.figma.com/design/ABC123/QueueTube-UI?node-id=42-7\n```\n"
        f"Then re-add the `story-ready` label or post `/story sync`."
    )


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    print(f"🚀 Story Agent — Issue #{ISSUE_NUMBER}: {ISSUE_TITLE}")
    print(f"📋 Issue body length: {len(ISSUE_BODY)} characters")

    if not ISSUE_BODY.strip():
        print("❌ Issue body is empty.")
        post_github_comment(
            ISSUE_NUMBER,
            build_error_comment("The issue body is empty — no Figma URL to process."),
        )
        return

    file_key, node_id = extract_figma_node(ISSUE_BODY)
    if not file_key:
        print("❌ No Figma URL with node-id found in issue body.")
        post_github_comment(
            ISSUE_NUMBER,
            build_error_comment(
                "No Figma URL with a `node-id` parameter was found in the issue body."
            ),
        )
        return

    print(f"✓ Figma file key: {file_key}  node ID: {node_id}")

    print("  Fetching Figma node data …")
    node_json = fetch_figma_node_json(file_key, node_id)

    print("  Fetching Figma screenshot …")
    screenshot_bytes = fetch_figma_screenshot(file_key, node_id)
    if screenshot_bytes:
        print(f"  Screenshot: {len(screenshot_bytes):,} bytes")
    else:
        print("  Screenshot unavailable — continuing with node JSON only.")

    print("🤖 Calling Claude …")
    story_text = run_story_agent(
        file_key, node_id, ISSUE_BODY, node_json, screenshot_bytes
    )
    print("✓ Story generated.")

    stories = split_stories(story_text)
    print(f"✓ {len(stories)} user {'story' if len(stories) == 1 else 'stories'} parsed.")

    if not stories:
        post_github_comment(
            ISSUE_NUMBER,
            build_error_comment(
                "Claude returned a response but no `### User Story:` blocks could be parsed from it."
            ),
        )
        return

    # Create one GitHub Issue per user story
    created_issues = []
    for title, body in stories:
        issue = create_github_issue(
            title=f"[Story] {title}",
            body=build_story_issue_body(body, file_key, node_id, ISSUE_NUMBER),
            labels=["story-draft"],
        )
        created_issues.append(issue)

    # Cross-reference all created issues on the original issue
    post_github_comment(ISSUE_NUMBER, build_link_comment(created_issues))

    remove_label(ISSUE_NUMBER, "story-ready")


if __name__ == "__main__":
    main()
