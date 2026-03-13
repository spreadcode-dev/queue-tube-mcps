"""
QueueTube — Design Agent
========================
Triggered by GitHub Actions. Reads a design spec from a GitHub Issue,
calls Claude via the Anthropic API (with Figma MCP attached), and posts
the resulting Figma file URL back as a comment on the Issue.

Flow:
  GitHub Issue (label: design-spec)
      → GitHub Actions (this script)
          → Anthropic API + Figma MCP
              → Figma file created/updated
                  → GitHub Issue comment with Figma URL
"""

import os
import re
import json
import subprocess
import time
import requests
import anthropic

# ── Environment ──────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
FIGMA_ACCESS_TOKEN = os.environ["FIGMA_ACCESS_TOKEN"]
FIGMA_TEAM_ID      = os.environ.get("FIGMA_TEAM_ID", "")
GITHUB_TOKEN       = os.environ["GITHUB_TOKEN"]
ISSUE_NUMBER       = os.environ["ISSUE_NUMBER"]
ISSUE_TITLE        = os.environ.get("ISSUE_TITLE", "Design Spec")
ISSUE_BODY         = os.environ.get("ISSUE_BODY", "")
REPO_FULL_NAME     = os.environ["REPO_FULL_NAME"]   # e.g. "myorg/queuestube"

GITHUB_API_BASE    = "https://api.github.com"
MODEL              = "claude-sonnet-4-20250514"


# ── Figma MCP Server (stdio subprocess) ──────────────────────────────────────

def start_figma_mcp() -> subprocess.Popen:
    """Start the Figma MCP server as a local subprocess."""
    env = os.environ.copy()
    env["FIGMA_ACCESS_TOKEN"] = FIGMA_ACCESS_TOKEN

    proc = subprocess.Popen(
        ["npx", "-y", "@figma/mcp", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=False,
    )
    # Give the server a moment to initialise
    time.sleep(3)
    return proc


# ── Claude via Anthropic SDK (MCP client mode) ────────────────────────────────

def run_design_agent(spec: str) -> str:
    """
    Send the design spec to Claude with Figma MCP tools available.
    Returns Claude's final text response (which should contain the Figma URL).
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = """You are a UI/UX design agent for QueueTube — a video queue management app.
Your job is to translate written design specifications into Figma designs.

When given a design spec you MUST:
1. Use the Figma MCP tools to create or update the appropriate Figma file.
2. Follow QueueTube's design language:
   - Primary colour: #1A1A2E (deep navy)
   - Accent colour:  #E94560 (vivid red)
   - Surface colour: #16213E
   - Font: Inter (headings bold, body regular)
   - Border radius: 12px on cards, 8px on buttons
   - Dark theme by default
3. Create components (not just static frames) where possible.
4. After completing the design, output the Figma file URL on its own line,
   prefixed exactly with: FIGMA_URL:
   Example → FIGMA_URL: https://www.figma.com/file/ABC123/QueueTube-UI

Design system context:
- The app has multiple named queues (e.g. "News", "Music", "Tech Talks").
- Each queue holds an ordered list of YouTube-compatible video URLs.
- Users can play, reorder, and manage queues.
- Auth is handled by AWS Cognito (login / signup / forgot password screens needed).
- Target platforms: Web (Next.js desktop-first, mobile responsive).
"""

    user_message = f"""## Design Spec — Issue #{ISSUE_NUMBER}: {ISSUE_TITLE}

{spec}

Please create the Figma design(s) described above and return the Figma URL.
"""

    # Use the Anthropic SDK with MCP server configuration.
    # The SDK will manage the stdio MCP connection automatically when
    # mcp_servers is provided as URL-type servers. For local stdio servers
    # in CI we pass the Figma REST API via tool definitions below as fallback.
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        # Attach the Figma MCP server (URL mode — requires hosted MCP endpoint).
        # If your Figma MCP is self-hosted, replace the URL below.
        # For stdio mode see: scripts/design_agent_stdio.py
        extra_body={
            "mcp_servers": [
                {
                    "type": "url",
                    "url": "https://mcp.figma.com/mcp",   # Figma-hosted MCP endpoint
                    "name": "figma",
                    "authorization_token": FIGMA_ACCESS_TOKEN,
                }
            ]
        },
    )

    # Collect all text blocks from the response
    full_text = "\n".join(
        block.text for block in response.content if block.type == "text"
    )
    return full_text


# ── Parse Figma URL from Claude's response ────────────────────────────────────

def extract_figma_url(response_text: str) -> str | None:
    """Extract the FIGMA_URL: ... line from Claude's response."""
    match = re.search(r"FIGMA_URL:\s*(https://www\.figma\.com/\S+)", response_text)
    return match.group(1) if match else None


# ── GitHub — post comment on Issue ───────────────────────────────────────────

def post_github_comment(issue_number: str, body: str) -> None:
    url = f"{GITHUB_API_BASE}/repos/{REPO_FULL_NAME}/issues/{issue_number}/comments"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = requests.post(url, headers=headers, json={"body": body})
    resp.raise_for_status()
    print(f"✅ Comment posted: {resp.json()['html_url']}")


def build_comment(figma_url: str | None, claude_response: str, issue_number: str) -> str:
    if figma_url:
        return f"""## 🎨 Design Agent — Figma Update

**Issue #{issue_number} — {ISSUE_TITLE}**

The design has been created/updated in Figma:

🔗 **[Open in Figma]({figma_url})**

<details>
<summary>Agent notes</summary>

```
{claude_response[:2000]}
```
</details>

---
*Generated automatically by the QueueTube Design Agent · [Workflow run](${{GITHUB_SERVER_URL}}/${{GITHUB_REPOSITORY}}/actions)*
"""
    else:
        return f"""## ⚠️ Design Agent — Could not extract Figma URL

The agent ran but did not return a parseable Figma URL for Issue #{issue_number}.

<details>
<summary>Full agent response (debug)</summary>

```
{claude_response[:3000]}
```
</details>

Please check the [workflow logs](${{GITHUB_SERVER_URL}}/${{GITHUB_REPOSITORY}}/actions) for details.
"""


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print(f"🚀 Design Agent starting for Issue #{ISSUE_NUMBER}: {ISSUE_TITLE}")
    print(f"📋 Spec length: {len(ISSUE_BODY)} characters")

    if not ISSUE_BODY.strip():
        print("❌ Issue body is empty — nothing to do.")
        return

    print("🤖 Calling Claude + Figma MCP …")
    claude_response = run_design_agent(ISSUE_BODY)
    print("Claude response received.")

    figma_url = extract_figma_url(claude_response)
    if figma_url:
        print(f"✅ Figma URL: {figma_url}")
    else:
        print("⚠️  No FIGMA_URL found in response — will post debug comment.")

    comment_body = build_comment(figma_url, claude_response, ISSUE_NUMBER)
    post_github_comment(ISSUE_NUMBER, comment_body)


if __name__ == "__main__":
    main()
