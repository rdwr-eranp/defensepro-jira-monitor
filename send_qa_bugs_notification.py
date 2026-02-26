"""
QA Bugs Email Notification

Fetches all bugs currently in QA status from Jira and prepares an email
to QA team members via Outlook (opens for review before sending).

Usage:
    python send_qa_bugs_notification.py                    # Open email in Outlook for review
    python send_qa_bugs_notification.py --send             # Send immediately
    python send_qa_bugs_notification.py --version 10.13.0.0
    python send_qa_bugs_notification.py --all-versions     # Include all fix versions
    python send_qa_bugs_notification.py --dry-run          # Print only, no Outlook
"""

import os
import argparse
import urllib3
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
from jira import JIRA

try:
    import win32com.client
    OUTLOOK_AVAILABLE = True
except ImportError:
    OUTLOOK_AVAILABLE = False

load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JIRA_URL = os.getenv("JIRA_URL", "https://rwrnd.atlassian.net")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")

# QA recipient list – override via env var QA_RECIPIENTS (comma-separated)
DEFAULT_QA_RECIPIENTS = os.getenv(
    "QA_RECIPIENTS",
    "qa-team@radware.com"
)

# Jira statuses that represent "on QA" – adjust to match your workflow
QA_STATUSES = ["Completed"]

PRIORITY_EMOJI = {
    "Blocker": "🔴",
    "Critical": "🔴",
    "High": "🟠",
    "Medium": "🟡",
    "Low": "🟢",
}

PRIORITY_ORDER = ["Blocker", "Critical", "High", "Medium", "Low"]

# ---------------------------------------------------------------------------
# Jira helpers
# ---------------------------------------------------------------------------

def connect_jira() -> JIRA:
    options = {"server": JIRA_URL, "verify": False}
    return JIRA(options=options, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))


def fetch_qa_bugs(jira: JIRA, version: str = None, skip_runners: bool = True):
    """Fetch bugs currently sitting in a QA status."""
    status_clause = ", ".join(f'"{s}"' for s in QA_STATUSES)
    jql = (
        f"project = DP AND issuetype = Bug "
        f"AND status IN ({status_clause}) "
        f"ORDER BY fixVersion DESC, priority DESC"
    )
    if version:
        jql = (
            f"project = DP AND issuetype = Bug "
            f"AND status IN ({status_clause}) "
            f'AND fixVersion = "{version}" '
            f"ORDER BY priority DESC"
        )

    fields = "key,summary,priority,status,assignee,fixVersions,customfield_10129"
    issues = jira.search_issues(jql, maxResults=False, fields=fields)

    bugs = []
    for issue in issues:
        # Optionally skip DP Runners team
        if skip_runners:
            team = getattr(issue.fields, "customfield_10129", None)
            if team:
                team_name = team.value if hasattr(team, "value") else str(team)
                if team_name == "DP Runners":
                    continue

        assignee = issue.fields.assignee
        assignee_name = assignee.displayName if assignee else "Unassigned"
        assignee_email = assignee.emailAddress if assignee else ""

        fix_versions = issue.fields.fixVersions
        fix_version = fix_versions[0].name if fix_versions else "Unassigned"

        priority = issue.fields.priority.name if issue.fields.priority else "Medium"
        status = issue.fields.status.name if issue.fields.status else ""

        bugs.append({
            "key": issue.key,
            "summary": issue.fields.summary,
            "priority": priority,
            "status": status,
            "assignee_name": assignee_name,
            "assignee_email": assignee_email,
            "fix_version": fix_version,
        })

    return bugs


# ---------------------------------------------------------------------------
# HTML email builder
# ---------------------------------------------------------------------------

def priority_sort_key(bug):
    try:
        return PRIORITY_ORDER.index(bug["priority"])
    except ValueError:
        return len(PRIORITY_ORDER)


def build_html_email(bugs: list, version_label: str) -> str:
    """Build a rich HTML email summarising all QA bugs."""

    if not bugs:
        return "<html><body><p>No bugs currently on QA.</p></body></html>"

    # Sort by priority
    bugs_sorted = sorted(bugs, key=priority_sort_key)

    # Priority summary counts
    priority_counts = defaultdict(int)
    for b in bugs_sorted:
        priority_counts[b["priority"]] += 1

    summary_rows = ""
    for p in PRIORITY_ORDER:
        if priority_counts[p]:
            emoji = PRIORITY_EMOJI.get(p, "⚪")
            summary_rows += f"<tr><td>{emoji} {p}</td><td><strong>{priority_counts[p]}</strong></td></tr>"

    # Group by fix version
    by_version = defaultdict(list)
    for b in bugs_sorted:
        by_version[b["fix_version"]].append(b)

    version_sections = ""
    for ver in sorted(by_version.keys(), reverse=True):
        ver_bugs = by_version[ver]
        rows = ""
        for b in ver_bugs:
            emoji = PRIORITY_EMOJI.get(b["priority"], "⚪")
            rows += f"""
                <tr>
                    <td><a href="{JIRA_URL}/browse/{b['key']}" style="color:#0066cc;">{b['key']}</a></td>
                    <td>{emoji} {b['priority']}</td>
                    <td>{b['status']}</td>
                    <td>{b['summary']}</td>
                    <td>{b['assignee_name']}</td>
                </tr>"""

        version_sections += f"""
        <h3 style="color:#2c3e50; border-bottom:2px solid #4472C4; padding-bottom:6px;
                   margin-top:30px;">
            Release {ver} &nbsp;
            <span style="font-size:13px; color:#777; font-weight:normal;">
                ({len(ver_bugs)} bug{'s' if len(ver_bugs) != 1 else ''})
            </span>
        </h3>
        <table border="1" cellpadding="8" cellspacing="0"
               style="border-collapse:collapse; width:100%; font-size:13px;">
            <tr style="background-color:#4472C4; color:white;">
                <th style="width:90px;">Bug ID</th>
                <th style="width:100px;">Priority</th>
                <th style="width:110px;">Status</th>
                <th>Summary</th>
                <th style="width:160px;">Assignee</th>
            </tr>
            {rows}
        </table>"""

    total = len(bugs_sorted)
    now = datetime.now().strftime("%d %b %Y, %H:%M")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body      {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; margin: 20px; }}
  h2        {{ color: #4472C4; }}
  table     {{ border-collapse: collapse; margin-bottom: 10px; }}
  th, td    {{ border: 1px solid #ccc; padding: 7px 10px; text-align: left; vertical-align: top; }}
  tr:nth-child(even) {{ background-color: #f7f7f7; }}
  .badge    {{ display:inline-block; padding:3px 8px; border-radius:4px;
               background:#e8f0fe; color:#1a56db; font-size:12px; font-weight:bold; }}
</style>
</head>
<body>

<h2>🐞 Bugs On QA – {version_label}</h2>

<p>
  Hi QA Team,<br><br>
  The following <strong>{total} bug{'s' if total != 1 else ''}</strong> are currently sitting
  in a <strong>QA verification</strong> status as of <em>{now}</em>.<br>
  Please review, test, and update each bug status to <strong>Accepted</strong> once verified,
  or re-open if the fix is insufficient.
</p>

<h3 style="color:#2c3e50; margin-bottom:4px;">Priority Summary</h3>
<table border="1" cellpadding="7" cellspacing="0"
       style="border-collapse:collapse; width:220px; margin-bottom:24px;">
  <tr style="background-color:#4472C4; color:white;"><th>Priority</th><th>Count</th></tr>
  {summary_rows}
  <tr style="background-color:#f0f0f0; font-weight:bold;">
    <td>Total</td><td>{total}</td>
  </tr>
</table>

{version_sections}

<br>
<p style="color:#555; font-size:13px;">
  This email was generated automatically from Jira.<br>
  Click any Bug ID to open the issue directly in Jira.
</p>

</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Email dispatch via Outlook
# ---------------------------------------------------------------------------

def open_in_outlook(to_recipients: list, subject: str, html_body: str, send: bool = False):
    if not OUTLOOK_AVAILABLE:
        print("❌ win32com not available. Install pywin32: pip install pywin32")
        print("   Falling back to dry-run output only.")
        return False

    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = "; ".join(to_recipients)
        mail.Subject = subject
        mail.HTMLBody = html_body

        if send:
            mail.Send()
            print(f"✅ Email sent to: {', '.join(to_recipients)}")
        else:
            mail.Display()
            print(f"✅ Email opened in Outlook for review.")
            print(f"   To: {', '.join(to_recipients)}")
            print(f"   Subject: {subject}")
        return True

    except Exception as exc:
        print(f"❌ Outlook error: {exc}")
        print("   Make sure Outlook is installed and running.")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Send QA bugs email notification via Outlook",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Open email in Outlook for review (default):
    python send_qa_bugs_notification.py

  Filter to a specific release version:
    python send_qa_bugs_notification.py --version 10.13.0.0

  Send immediately without review:
    python send_qa_bugs_notification.py --send

  Dry run – print bugs to console only:
    python send_qa_bugs_notification.py --dry-run

  Custom recipient list:
    python send_qa_bugs_notification.py --to qa1@radware.com qa2@radware.com
        """,
    )
    parser.add_argument("--version", default=None,
                        help="Filter by fix version (e.g. 10.13.0.0). Omit for all versions.")
    parser.add_argument("--send", action="store_true",
                        help="Send immediately via Outlook (default: open for review)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print bug list to console only – do not open Outlook")
    parser.add_argument("--to", nargs="+", metavar="EMAIL",
                        help="Override recipient list (space-separated emails)")
    parser.add_argument("--include-runners", action="store_true",
                        help="Include bugs assigned to the DP Runners team")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  QA Bugs Email Notification")
    print("=" * 60)

    # Connect to Jira
    print("🔗 Connecting to Jira...")
    try:
        jira = connect_jira()
    except Exception as exc:
        print(f"❌ Cannot connect to Jira: {exc}")
        return

    # Fetch bugs
    version_label = args.version if args.version else "All Versions"
    print(f"🔍 Fetching bugs on QA ({version_label})...")
    bugs = fetch_qa_bugs(jira, version=args.version, skip_runners=not args.include_runners)

    if not bugs:
        print("ℹ️  No bugs found in QA status with the current filters.")
        print(f"   Checked statuses: {', '.join(QA_STATUSES)}")
        return

    # Display summary
    priority_counts = defaultdict(int)
    for b in bugs:
        priority_counts[b["priority"]] += 1

    print(f"\n📋 Found {len(bugs)} bug(s) on QA:")
    for p in PRIORITY_ORDER:
        if priority_counts[p]:
            emoji = PRIORITY_EMOJI.get(p, "⚪")
            print(f"   {emoji} {p}: {priority_counts[p]}")

    # Dry run: just print the list
    if args.dry_run:
        print("\n" + "-" * 60)
        for b in sorted(bugs, key=priority_sort_key):
            emoji = PRIORITY_EMOJI.get(b["priority"], "⚪")
            print(f"  {b['key']:12s} [{emoji}{b['priority']:8s}] [{b['fix_version']}] {b['summary']}")
        print("-" * 60)
        print("ℹ️  Dry run – no email sent.")
        return

    # Build email
    if args.to:
        recipients = [r.strip() for r in args.to if r.strip()]
    else:
        # Send only to assignees of the fetched bugs (skip unassigned)
        recipients = sorted(set(
            b["assignee_email"] for b in bugs if b["assignee_email"]
        ))

    subject = f"Action Required: Bugs on QA – DefensePro {version_label} ({len(bugs)} bugs)"
    html_body = build_html_email(bugs, version_label)

    print(f"\n📧 Preparing email:")
    print(f"   To:      {', '.join(recipients)}")
    print(f"   Subject: {subject}")

    open_in_outlook(recipients, subject, html_body, send=args.send)


if __name__ == "__main__":
    main()
