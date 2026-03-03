"""
Sub Test Execution Coverage Reminder

Fetches sub test executions for a DefensePro release, queries Xray for
execution coverage, and sends an Outlook email to assignees whose
sub test executions are below a coverage threshold (default 50%).

Usage:
    python send_coverage_reminder.py                          # Default: version from $VERSION, threshold 50%
    python send_coverage_reminder.py --version 10.13.0.0
    python send_coverage_reminder.py --threshold 60           # Custom threshold
    python send_coverage_reminder.py --dry-run                # Print only, no Outlook
    python send_coverage_reminder.py --send                   # Send immediately
"""

import os
import sys
import argparse
import time
import urllib3
import requests
from collections import Counter, defaultdict
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

XRAY_AUTH_URL = 'https://xray.cloud.getxray.app/api/v2/authenticate'
XRAY_GRAPHQL_URL = 'https://xray.cloud.getxray.app/api/v2/graphql'
XRAY_CLIENT_ID = os.getenv('XRAY_CLIENT_ID', '7DC37640C3B6422D91E978570801CCF8')
XRAY_CLIENT_SECRET = os.getenv('XRAY_CLIENT_SECRET', '757b92c3039c706606ee29fe74e7c9d28c0a9c80bc013f6999f5910f20d347d8')

ALWAYS_INCLUDE = [e.strip() for e in os.getenv("QA_BUGS_ALWAYS_INCLUDE", "eranp@radware.com").split(",") if e.strip()]


# ---------------------------------------------------------------------------
# Xray helpers
# ---------------------------------------------------------------------------

def get_xray_token():
    try:
        resp = requests.post(
            XRAY_AUTH_URL,
            json={'client_id': XRAY_CLIENT_ID, 'client_secret': XRAY_CLIENT_SECRET},
            headers={'Content-Type': 'application/json'},
            verify=False, timeout=30,
        )
        if resp.status_code == 200:
            return resp.text.strip('"')
    except Exception:
        pass
    return None


def get_xray_ids(jira_keys, max_pages=20):
    """Map Jira keys → Xray issueIds."""
    key_to_id = {}
    target = set(jira_keys)
    start, limit, pages = 0, 100, 0
    query = """
    query($limit: Int!, $start: Int!) {
        getTestExecutions(limit: $limit, start: $start) {
            total
            results { issueId  jira(fields: ["key"]) }
        }
    }
    """
    while pages < max_pages:
        token = get_xray_token()
        if not token:
            break
        try:
            resp = requests.post(
                XRAY_GRAPHQL_URL,
                json={'query': query, 'variables': {'limit': limit, 'start': start}},
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                verify=False, timeout=60,
            )
            if resp.status_code != 200:
                break
            data = resp.json().get('data', {}).get('getTestExecutions', {})
            results = data.get('results', [])
            if not results:
                break
            for r in results:
                k = r.get('jira', {}).get('key')
                if k in target:
                    key_to_id[k] = r.get('issueId')
            if len(key_to_id) == len(target) or start + limit >= data.get('total', 0):
                break
            start += limit
            pages += 1
        except Exception:
            break
        time.sleep(0.5)
    return key_to_id


def get_execution_coverage(jira_keys, key_to_xray_id):
    """Query Xray for each sub test execution and return {key: {tests, executed, rate}}."""
    query = """
    query($issueId: String!) {
        getTestExecution(issueId: $issueId) {
            testRuns(limit: 100) {
                total
                results { status { name } }
            }
        }
    }
    """
    results = {}
    for idx, jira_key in enumerate(jira_keys, 1):
        xray_id = key_to_xray_id.get(jira_key)
        entry = {'tests': 0, 'executed': 0, 'rate': 0.0}
        if not xray_id:
            results[jira_key] = entry
            continue
        print(f"   [{idx}/{len(jira_keys)}] {jira_key}...", end='', flush=True)
        for attempt in range(2):
            try:
                token = get_xray_token()
                if not token:
                    break
                resp = requests.post(
                    XRAY_GRAPHQL_URL,
                    json={'query': query, 'variables': {'issueId': xray_id}},
                    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                    verify=False, timeout=15,
                )
                if resp.status_code != 200:
                    continue
                te = resp.json().get('data', {}).get('getTestExecution')
                if not te:
                    break
                runs = te.get('testRuns', {})
                total = runs.get('total', 0)
                executed = sum(
                    1 for r in runs.get('results', [])
                    if r.get('status', {}).get('name', '').upper() not in ('TO DO', 'TODO')
                )
                rate = (executed / total * 100) if total > 0 else 0.0
                entry = {'tests': total, 'executed': executed, 'rate': rate}
                print(f" {total} tests, {executed} executed ({rate:.0f}%)")
                break
            except requests.exceptions.Timeout:
                print(" timeout", end='')
                time.sleep(1)
            except Exception as e:
                print(f" error", end='')
                time.sleep(1)
        else:
            print()
        results[jira_key] = entry
        time.sleep(0.3)
    return results


# ---------------------------------------------------------------------------
# HTML email builder
# ---------------------------------------------------------------------------

def build_html_email(low_coverage_items, version, threshold):
    """
    Build HTML email.  low_coverage_items is a list of dicts:
      {key, summary, assignee_name, assignee_email, tests, executed, rate}
    sorted by rate ascending (worst first).
    """
    now = datetime.now().strftime("%d %b %Y, %H:%M")
    total = len(low_coverage_items)

    # Group by assignee
    by_assignee = defaultdict(list)
    for item in low_coverage_items:
        by_assignee[item['assignee_name']].append(item)

    assignee_sections = ""
    for assignee, items in sorted(by_assignee.items()):
        rows = ""
        for it in sorted(items, key=lambda x: x['rate']):
            if it['rate'] == 0:
                color = '#dc3545'   # red
            elif it['rate'] < 25:
                color = '#e65100'   # dark orange
            else:
                color = '#ff9800'   # orange
            bar_width = max(int(it['rate']), 2)
            rows += f"""
                <tr>
                    <td><a href="{JIRA_URL}/browse/{it['key']}" style="color:#0066cc;">{it['key']}</a></td>
                    <td style="max-width:350px;">{it['summary']}</td>
                    <td style="text-align:center;">{it['tests']}</td>
                    <td style="text-align:center;">{it['executed']}</td>
                    <td style="text-align:center; font-weight:bold; color:{color};">{it['rate']:.0f}%
                        <div style="background:#eee; border-radius:3px; height:6px; margin-top:3px;">
                            <div style="background:{color}; width:{bar_width}%; height:6px; border-radius:3px;"></div>
                        </div>
                    </td>
                </tr>"""

        assignee_sections += f"""
        <h3 style="color:#2c3e50; border-bottom:2px solid #e74c3c; padding-bottom:6px; margin-top:28px;">
            {assignee}
            <span style="font-size:13px; color:#777; font-weight:normal;">
                ({len(items)} execution{'s' if len(items) != 1 else ''} below {threshold}%)
            </span>
        </h3>
        <table border="1" cellpadding="8" cellspacing="0"
               style="border-collapse:collapse; width:100%; font-size:13px;">
            <tr style="background-color:#e74c3c; color:white;">
                <th style="width:100px;">Key</th>
                <th>Summary</th>
                <th style="width:70px;">Tests</th>
                <th style="width:80px;">Executed</th>
                <th style="width:100px;">Coverage</th>
            </tr>
            {rows}
        </table>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body      {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; margin: 20px; }}
  h2        {{ color: #e74c3c; }}
  table     {{ border-collapse: collapse; margin-bottom: 10px; }}
  th, td    {{ border: 1px solid #ccc; padding: 7px 10px; text-align: left; vertical-align: top; }}
  tr:nth-child(even) {{ background-color: #f9f9f9; }}
</style>
</head>
<body>

<h2>⚠️ Test Coverage Reminder – DefensePro {version}</h2>

<p>
  Hi Team,<br><br>
  The following <strong>{total} sub test execution{'s' if total != 1 else ''}</strong>
  currently have <strong>less than {threshold}% test coverage</strong> in Xray
  as of <em>{now}</em>.<br><br>
  Please update your test results in Xray at your earliest convenience.
</p>

<table border="1" cellpadding="7" cellspacing="0"
       style="border-collapse:collapse; width:300px; margin-bottom:24px; font-size:13px;">
  <tr style="background-color:#e74c3c; color:white;">
    <th>Metric</th><th>Value</th>
  </tr>
  <tr><td>Sub Test Executions below {threshold}%</td><td><strong>{total}</strong></td></tr>
  <tr><td>Assignees affected</td><td><strong>{len(by_assignee)}</strong></td></tr>
</table>

{assignee_sections}

<br>
<p style="color:#555; font-size:13px;">
  This email was generated automatically from Jira + Xray data.<br>
  Click any Key to open the issue directly in Jira.
</p>

</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Outlook dispatch
# ---------------------------------------------------------------------------

def open_in_outlook(to_recipients, subject, html_body, send=False):
    if not OUTLOOK_AVAILABLE:
        print("❌ win32com not available – cannot open Outlook.")
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
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Remind QA members about sub test executions with low coverage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python send_coverage_reminder.py --version 10.13.0.0
    python send_coverage_reminder.py --version 10.13.0.0 --threshold 60
    python send_coverage_reminder.py --dry-run
    python send_coverage_reminder.py --send
    python send_coverage_reminder.py --to user@radware.com
        """,
    )
    parser.add_argument("--version", default=os.getenv("VERSION"),
                        help="Fix version (default: $VERSION env var)")
    parser.add_argument("--threshold", type=float, default=50,
                        help="Coverage threshold %% (default: 50)")
    parser.add_argument("--send", action="store_true",
                        help="Send immediately via Outlook (default: open for review)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print to console only – no Outlook")
    parser.add_argument("--to", nargs="+", metavar="EMAIL",
                        help="Override recipient list")
    parser.add_argument("--include-runners", action="store_true",
                        help="Include DP Runners team sub executions")
    args = parser.parse_args()

    version = args.version
    if not version:
        version = input("Enter version (e.g. 10.13.0.0): ").strip()
    threshold = args.threshold

    print(f"\n{'='*60}")
    print(f"  Sub Test Execution Coverage Reminder")
    print(f"  Version: {version}  |  Threshold: <{threshold:.0f}%")
    print(f"{'='*60}\n")

    # Connect to Jira
    print("🔗 Connecting to Jira...")
    options = {"server": JIRA_URL, "verify": False}
    try:
        jira = JIRA(options=options, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
    except Exception as exc:
        print(f"❌ Cannot connect to Jira: {exc}")
        return

    # Fetch sub test executions (excluding Web Assist & Cloud Assist)
    print(f"🔍 Fetching sub test executions for {version}...")
    sub_exec_jql = (
        f'project = DP AND fixVersion = "{version}" '
        f'AND type = "sub test execution" '
        f'AND summary !~ "Web Assist" '
        f'AND summary !~ "Cloud Assist"'
    )
    sub_execs = jira.search_issues(sub_exec_jql, maxResults=False,
                                   fields='summary,status,assignee,customfield_10129')
    print(f"✓ Found {len(sub_execs)} sub test executions\n")

    if not sub_execs:
        print("ℹ️  No sub test executions found.")
        return

    # Optionally skip DP Runners
    if not args.include_runners:
        filtered = []
        for se in sub_execs:
            team = getattr(se.fields, 'customfield_10129', None)
            if team:
                team_name = team.value if hasattr(team, 'value') else str(team)
                if team_name == 'DP Runners':
                    continue
            filtered.append(se)
        if len(filtered) < len(sub_execs):
            print(f"   Skipped {len(sub_execs) - len(filtered)} DP Runners executions")
            sub_execs = filtered

    # Get Xray IDs
    jira_keys = [se.key for se in sub_execs]
    print(f"🔗 Mapping {len(jira_keys)} keys to Xray IDs...")
    key_to_xray_id = get_xray_ids(jira_keys)
    print(f"   Found {len(key_to_xray_id)} Xray mappings\n")

    # Query coverage per execution
    print("📊 Querying Xray execution coverage...")
    coverage = get_execution_coverage(jira_keys, key_to_xray_id)

    # Filter to below threshold
    low_coverage = []
    for se in sub_execs:
        cov = coverage.get(se.key, {})
        rate = cov.get('rate', 0)
        if rate < threshold and cov.get('tests', 0) > 0:
            assignee = se.fields.assignee
            low_coverage.append({
                'key': se.key,
                'summary': se.fields.summary,
                'assignee_name': assignee.displayName if assignee else 'Unassigned',
                'assignee_email': assignee.emailAddress if assignee else '',
                'tests': cov['tests'],
                'executed': cov['executed'],
                'rate': rate,
            })

    # Sort worst first
    low_coverage.sort(key=lambda x: x['rate'])

    print(f"\n📋 {len(low_coverage)} sub test execution(s) below {threshold:.0f}% coverage:")
    if not low_coverage:
        print("ℹ️  All executions meet the threshold – no reminder needed. 🎉")
        return

    for item in low_coverage:
        print(f"   {item['key']:12s} {item['rate']:5.0f}% ({item['executed']}/{item['tests']})  {item['assignee_name']}")

    # Dry run
    if args.dry_run:
        print("\nℹ️  Dry run – no email sent.")
        return

    # Build email
    if args.to:
        recipients = [r.strip() for r in args.to if r.strip()]
    else:
        recipients = sorted(set(
            item['assignee_email'] for item in low_coverage if item['assignee_email']
        ) | set(ALWAYS_INCLUDE))

    subject = f"⚠️ Test Coverage Reminder: {len(low_coverage)} executions below {threshold:.0f}% – DefensePro {version}"
    html_body = build_html_email(low_coverage, version, threshold)

    print(f"\n📧 Preparing email:")
    print(f"   To:      {', '.join(recipients)}")
    print(f"   Subject: {subject}")

    open_in_outlook(recipients, subject, html_body, send=args.send)


if __name__ == "__main__":
    main()
