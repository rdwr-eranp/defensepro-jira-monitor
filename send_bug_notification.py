"""
Bug Notification Email Sender

This script sends email notifications to QA team members about bugs awaiting verification.
It can be used standalone or integrated with Jira data retrieval scripts.

Configuration:
    Option 1: Set environment variables in .env file
    Option 2: Use --login flag to enter credentials at runtime (more secure)
    
    Environment variables:
    - SMTP_SERVER: SMTP server address (e.g., smtp.office365.com)
    - SMTP_PORT: SMTP port (default: 587 for TLS)
    - SMTP_USERNAME: Email account username
    - SMTP_PASSWORD: Email account password or app-specific password
    - SENDER_EMAIL: Sender email address
"""

import os
import smtplib
import getpass
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class Bug:
    """Represents a Jira bug."""
    key: str
    summary: str
    priority: str
    assignee_name: str
    assignee_email: str
    resolution: str = "Fixed"


@dataclass
class EmailConfig:
    """Email configuration from environment variables."""
    smtp_server: str
    smtp_port: int
    username: str
    password: str
    sender_email: str
    
    @classmethod
    def from_env(cls) -> 'EmailConfig':
        """Load configuration from environment variables."""
        return cls(
            smtp_server=os.getenv('SMTP_SERVER', 'smtp.office365.com'),
            smtp_port=int(os.getenv('SMTP_PORT', '587')),
            username=os.getenv('SMTP_USERNAME', ''),
            password=os.getenv('SMTP_PASSWORD', ''),
            sender_email=os.getenv('SENDER_EMAIL', '')
        )
    
    @classmethod
    def from_prompt(cls, default_email: str = '') -> 'EmailConfig':
        """Prompt user for credentials at runtime (more secure - nothing saved)."""
        print("\n" + "="*60)
        print("🔐 Enter Email Credentials (not saved)")
        print("="*60)
        
        # SMTP Server
        smtp_server = input(f"SMTP Server [smtp.office365.com]: ").strip()
        if not smtp_server:
            smtp_server = 'smtp.office365.com'
        
        # SMTP Port
        smtp_port_str = input(f"SMTP Port [587]: ").strip()
        smtp_port = int(smtp_port_str) if smtp_port_str else 587
        
        # Email/Username
        default_prompt = f" [{default_email}]" if default_email else ""
        username = input(f"Email{default_prompt}: ").strip()
        if not username and default_email:
            username = default_email
        
        # Password (hidden input)
        password = getpass.getpass("Password (hidden): ")
        
        print("="*60 + "\n")
        
        return cls(
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            username=username,
            password=password,
            sender_email=username
        )


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


def create_individual_email_body(assignee_name: str, bugs: List[Bug], version: str) -> str:
    """Create HTML email body for individual assignee."""
    bug_rows = ""
    for bug in bugs:
        emoji = get_priority_emoji(bug.priority)
        bug_rows += f"""
        <tr>
            <td><a href="https://rwrnd.atlassian.net/browse/{bug.key}">{bug.key}</a></td>
            <td>{emoji} {bug.priority}</td>
            <td>{bug.summary}</td>
        </tr>
        """
    
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #4472C4; color: white; }}
            tr:nth-child(even) {{ background-color: #f2f2f2; }}
            a {{ color: #0066cc; }}
        </style>
    </head>
    <body>
        <p>Hi {assignee_name},</p>
        
        <p>This is a reminder that the following bugs for <strong>DefensePro {version}</strong> 
        have been marked as <strong>Completed</strong> by Development and are now waiting for 
        <strong>QA verification</strong>.</p>
        
        <table>
            <tr>
                <th>Bug ID</th>
                <th>Priority</th>
                <th>Summary</th>
            </tr>
            {bug_rows}
        </table>
        
        <p>Please verify the fixes and update the bug status to <strong>Accepted</strong> once validated.</p>
        
        <p>Thank you,<br>QA Automation</p>
    </body>
    </html>
    """
    return html


def create_summary_email_body(bugs_by_assignee: Dict[str, List[Bug]], version: str) -> str:
    """Create HTML email body for summary email to all assignees."""
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
        <table>
            <tr>
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
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 10px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #4472C4; color: white; }}
            tr:nth-child(even) {{ background-color: #f2f2f2; }}
            a {{ color: #0066cc; }}
            h2 {{ color: #4472C4; }}
            h3 {{ color: #333; border-bottom: 1px solid #ddd; padding-bottom: 5px; }}
        </style>
    </head>
    <body>
        <h2>Bug Verification Required - DefensePro {version}</h2>
        
        <p>The following bugs have been marked as <strong>Completed</strong> by Development 
        and are waiting for <strong>QA verification</strong>.</p>
        
        <h3>Summary</h3>
        <table style="width: 200px;">
            <tr><th>Priority</th><th>Count</th></tr>
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


def send_email(
    config: EmailConfig,
    to_addresses: List[str],
    subject: str,
    html_body: str,
    cc_addresses: Optional[List[str]] = None
) -> bool:
    """Send an email using SMTP."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = config.sender_email
        msg['To'] = ', '.join(to_addresses)
        if cc_addresses:
            msg['Cc'] = ', '.join(cc_addresses)
        
        # Attach HTML body
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        
        # Connect and send
        with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
            server.starttls()
            server.login(config.username, config.password)
            
            all_recipients = to_addresses + (cc_addresses or [])
            server.sendmail(config.sender_email, all_recipients, msg.as_string())
        
        print(f"✅ Email sent successfully to: {', '.join(to_addresses)}")
        return True
        
    except smtplib.SMTPAuthenticationError:
        print("❌ Authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD.")
        return False
    except smtplib.SMTPException as e:
        print(f"❌ SMTP error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False


def send_bug_notifications(
    bugs: List[Bug],
    version: str,
    send_individual: bool = False,
    send_summary: bool = True,
    dry_run: bool = True,
    config: Optional[EmailConfig] = None
):
    """
    Send bug notification emails.
    
    Args:
        bugs: List of Bug objects
        version: Release version (e.g., "10.13.0.0")
        send_individual: Send individual emails to each assignee
        send_summary: Send summary email to all assignees
        dry_run: If True, only print what would be sent without actually sending
        config: Email configuration (optional, will load from env if not provided)
    """
    if config is None:
        config = EmailConfig.from_env()
    
    if not dry_run and (not config.username or not config.password):
        print("⚠️  SMTP credentials not configured!")
        return
    
    bugs_by_assignee = group_bugs_by_assignee(bugs)
    all_emails = list(bugs_by_assignee.keys())
    
    subject = f"Action Required: Bug Verification for DefensePro {version} - Bugs on QA"
    
    if send_summary:
        html_body = create_summary_email_body(bugs_by_assignee, version)
        
        if dry_run:
            print("\n" + "="*60)
            print("📧 DRY RUN - Summary Email")
            print("="*60)
            print(f"To: {', '.join(all_emails)}")
            print(f"Subject: {subject}")
            print("-"*60)
            # Print plain text version for preview
            print(f"Total bugs: {len(bugs)}")
            for email, assignee_bugs in bugs_by_assignee.items():
                print(f"\n{assignee_bugs[0].assignee_name} ({email}):")
                for bug in assignee_bugs:
                    print(f"  - {bug.key}: {bug.summary}")
        else:
            send_email(config, all_emails, subject, html_body)
    
    if send_individual:
        for email, assignee_bugs in bugs_by_assignee.items():
            assignee_name = assignee_bugs[0].assignee_name
            html_body = create_individual_email_body(assignee_name, assignee_bugs, version)
            
            if dry_run:
                print("\n" + "="*60)
                print(f"📧 DRY RUN - Individual Email to {assignee_name}")
                print("="*60)
                print(f"To: {email}")
                print(f"Subject: {subject}")
                print("-"*60)
                for bug in assignee_bugs:
                    print(f"  - {bug.key}: {bug.summary}")
            else:
                send_email(config, [email], subject, html_body)


# Sample data for DefensePro 10.13.0.0 bugs on QA
SAMPLE_BUGS = [
    Bug(
        key="DP-110635",
        summary="10.12.0.0 | DOCUMENTATION | CLI Reference Guide | Discrepancy in the Values",
        priority="Low",
        assignee_name="Abhishek P Koparde",
        assignee_email="abhishekk@radware.com"
    ),
    Bug(
        key="DP-110640",
        summary="DP 10.12.0.0 | ATP | Syn Protection | CDB Packet-Report Flag Invalid Value After Upgrade",
        priority="Medium",
        assignee_name="Ahmad Saide",
        assignee_email="ahmadsa@radware.com"
    ),
    Bug(
        key="DP-110181",
        summary="DP 10.12.0.0 | Legacy | WebDDoS | Randomized Attack Failed to Remove Policy From Persistent Policy Storage",
        priority="High",
        assignee_name="Alaa Grable",
        assignee_email="alaag@radware.com"
    ),
    Bug(
        key="DP-111011",
        summary="DP 10.13.0.0 | Preventive Filters | DP Crashed After Reboot While Engines Starting On Self-Detection Mode",
        priority="Blocker",
        assignee_name="Mohamed Abo Saleh",
        assignee_email="mohameda@radware.com"
    ),
    Bug(
        key="DP-110643",
        summary="DP 10.13.0.0 | Crash when DNS Allow list attached to non-exist policy",
        priority="Medium",
        assignee_name="Nidal Hasan Said",
        assignee_email="nidals@radware.com"
    ),
    Bug(
        key="DP-110572",
        summary="DP 10.12.0.0 | MRQP | After reboot can't connect to device with network in different domain",
        priority="Medium",
        assignee_name="Nidal Hasan Said",
        assignee_email="nidals@radware.com"
    ),
    Bug(
        key="DP-111001",
        summary="DP 10.13.0.0 | TLS Visibility | System logfile filled with WEBDDOS Fingerprint 'table full' messages",
        priority="Medium",
        assignee_name="Tony Augustine",
        assignee_email="tonya@radware.com"
    ),
    Bug(
        key="DP-110997",
        summary="DP 10.13.0.0 | TLS Visibility | CLI command web-ddos-protection analytics-collection should be hidden",
        priority="Low",
        assignee_name="Tony Augustine",
        assignee_email="tonya@radware.com"
    ),
]


def send_test_email(to_email: str, version: str = "10.13.0.0", use_login: bool = False):
    """Send a test email to verify SMTP configuration."""
    if use_login:
        config = EmailConfig.from_prompt(default_email=to_email)
    else:
        config = EmailConfig.from_env()
        
        if not config.username or not config.password:
            print("❌ SMTP credentials not configured!")
            print("   Option 1: Add credentials to .env file")
            print("   Option 2: Use --login flag to enter credentials at runtime")
            print(f"\n   Example: python send_bug_notification.py --test {to_email} --login")
            return False
    
    subject = f"[TEST] Bug Notification System - DefensePro {version}"
    
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            .success {{ color: green; font-size: 24px; }}
            table {{ border-collapse: collapse; margin: 20px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; }}
            th {{ background-color: #4472C4; color: white; }}
        </style>
    </head>
    <body>
        <h2>🎉 Test Email Successful!</h2>
        <p class="success">✅ Your email configuration is working correctly.</p>
        
        <h3>Configuration Details:</h3>
        <table>
            <tr><th>Setting</th><th>Value</th></tr>
            <tr><td>SMTP Server</td><td>{config.smtp_server}</td></tr>
            <tr><td>SMTP Port</td><td>{config.smtp_port}</td></tr>
            <tr><td>Sender</td><td>{config.sender_email}</td></tr>
        </table>
        
        <h3>Sample Bug Notification Preview:</h3>
        <p>When you run the script with <code>--send</code>, emails will look like this:</p>
        
        <table>
            <tr><th>Bug ID</th><th>Priority</th><th>Summary</th></tr>
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
        
        <p>You can now use:</p>
        <ul>
            <li><code>python send_bug_notification.py --send</code> - Send to all assignees</li>
            <li><code>python send_bug_notification.py --individual --send</code> - Send individual emails</li>
        </ul>
        
        <p>Best regards,<br>QA Automation System</p>
    </body>
    </html>
    """
    
    print(f"\n📧 Sending test email to {to_email}...")
    return send_email(config, [to_email], subject, html_body)


def get_config(use_login: bool, default_email: str = '') -> EmailConfig:
    """Get email configuration either from prompt or environment."""
    if use_login:
        return EmailConfig.from_prompt(default_email=default_email)
    return EmailConfig.from_env()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Send bug notification emails to QA team",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Dry run (preview):
    python send_bug_notification.py
    
  Send test email with login prompt:
    python send_bug_notification.py --test eranp@radware.com --login
    
  Send to all assignees with login prompt:
    python send_bug_notification.py --send --login
    
  Send using .env credentials:
    python send_bug_notification.py --send
        """
    )
    parser.add_argument("--version", default="10.13.0.0", help="Release version")
    parser.add_argument("--individual", action="store_true", help="Send individual emails to each assignee")
    parser.add_argument("--summary", action="store_true", default=True, help="Send summary email to all")
    parser.add_argument("--send", action="store_true", help="Actually send emails (default is dry run)")
    parser.add_argument("--test", type=str, metavar="EMAIL", help="Send test email to verify configuration")
    parser.add_argument("--login", action="store_true", help="Prompt for credentials at runtime (more secure)")
    
    args = parser.parse_args()
    
    if args.test:
        send_test_email(args.test, args.version, use_login=args.login)
    else:
        print(f"\n{'='*60}")
        print(f"Bug Notification Email Sender - DefensePro {args.version}")
        print(f"{'='*60}")
        print(f"Mode: {'LIVE SEND' if args.send else 'DRY RUN (use --send to actually send)'}")
        print(f"Bugs to notify: {len(SAMPLE_BUGS)}")
        
        # Get config if actually sending
        config = None
        if args.send:
            config = get_config(args.login)
            if not config.username or not config.password:
                print("\n❌ Cannot send: No credentials provided!")
                print("   Use --login flag or configure .env file")
                exit(1)
        
        send_bug_notifications(
            bugs=SAMPLE_BUGS,
            version=args.version,
            send_individual=args.individual,
            send_summary=args.summary,
            dry_run=not args.send,
            config=config
        )

