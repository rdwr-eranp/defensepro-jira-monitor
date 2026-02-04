"""
Send Bug Notification Emails via Outlook

This script uses the local Outlook installation to send emails.
No SMTP credentials needed - uses your already-authenticated Outlook.
"""

import win32com.client
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class Bug:
    """Represents a Jira bug."""
    key: str
    summary: str
    priority: str
    assignee_name: str
    assignee_email: str


def get_priority_emoji(priority: str) -> str:
    """Return emoji for bug priority."""
    priority_emojis = {
        'Blocker': '🔴',
        'Critical': '🔴',
        'High': '🟠',
        'Medium': '🟡',
        'Low': '🟢'
    }
    return priority_emojis.get(priority, '⚪')


def group_bugs_by_assignee(bugs: List[Bug]) -> Dict[str, List[Bug]]:
    """Group bugs by assignee email."""
    grouped = {}
    for bug in bugs:
        email = bug.assignee_email
        if email not in grouped:
            grouped[email] = []
        grouped[email].append(bug)
    return grouped


def create_html_body(bugs_by_assignee: Dict[str, List[Bug]], version: str) -> str:
    """Create HTML email body."""
    sections = ""
    total_bugs = 0
    priority_counts = {'Blocker': 0, 'Critical': 0, 'High': 0, 'Medium': 0, 'Low': 0}
    
    for email, bugs in bugs_by_assignee.items():
        if not bugs:
            continue
        assignee_name = bugs[0].assignee_name
        total_bugs += len(bugs)
        
        bug_rows = ""
        for bug in bugs:
            emoji = get_priority_emoji(bug.priority)
            priority_counts[bug.priority] = priority_counts.get(bug.priority, 0) + 1
            bug_rows += f"""
            <tr>
                <td><a href="https://rwrnd.atlassian.net/browse/{bug.key}">{bug.key}</a></td>
                <td>{emoji} {bug.priority}</td>
                <td>{bug.summary}</td>
            </tr>
            """
        
        sections += f"""
        <h3>{assignee_name} ({email})</h3>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
            <tr style="background-color: #4472C4; color: white;">
                <th>Bug ID</th>
                <th>Priority</th>
                <th>Summary</th>
            </tr>
            {bug_rows}
        </table>
        <br>
        """
    
    # Summary table
    summary_rows = ""
    for priority, count in priority_counts.items():
        if count > 0:
            emoji = get_priority_emoji(priority)
            summary_rows += f"<tr><td>{emoji} {priority}</td><td>{count}</td></tr>"
    
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif;">
        <h2 style="color: #4472C4;">Bug Verification Required - DefensePro {version}</h2>
        
        <p>The following bugs have been marked as <strong>Completed</strong> by Development 
        and are waiting for <strong>QA verification</strong>.</p>
        
        <h3>Summary</h3>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 200px;">
            <tr style="background-color: #4472C4; color: white;"><th>Priority</th><th>Count</th></tr>
            {summary_rows}
            <tr style="font-weight: bold;"><td>Total</td><td>{total_bugs}</td></tr>
        </table>
        
        {sections}
        
        <p>Please verify the fixes and update the bug status to <strong>Accepted</strong> once validated.</p>
        
        <p>Thank you,<br>QA Automation</p>
    </body>
    </html>
    """
    return html


def send_via_outlook(
    to_emails: List[str],
    subject: str,
    html_body: str,
    display_only: bool = True
) -> bool:
    """
    Send email via Outlook COM automation.
    
    Args:
        to_emails: List of recipient email addresses
        subject: Email subject
        html_body: HTML content of the email
        display_only: If True, opens email for review before sending
    """
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = olMailItem
        
        mail.To = "; ".join(to_emails)
        mail.Subject = subject
        mail.HTMLBody = html_body
        
        if display_only:
            mail.Display()  # Opens email for review
            print(f"✅ Email opened in Outlook for review")
            print(f"   Recipients: {', '.join(to_emails)}")
            print(f"   Subject: {subject}")
            return True
        else:
            mail.Send()
            print(f"✅ Email sent via Outlook to: {', '.join(to_emails)}")
            return True
            
    except Exception as e:
        print(f"❌ Error: {e}")
        print("   Make sure Outlook is running on this PC")
        return False


def send_test_email(to_email: str, display_only: bool = True):
    """Send a test email via Outlook."""
    subject = "[TEST] Bug Notification System - DefensePro"
    
    html_body = """
    <html>
    <body style="font-family: Arial, sans-serif;">
        <h2>🎉 Test Email from Outlook Automation</h2>
        <p style="color: green; font-size: 18px;">✅ Your Outlook integration is working!</p>
        
        <p>This email was sent using your local Outlook installation.</p>
        
        <h3>Sample Bug Table:</h3>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
            <tr style="background-color: #4472C4; color: white;">
                <th>Bug ID</th>
                <th>Priority</th>
                <th>Summary</th>
            </tr>
            <tr>
                <td><a href="https://rwrnd.atlassian.net/browse/DP-111011">DP-111011</a></td>
                <td>🔴 Blocker</td>
                <td>DP 10.13.0.0 | Preventive Filters | DP Crashed After Reboot</td>
            </tr>
            <tr>
                <td><a href="https://rwrnd.atlassian.net/browse/DP-111001">DP-111001</a></td>
                <td>🟡 Medium</td>
                <td>DP 10.13.0.0 | TLS Visibility | System logfile filled with errors</td>
            </tr>
        </table>
        
        <p>Best regards,<br>QA Automation System</p>
    </body>
    </html>
    """
    
    return send_via_outlook([to_email], subject, html_body, display_only)


# Sample bugs for DefensePro 10.13.0.0
SAMPLE_BUGS = [
    Bug("DP-110635", "10.12.0.0 | DOCUMENTATION | CLI Reference Guide | Discrepancy in the Values", 
        "Low", "Abhishek P Koparde", "abhishekk@radware.com"),
    Bug("DP-110640", "DP 10.12.0.0 | ATP | Syn Protection | CDB Packet-Report Flag Invalid Value After Upgrade",
        "Medium", "Ahmad Saide", "ahmadsa@radware.com"),
    Bug("DP-110181", "DP 10.12.0.0 | Legacy | WebDDoS | Randomized Attack Failed to Remove Policy",
        "High", "Alaa Grable", "alaag@radware.com"),
    Bug("DP-111011", "DP 10.13.0.0 | Preventive Filters | DP Crashed After Reboot",
        "Blocker", "Mohamed Abo Saleh", "mohameda@radware.com"),
    Bug("DP-110643", "DP 10.13.0.0 | Crash when DNS Allow list attached to non-exist policy",
        "Medium", "Nidal Hasan Said", "nidals@radware.com"),
    Bug("DP-110572", "DP 10.12.0.0 | MRQP | After reboot can't connect to device",
        "Medium", "Nidal Hasan Said", "nidals@radware.com"),
    Bug("DP-111001", "DP 10.13.0.0 | TLS Visibility | System logfile filled with WEBDDOS errors",
        "Medium", "Tony Augustine", "tonya@radware.com"),
    Bug("DP-110997", "DP 10.13.0.0 | TLS Visibility | CLI command should be hidden",
        "Low", "Tony Augustine", "tonya@radware.com"),
]


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Send bug notification emails via Outlook",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Open test email in Outlook for review:
    python send_via_outlook.py --test eranp@radware.com
    
  Send test email directly:
    python send_via_outlook.py --test eranp@radware.com --send
    
  Open bug notification email for review:
    python send_via_outlook.py
    
  Send bug notification email directly:
    python send_via_outlook.py --send
        """
    )
    parser.add_argument("--version", default="10.13.0.0", help="Release version")
    parser.add_argument("--test", type=str, metavar="EMAIL", help="Send test email to specified address")
    parser.add_argument("--send", action="store_true", help="Send immediately (default: open for review)")
    
    args = parser.parse_args()
    
    display_only = not args.send
    
    if args.test:
        print(f"\n{'='*60}")
        print(f"Sending TEST email via Outlook")
        print(f"{'='*60}")
        send_test_email(args.test, display_only)
    else:
        print(f"\n{'='*60}")
        print(f"Bug Notification via Outlook - DefensePro {args.version}")
        print(f"{'='*60}")
        print(f"Mode: {'SEND IMMEDIATELY' if args.send else 'OPEN FOR REVIEW'}")
        print(f"Bugs: {len(SAMPLE_BUGS)}")
        
        bugs_by_assignee = group_bugs_by_assignee(SAMPLE_BUGS)
        all_emails = list(bugs_by_assignee.keys())
        
        subject = f"Action Required: Bug Verification for DefensePro {args.version} - Bugs on QA"
        html_body = create_html_body(bugs_by_assignee, args.version)
        
        send_via_outlook(all_emails, subject, html_body, display_only)
