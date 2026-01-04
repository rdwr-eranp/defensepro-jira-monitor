"""
Weekly High Severity Bug Trend Graph for DefensePro 10.13.0.0
Shows weekly progress for HIGH and CRITICAL priority bugs only: 
  - Open bugs on Dev
  - Open bugs on QA
  - Closed/Accepted bugs

Version Information:
  Version: 10.13.0.0
  Project: DP (DefensePro)
  Report Date: January 1, 2026
  Filter: HIGH and CRITICAL priority only

Metrics:
  - Open on Dev: High/Critical bugs currently on Dev at end of week (Status IN "In Progress", "To-Do", "None")
  - Open on QA: High/Critical bugs currently on QA at end of week (Status = "Completed")
  - Closed: High/Critical bugs that are Accepted/Closed
"""

import os
from dotenv import load_dotenv
from jira import JIRA
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from collections import defaultdict

def connect_to_jira():
    """Connect to Jira using credentials from .env file"""
    load_dotenv()
    
    jira_url = os.getenv('JIRA_URL')
    jira_email = os.getenv('JIRA_EMAIL')
    jira_api_token = os.getenv('JIRA_API_TOKEN')
    
    options = {'server': jira_url, 'verify': False}
    jira = JIRA(options=options, basic_auth=(jira_email, jira_api_token))
    return jira

def get_bug_status_at_date(issue, target_date):
    """
    Determine bug status category at a specific date by examining changelog
    Returns: 'dev', 'qa', 'closed', or 'not_created'
    """
    # Ensure target_date is a date object
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    
    # Check if bug was created before target date
    created_date = datetime.strptime(issue.fields.created[:10], '%Y-%m-%d').date()
    if created_date > target_date:
        return 'not_created'
    
    # Replay changelog to find status at target_date (end of week)
    status_at_date = 'None'  # Default initial status for new bugs
    
    changelog = issue.changelog
    if hasattr(changelog, 'histories'):
        # IMPORTANT: Sort histories chronologically (oldest first)
        sorted_histories = sorted(changelog.histories, key=lambda h: h.created)
        
        for history in sorted_histories:
            change_date = datetime.strptime(history.created[:19], '%Y-%m-%dT%H:%M:%S').date()
            
            # Only include changes that occurred on or before target_date
            if change_date > target_date:
                break
            
            # Apply status changes
            for item in history.items:
                if item.field == 'status':
                    status_at_date = item.toString
    
    # Categorize based on status
    status_lower = status_at_date.lower()
    
    if 'accepted' in status_lower:
        return 'closed'
    elif 'completed' in status_lower:
        return 'qa'
    elif any(s in status_lower for s in ['in progress', 'to do', 'to-do', 'none', 'open']):
        return 'dev'
    else:
        return 'dev'

def fetch_high_severity_bug_trend(jira, version="10.12.0.0"):
    """
    Fetch high severity bug trend data (High and Critical priority only)
    """
    print(f"Fetching HIGH and CRITICAL priority bugs for version {version}...")
    
    # Fetch HIGH and CRITICAL bugs with changelog
    jql = f'project = DP AND type = Bug AND fixVersion = "{version}" AND priority IN (High, Highest, Critical) ORDER BY created ASC'
    
    print(f"  Fetching bugs with changelog...")
    all_issues = jira.search_issues(jql, maxResults=False, expand='changelog')
    
    print(f"✓ Found {len(all_issues)} HIGH/CRITICAL priority bugs for version {version}")
    
    # Determine release start date (earliest bug creation date)
    if all_issues:
        earliest_date = min([datetime.strptime(issue.fields.created[:10], '%Y-%m-%d').date() for issue in all_issues])
    else:
        earliest_date = datetime.now().date() - timedelta(days=90)  # Default to 90 days ago
    
    print(f"  Release tracking from: {earliest_date}")
    
    # Calculate historical bug trend from release start
    print(f"\nCalculating HIGH/CRITICAL bug trend from {earliest_date}...\n")
    historical_dates = []
    historical_total = []
    historical_dev = []
    historical_qa = []
    historical_closed = []
    
    # Generate weekly data points from release start to now
    current_date = earliest_date
    end_date = datetime.now().date()
    
    while current_date <= end_date:
        historical_dates.append(current_date.strftime('%Y-%m-%d'))
        
        # Count bugs at this date
        total_at_date = 0
        dev_at_date = 0
        qa_at_date = 0
        closed_at_date = 0
        
        for issue in all_issues:
            # Check if bug was created by this date
            bug_created = datetime.strptime(issue.fields.created[:10], '%Y-%m-%d').date()
            if bug_created <= current_date:
                total_at_date += 1
                status = get_bug_status_at_date(issue, current_date)
                if status == 'dev':
                    dev_at_date += 1
                elif status == 'qa':
                    qa_at_date += 1
                elif status == 'closed':
                    closed_at_date += 1
        
        historical_total.append(total_at_date)
        historical_dev.append(dev_at_date)
        historical_qa.append(qa_at_date)
        historical_closed.append(closed_at_date)
        
        # Move to next week
        current_date += timedelta(days=7)
    
    print(f"  Generated {len(historical_dates)} data points from {earliest_date} to {end_date}")
    
    # Get current status details for all high severity bugs
    current_dev = []
    current_qa = []
    current_closed = []
    
    for issue in all_issues:
        status = get_bug_status_at_date(issue, end_date)
        if status == 'dev':
            current_dev.append(issue)
        elif status == 'qa':
            current_qa.append(issue)
        elif status == 'closed':
            current_closed.append(issue)
    
    return {
        'historical_dates': historical_dates,
        'historical_total': historical_total,
        'historical_dev': historical_dev,
        'historical_qa': historical_qa,
        'historical_closed': historical_closed,
        'release_start': earliest_date.strftime('%Y-%m-%d'),
        'bugs_on_dev': current_dev,
        'bugs_on_qa': current_qa,
        'bugs_closed': current_closed,
        'total_bugs': len(all_issues)
    }

def generate_high_severity_trend_chart(data, version="10.12.0.0"):
    """Generate weekly high severity bug trend chart from release start"""
    
    fig = go.Figure()
    
    # Add total bugs line
    fig.add_trace(go.Scatter(
        x=data['historical_dates'],
        y=data['historical_total'],
        mode='lines+markers',
        name='Total High/Critical Bugs',
        line=dict(color='#d32f2f', width=4),
        marker=dict(size=8),
        hovertemplate='<b>Total High/Critical</b><br>Week: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    # Add bugs on Dev line
    fig.add_trace(go.Scatter(
        x=data['historical_dates'],
        y=data['historical_dev'],
        mode='lines+markers',
        name='On Dev',
        line=dict(color='#ff6600', width=3),
        marker=dict(size=7),
        hovertemplate='<b>On Dev</b><br>Week: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    # Add bugs on QA line
    fig.add_trace(go.Scatter(
        x=data['historical_dates'],
        y=data['historical_qa'],
        mode='lines+markers',
        name='On QA',
        line=dict(color='#0070c0', width=3),
        marker=dict(size=7),
        hovertemplate='<b>On QA</b><br>Week: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    # Add closed bugs line
    fig.add_trace(go.Scatter(
        x=data['historical_dates'],
        y=data['historical_closed'],
        mode='lines+markers',
        name='Closed/Accepted',
        line=dict(color='#00b050', width=3),
        marker=dict(size=7),
        hovertemplate='<b>Closed/Accepted</b><br>Week: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    fig.update_layout(
        title={
            'text': f'DefensePro {version} - HIGH/CRITICAL Priority Bug Trend from Release Start<br><sub>Tracking HIGH and CRITICAL priority bugs only | {data["release_start"]} to {data["historical_dates"][-1]} ({len(data["historical_dates"])} weeks)</sub>',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 20, 'color': '#d32f2f', 'family': 'Arial'}
        },
        xaxis=dict(
            title='Week',
            showgrid=True,
            gridcolor='#e0e0e0',
            tickangle=-45,
            tickfont=dict(size=10)
        ),
        yaxis=dict(
            title='Bug Count',
            showgrid=True,
            gridcolor='#e0e0e0',
            tickfont=dict(size=11),
            rangemode='tozero'
        ),
        plot_bgcolor='white',
        paper_bgcolor='white',
        height=500,
        margin=dict(l=80, r=80, t=120, b=100),
        showlegend=True,
        legend=dict(
            x=0.02,
            y=0.98,
            bgcolor='rgba(255,255,255,0.9)',
            bordercolor='#e0e0e0',
            borderwidth=1,
            font=dict(size=12)
        ),
        hovermode='x unified'
    )
    
    return fig

def save_data_to_csv(data, version="10.12.0.0"):
    """Save the high severity bug trend data to CSV"""
    df = pd.DataFrame({
        'Week': data['historical_dates'],
        'Total High/Critical': data['historical_total'],
        'On Dev': data['historical_dev'],
        'On QA': data['historical_qa'],
        'Closed': data['historical_closed']
    })
    
    filename = f'weekly_high_severity_bug_trend_{version}.csv'
    df.to_csv(filename, index=False)
    print(f"\n✓ Data saved to {filename}")
    return filename

def main():
    """Main execution function"""
    try:
        print("=" * 70)
        print("Weekly HIGH/CRITICAL Priority Bug Trend")
        print("DefensePro 10.13.0.0")
        print("=" * 70)
        print()
        
        # Connect to Jira
        print("Connecting to Jira...")
        jira = connect_to_jira()
        print("✓ Connected successfully\n")
        
        # Fetch high severity bug trend data
        version = "10.13.0.0"
        data = fetch_high_severity_bug_trend(jira, version=version)
        
        # Save data to CSV
        csv_file = save_data_to_csv(data, version=version)
        
        # Generate chart
        print("\nGenerating high severity bug trend chart...")
        fig = generate_high_severity_trend_chart(data, version=version)
        
        # Build bug tables HTML
        bugs_dev_html = ""
        for bug in data['bugs_on_dev']:
            created_date = datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').strftime('%b %d, %Y')
            priority_class = "priority-high" if bug.fields.priority.name in ["High", "Highest", "Critical"] else "priority-medium"
            bugs_dev_html += f"""
                <tr>
                    <td><a href="https://rwrnd.atlassian.net/browse/{bug.key}" class="bug-key" target="_blank">{bug.key}</a></td>
                    <td><span class="{priority_class}">{bug.fields.priority.name}</span></td>
                    <td>{bug.fields.summary}</td>
                    <td>{created_date}</td>
                </tr>
            """
        
        bugs_qa_html = ""
        for bug in data['bugs_on_qa']:
            created_date = datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').strftime('%b %d, %Y')
            priority_class = "priority-high" if bug.fields.priority.name in ["High", "Highest", "Critical"] else "priority-medium"
            bugs_qa_html += f"""
                <tr>
                    <td><a href="https://rwrnd.atlassian.net/browse/{bug.key}" class="bug-key" target="_blank">{bug.key}</a></td>
                    <td><span class="{priority_class}">{bug.fields.priority.name}</span></td>
                    <td>{bug.fields.summary}</td>
                    <td>{created_date}</td>
                </tr>
            """
        
        # Generate HTML report
        output_file = f'weekly_high_severity_bug_trend_{version}.html'
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HIGH/CRITICAL Priority Bug Trend - DefensePro {version}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background-color: white; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); border-radius: 8px; }}
        h1 {{ color: #d32f2f; border-bottom: 3px solid #d32f2f; padding-bottom: 10px; margin-bottom: 10px; text-align: center; }}
        h2 {{ color: #d32f2f; margin-top: 30px; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }}
        .metadata {{ color: #666; font-size: 14px; margin-bottom: 30px; text-align: center; }}
        .summary-box {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }}
        .metric-card {{ padding: 20px; border-radius: 8px; text-align: center; box-shadow: 0 2px 5px rgba(0,0,0,0.1); color: white; }}
        .metric-card.total {{ background: linear-gradient(135deg, #d32f2f 0%, #f44336 100%); }}
        .metric-card.dev {{ background: linear-gradient(135deg, #ff6600 0%, #ff8833 100%); }}
        .metric-card.qa {{ background: linear-gradient(135deg, #0070c0 0%, #3399dd 100%); }}
        .metric-card.closed {{ background: linear-gradient(135deg, #00b050 0%, #33cc66 100%); }}
        .metric-number {{ font-size: 48px; font-weight: bold; margin: 10px 0; }}
        .metric-label {{ font-size: 16px; font-weight: 500; }}
        .chart-container {{ margin: 30px 0; }}
        .section-title {{ color: #d32f2f; font-size: 20px; font-weight: bold; margin: 30px 0 15px 0; padding-bottom: 5px; border-bottom: 2px solid #e0e0e0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        th {{ background-color: #d32f2f; color: white; padding: 12px; text-align: left; font-weight: 600; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #e0e0e0; }}
        tr:hover {{ background-color: #f9f9f9; }}
        .priority-high {{ color: #d32f2f; font-weight: bold; }}
        .priority-medium {{ color: #f57c00; font-weight: bold; }}
        .bug-key {{ font-family: monospace; font-weight: bold; color: #0070c0; text-decoration: none; }}
        .bug-key:hover {{ text-decoration: underline; }}
        .observation-list {{ background-color: #ffebee; padding: 20px; border-left: 4px solid #d32f2f; margin: 20px 0; }}
        .observation-list ul {{ margin: 10px 0; padding-left: 20px; }}
        .observation-list li {{ margin: 8px 0; line-height: 1.6; }}
        .alert-box {{ background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }}
        .alert-box.critical {{ background-color: #ffebee; border-left-color: #d32f2f; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>HIGH/CRITICAL Priority Bug Trend - DefensePro {version}</h1>
        <div class="metadata">
            <strong>Filter:</strong> HIGH and CRITICAL priority bugs only<br>
            <strong>Tracking Period:</strong> {data['release_start']} to {data['historical_dates'][-1]}<br>
            <strong>Report Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>

        <div class="summary-box">
            <div class="metric-card total">
                <div class="metric-label">Total High/Critical</div>
                <div class="metric-number">{data['total_bugs']}</div>
            </div>
            <div class="metric-card dev">
                <div class="metric-label">Currently on Dev</div>
                <div class="metric-number">{len(data['bugs_on_dev'])}</div>
            </div>
            <div class="metric-card qa">
                <div class="metric-label">Currently on QA</div>
                <div class="metric-number">{len(data['bugs_on_qa'])}</div>
            </div>
            <div class="metric-card closed">
                <div class="metric-label">Closed/Accepted</div>
                <div class="metric-number">{len(data['bugs_closed'])}</div>
            </div>
        </div>

        {'<div class="alert-box critical"><strong>⚠️ Critical Status Alert:</strong> There are currently ' + str(len(data['bugs_on_dev']) + len(data['bugs_on_qa'])) + ' open HIGH/CRITICAL priority bugs requiring immediate attention.</div>' if len(data['bugs_on_dev']) + len(data['bugs_on_qa']) > 0 else '<div class="alert-box" style="background-color: #e8f5e9; border-left-color: #4caf50;"><strong>✓ Status:</strong> No open HIGH/CRITICAL priority bugs.</div>'}

        <div class="section-title">📊 High/Critical Priority Bug Trend</div>
        <div class="chart-container" id="trend-chart"></div>

        <h2>High/Critical Bugs on Dev ({len(data['bugs_on_dev'])} bugs)</h2>
        <p>Status: HIGH/CRITICAL priority bugs in development or not started</p>
        <table>
            <thead><tr><th>Key</th><th>Priority</th><th>Summary</th><th>Created</th></tr></thead>
            <tbody>{bugs_dev_html if bugs_dev_html else '<tr><td colspan="4" style="text-align: center;">No HIGH/CRITICAL bugs on Dev</td></tr>'}</tbody>
        </table>

        <h2>High/Critical Bugs on QA ({len(data['bugs_on_qa'])} bugs)</h2>
        <p>Status: HIGH/CRITICAL priority bugs completed by Dev, awaiting QA verification</p>
        <table>
            <thead><tr><th>Key</th><th>Priority</th><th>Summary</th><th>Created</th></tr></thead>
            <tbody>{bugs_qa_html if bugs_qa_html else '<tr><td colspan="4" style="text-align: center;">No HIGH/CRITICAL bugs on QA</td></tr>'}</tbody>
        </table>

        <h2>Key Observations</h2>
        <div class="observation-list">
            <ul>
                <li><strong>Total HIGH/CRITICAL Bugs:</strong> {data['total_bugs']} bugs tracked since {data['release_start']}</li>
                <li><strong>Current Status:</strong> {len(data['bugs_on_dev'])} on Dev, {len(data['bugs_on_qa'])} on QA, {len(data['bugs_closed'])} Closed</li>
                <li><strong>Closure Rate:</strong> {len(data['bugs_closed']) / max(data['total_bugs'], 1) * 100:.1f}% of HIGH/CRITICAL bugs resolved</li>
                <li><strong>Open HIGH/CRITICAL:</strong> {len(data['bugs_on_dev']) + len(data['bugs_on_qa'])} bugs remaining ({(len(data['bugs_on_dev']) + len(data['bugs_on_qa'])) / max(data['total_bugs'], 1) * 100:.1f}%)</li>
                <li><strong>Trend:</strong> {'⚠️ Requires immediate attention and prioritization' if len(data['bugs_on_dev']) + len(data['bugs_on_qa']) > 0 else '✓ All HIGH/CRITICAL bugs resolved'}</li>
            </ul>
        </div>

        <div class="footer">
            <p>Generated from Jira Project: DP (DefensePro) | Version: {version} | Filter: HIGH and CRITICAL priority only</p>
            <p><strong>Note:</strong> This is a READ-ONLY report. No Jira issues were created or modified during this analysis.</p>
        </div>
    </div>

    {fig.to_html(include_plotlyjs='cdn', div_id='trend-chart', full_html=False)}
</body>
</html>"""
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✓ Report saved to {output_file}")
        
        # Display summary
        print("\n" + "=" * 70)
        print("SUMMARY - HIGH/CRITICAL PRIORITY BUGS")
        print("=" * 70)
        print(f"Total HIGH/CRITICAL Bugs: {data['total_bugs']}")
        print(f"  • Currently on Dev: {len(data['bugs_on_dev'])}")
        print(f"  • Currently on QA: {len(data['bugs_on_qa'])}")
        print(f"  • Closed/Accepted: {len(data['bugs_closed'])}")
        print(f"  • Closure Rate: {len(data['bugs_closed']) / max(data['total_bugs'], 1) * 100:.1f}%")
        print()
        
        print("\n✓ High severity bug trend report generation complete!")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
