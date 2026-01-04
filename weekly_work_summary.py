"""
Weekly Work Summary Graph for DefensePro 10.13.0.0
Shows weekly progress: Open bugs on Dev, Open bugs on QA, and Accepted bugs

Version Information:
  Version: 10.13.0.0
  Project: DP (DefensePro)
  Report Date: January 1, 2026

Metrics:
  - Open on Dev: Bugs currently on Dev at end of week (Status IN "In Progress", "To-Do", "None")
  - Open on QA: Bugs currently on QA at end of week (Status = "Completed")
  - Accepted This Week: Bugs that transitioned to Accepted status during the week
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

def count_accepted_in_week(issue, week_start, week_end):
    """
    Count if bug was accepted during the given week
    Returns: 1 if accepted during week, 0 otherwise
    """
    changelog = issue.changelog
    if not hasattr(changelog, 'histories'):
        return 0
    
    for history in changelog.histories:
        change_date = datetime.strptime(history.created[:19], '%Y-%m-%dT%H:%M:%S')
        
        # Check if change happened during this week
        if week_start <= change_date <= week_end:
            for item in history.items:
                if item.field == 'status' and 'accepted' in item.toString.lower():
                    return 1
    
    return 0

def fetch_weekly_work_data(jira, version="10.12.0.0", weeks_back=12):
    """
    Fetch weekly work summary data
    """
    # Calculate week ranges
    today = datetime.now()
    weeks = []
    for i in range(weeks_back, -1, -1):
        week_end = today - timedelta(weeks=i)
        week_end = week_end.replace(hour=23, minute=59, second=59, microsecond=0)
        week_start = week_end - timedelta(days=6, hours=23, minutes=59, seconds=59)
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        weeks.append((week_start, week_end))
    
    print(f"Fetching all bugs for version {version}...")
    
    # Fetch ALL bugs with changelog
    jql = f'project = DP AND type = Bug AND fixVersion = "{version}" ORDER BY created ASC'
    
    print(f"  Fetching all bugs with changelog...")
    all_issues = jira.search_issues(jql, maxResults=False, expand='changelog')
    
    print(f"✓ Found {len(all_issues)} total bugs for version {version}")
    
    # Determine release start date (earliest bug creation date)
    if all_issues:
        earliest_date = min([datetime.strptime(issue.fields.created[:10], '%Y-%m-%d').date() for issue in all_issues])
    else:
        earliest_date = datetime.now().date() - timedelta(days=90)  # Default to 90 days ago
    
    print(f"  Release tracking from: {earliest_date}")
    
    # Fetch sub test executions with changelog for burndown analysis
    print(f"Fetching sub test executions for version {version}...")
    jql_sub_exec = f'project = DP AND type = "sub test execution" AND fixVersion = "{version}" ORDER BY status'
    sub_executions = jira.search_issues(jql_sub_exec, maxResults=1000, fields='status,summary,created', expand='changelog')
    print(f"✓ Found {len(sub_executions)} sub test executions")
    
    # Categorize sub test executions
    sub_exec_total = 0
    sub_exec_completed = 0
    sub_exec_in_progress = 0
    sub_exec_not_started = 0
    
    for execution in sub_executions:
        status = execution.fields.status.name
        # Skip trash status
        if status.lower() == 'trash':
            continue
        
        sub_exec_total += 1
        
        # Categorize status
        if status.lower() in ['done', 'completed', 'passed', 'failed', 'closed', 'accepted']:
            sub_exec_completed += 1
        elif status.lower() in ['in progress', 'executing', 'in review']:
            sub_exec_in_progress += 1
        else:
            sub_exec_not_started += 1
    
    print(f"  Total: {sub_exec_total}, Completed: {sub_exec_completed}, In Progress: {sub_exec_in_progress}, Not Started: {sub_exec_not_started}")
    print(f"\nCalculating work summary for the last week...\n")
    
    dev_counts = []
    qa_counts = []
    accepted_counts = []
    week_labels = []
    sub_exec_burndown = []  # Track completed test executions per week
    
    # Calculate historical bug trend from release start
    print(f"\nCalculating historical bug trend from {earliest_date}...\n")
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
    
    # Calculate HIGH/CRITICAL priority bug trend
    print(f"\nCalculating HIGH/CRITICAL priority bug trend...\n")
    high_sev_issues = [issue for issue in all_issues if issue.fields.priority.name in ['High', 'Highest', 'Critical']]
    print(f"  Found {len(high_sev_issues)} HIGH/CRITICAL priority bugs")
    
    high_sev_dates = []
    high_sev_total = []
    high_sev_dev = []
    high_sev_qa = []
    high_sev_closed = []
    
    current_date = earliest_date
    while current_date <= end_date:
        high_sev_dates.append(current_date.strftime('%Y-%m-%d'))
        
        total_at_date = 0
        dev_at_date = 0
        qa_at_date = 0
        closed_at_date = 0
        
        for issue in high_sev_issues:
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
        
        high_sev_total.append(total_at_date)
        high_sev_dev.append(dev_at_date)
        high_sev_qa.append(qa_at_date)
        high_sev_closed.append(closed_at_date)
        
        current_date += timedelta(days=7)
    
    print(f"  Generated {len(high_sev_dates)} data points for HIGH/CRITICAL bugs")
    
    for week_start, week_end in weeks:
        week_label = week_end.strftime('Week of %b %d')
        week_labels.append(week_label)
        
        dev_count = 0
        qa_count = 0
        accepted_count = 0
        
        # Check status at end of week for each bug
        for issue in all_issues:
            status = get_bug_status_at_date(issue, week_end)
            if status == 'dev':
                dev_count += 1
            elif status == 'qa':
                qa_count += 1
            
            # Count if accepted during this week
            accepted_count += count_accepted_in_week(issue, week_start, week_end)
        
        dev_counts.append(dev_count)
        qa_counts.append(qa_count)
        accepted_counts.append(accepted_count)
        
        # Calculate sub test executions completed by this week end
        completed_by_week = 0
        for exec_issue in sub_executions:
            if exec_issue.fields.status.name.lower() in ['done', 'completed', 'passed', 'failed', 'closed', 'accepted']:
                # Check if completed by this week_end
                completion_date = None
                if hasattr(exec_issue.fields, 'changelog'):
                    for history in sorted(exec_issue.fields.changelog.histories, key=lambda h: h.created):
                        for item in history.items:
                            if item.field == 'status' and item.toString.lower() in ['done', 'completed', 'passed', 'failed', 'closed', 'accepted']:
                                completion_date = datetime.strptime(history.created[:10], '%Y-%m-%d').date()
                                break
                        if completion_date:
                            break
                
                # If no completion date in changelog, assume it was completed (might be initial status)
                if completion_date is None or completion_date <= week_end:
                    completed_by_week += 1
        
        sub_exec_burndown.append(completed_by_week)
        
        print(f"  {week_label}: Dev={dev_count}, QA={qa_count}, Accepted={accepted_count}")
    
    return {
        'week_labels': week_labels,
        'bugs_on_dev': dev_counts,
        'bugs_on_qa': qa_counts,
        'accepted_this_week': accepted_counts,
        'week_dates': [w[1].strftime('%Y-%m-%d') for w in weeks],
        'sub_exec_total': sub_exec_total,
        'sub_exec_completed': sub_exec_completed,
        'sub_exec_in_progress': sub_exec_in_progress,
        'sub_exec_not_started': sub_exec_not_started,
        'sub_exec_burndown': sub_exec_burndown,
        'sub_exec_details': sub_executions,
        'historical_dates': historical_dates,
        'historical_total': historical_total,
        'historical_dev': historical_dev,
        'historical_qa': historical_qa,
        'historical_closed': historical_closed,
        'high_sev_dates': high_sev_dates,
        'high_sev_total': high_sev_total,
        'high_sev_dev': high_sev_dev,
        'high_sev_qa': high_sev_qa,
        'high_sev_closed': high_sev_closed,
        'high_sev_count': len(high_sev_issues),
        'release_start': earliest_date.strftime('%Y-%m-%d')
    }

def generate_historical_bug_trend_chart(data, version="10.12.0.0"):
    """Generate weekly historical bug trend chart from release start"""
    
    fig = go.Figure()
    
    # Add total bugs line
    fig.add_trace(go.Scatter(
        x=data['historical_dates'],
        y=data['historical_total'],
        mode='lines+markers',
        name='Total Bugs',
        line=dict(color='#003366', width=4),
        marker=dict(size=8),
        hovertemplate='<b>Total Bugs</b><br>Week: %{x}<br>Count: %{y}<extra></extra>'
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
    
    fig.update_layout(
        title={
            'text': f'DefensePro {version} - Weekly Bug Trend from Release Start<br><sub>Tracking from {data["release_start"]} to {data["historical_dates"][-1]} ({len(data["historical_dates"])} weeks)</sub>',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 20, 'color': '#003366', 'family': 'Arial'}
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
        height=450,
        margin=dict(l=80, r=80, t=100, b=100),
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

def fetch_bugs_by_release(jira):
    """Fetch all open bugs grouped by release version (excluding DP Runners team, Trash bugs, and 10.100.0.0)"""
    # Get all open bugs (not Accepted, Closed, or Trash)
    jql = 'project = DP AND type = Bug AND status NOT IN (Accepted, Closed, Trash) ORDER BY fixVersion DESC'
    bugs = jira.search_issues(jql, maxResults=False, fields='key,fixVersion,status,priority,customfield_10129')
    
    # Group bugs by release version, filtering out DP Runners team and 10.100.0.0
    release_bugs = defaultdict(lambda: {'total': 0, 'high': 0, 'medium': 0, 'low': 0})
    
    for bug in bugs:
        # Skip bugs assigned to DP Runners team
        scrum_team = getattr(bug.fields, 'customfield_10129', None)
        if scrum_team:
            team_name = scrum_team.value if hasattr(scrum_team, 'value') else str(scrum_team)
            if team_name == 'DP Runners':
                continue
        
        # Get fixVersion (can be multiple, take the first one)
        if bug.fields.fixVersions:
            version = bug.fields.fixVersions[0].name
            # Skip bugs on 10.100.0.0 release
            if version == '10.100.0.0':
                continue
        else:
            version = 'Unassigned'
        
        release_bugs[version]['total'] += 1
        
        # Track by priority
        if hasattr(bug.fields, 'priority'):
            priority = bug.fields.priority.name
            if priority in ['High', 'Highest', 'Critical']:
                release_bugs[version]['high'] += 1
            elif priority == 'Medium':
                release_bugs[version]['medium'] += 1
            else:
                release_bugs[version]['low'] += 1
    
    return dict(release_bugs)

def generate_bugs_by_release_chart(release_data):
    """Generate bar chart showing in-progress bugs across releases"""
    
    # Sort releases by version number (reverse to show latest first)
    releases = sorted(release_data.keys(), reverse=True)
    
    # Extract data for each priority category
    high_bugs = [release_data[r]['high'] for r in releases]
    medium_bugs = [release_data[r]['medium'] for r in releases]
    low_bugs = [release_data[r]['low'] for r in releases]
    total_bugs = [release_data[r]['total'] for r in releases]
    
    fig = go.Figure()
    
    # Add bars for High priority bugs
    fig.add_trace(go.Bar(
        name='High Priority',
        x=releases,
        y=high_bugs,
        marker_color='#d32f2f',
        hovertemplate='<b>High Priority</b><br>Version: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    # Add bars for Medium priority bugs
    fig.add_trace(go.Bar(
        name='Medium Priority',
        x=releases,
        y=medium_bugs,
        marker_color='#f57c00',
        hovertemplate='<b>Medium Priority</b><br>Version: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    # Add bars for Low priority bugs
    fig.add_trace(go.Bar(
        name='Low Priority',
        x=releases,
        y=low_bugs,
        marker_color='#0288d1',
        hovertemplate='<b>Low Priority</b><br>Version: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    # Update layout
    fig.update_layout(
        title={
            'text': 'Open Bugs Across Active Releases<br><sub>Excluding DP Runners Team, Trash bugs, and 10.100.0.0</sub>',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 20, 'color': '#003366', 'family': 'Arial'}
        },
        xaxis=dict(
            title='Release Version',
            tickfont=dict(size=10),
            tickangle=-45
        ),
        yaxis=dict(
            title='Bug Count',
            showgrid=True,
            gridcolor='#e0e0e0',
            tickfont=dict(size=11)
        ),
        barmode='stack',
        plot_bgcolor='white',
        paper_bgcolor='white',
        height=500,
        margin=dict(l=80, r=80, t=100, b=120),
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

def generate_high_severity_bug_trend_chart(data, version="10.12.0.0"):
    """Generate weekly high severity (HIGH/CRITICAL) bug trend chart"""
    
    fig = go.Figure()
    
    # Add total high severity bugs line
    fig.add_trace(go.Scatter(
        x=data['high_sev_dates'],
        y=data['high_sev_total'],
        mode='lines+markers',
        name='Total High/Critical Bugs',
        line=dict(color='#d32f2f', width=4),
        marker=dict(size=8),
        hovertemplate='<b>Total High/Critical</b><br>Week: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    # Add high severity bugs on Dev line
    fig.add_trace(go.Scatter(
        x=data['high_sev_dates'],
        y=data['high_sev_dev'],
        mode='lines+markers',
        name='On Dev',
        line=dict(color='#ff6600', width=3),
        marker=dict(size=7),
        hovertemplate='<b>On Dev</b><br>Week: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    # Add high severity bugs on QA line
    fig.add_trace(go.Scatter(
        x=data['high_sev_dates'],
        y=data['high_sev_qa'],
        mode='lines+markers',
        name='On QA',
        line=dict(color='#0070c0', width=3),
        marker=dict(size=7),
        hovertemplate='<b>On QA</b><br>Week: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    # Add closed high severity bugs line
    fig.add_trace(go.Scatter(
        x=data['high_sev_dates'],
        y=data['high_sev_closed'],
        mode='lines+markers',
        name='Closed/Accepted',
        line=dict(color='#00b050', width=3),
        marker=dict(size=7),
        hovertemplate='<b>Closed/Accepted</b><br>Week: %{x}<br>Count: %{y}<extra></extra>'
    ))
    
    fig.update_layout(
        title={
            'text': f'DefensePro {version} - HIGH/CRITICAL Priority Bug Trend<br><sub>HIGH and CRITICAL priority bugs only | {data["release_start"]} to {data["high_sev_dates"][-1]} ({len(data["high_sev_dates"])} weeks)</sub>',
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
        height=450,
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

def generate_work_summary_chart(data, version="10.12.0.0"):
    """Generate interactive work summary chart using Plotly"""
    
    fig = go.Figure()
    
    # Create a single-week bar chart
    categories = ['Open on Dev', 'Open on QA', 'Accepted This Week']
    values = [data['bugs_on_dev'][-1], data['bugs_on_qa'][-1], data['accepted_this_week'][-1]]
    colors = ['#ff6600', '#0070c0', '#00b050']
    
    fig.add_trace(go.Bar(
        x=categories,
        y=values,
        marker=dict(color=colors),
        text=values,
        textposition='outside',
        textfont=dict(size=16, family='Arial Black'),
        hovertemplate='<b>%{x}</b><br>Count: %{y}<extra></extra>'
    ))
    
    # Update layout
    fig.update_layout(
        title={
            'text': f'DefensePro {version} - Weekly Bug Status<br><sub>{data["week_labels"][-1]}</sub>',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 24, 'color': '#003366', 'family': 'Arial'}
        },
        xaxis=dict(
            title='',
            showgrid=False,
            tickfont=dict(size=14)
        ),
        yaxis=dict(
            title='Bug Count',
            showgrid=True,
            gridcolor='lightgray',
            tickfont=dict(size=12),
            range=[0, max(values) * 1.15] if max(values) > 0 else [0, 10]
        ),
        plot_bgcolor='white',
        paper_bgcolor='white',
        height=400,
        margin=dict(l=80, r=80, t=100, b=80),
        showlegend=False
    )
    
    return fig

def generate_sub_exec_chart(data, version="10.12.0.0"):
    """Generate sub test execution status and burndown charts"""
    from plotly.subplots import make_subplots
    
    # Create subplots: 1 row, 2 columns
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=('Current Status', 'Completion Burndown'),
        specs=[[{'type': 'bar'}, {'type': 'scatter'}]],
        horizontal_spacing=0.15
    )
    
    # Left chart: Current status
    categories = ['Completed', 'In Progress', 'Not Started']
    values = [data['sub_exec_completed'], data['sub_exec_in_progress'], data['sub_exec_not_started']]
    colors = ['#00b050', '#ffc107', '#757575']
    
    fig.add_trace(
        go.Bar(
            x=categories,
            y=values,
            marker=dict(color=colors),
            text=values,
            textposition='outside',
            textfont=dict(size=14, color='black'),
            showlegend=False,
            hovertemplate='<b>%{x}</b><br>Count: %{y}<extra></extra>'
        ),
        row=1, col=1
    )
    
    # Right chart: Burndown trend
    fig.add_trace(
        go.Scatter(
            x=data['week_labels'],
            y=data['sub_exec_burndown'],
            mode='lines+markers',
            name='Completed',
            line=dict(color='#00b050', width=3),
            marker=dict(size=10),
            text=[f"{val} completed" for val in data['sub_exec_burndown']],
            hovertemplate='<b>%{x}</b><br>Completed: %{y}<extra></extra>'
        ),
        row=1, col=2
    )
    
    # Add target line if we have total
    if data['sub_exec_total'] > 0:
        fig.add_trace(
            go.Scatter(
                x=data['week_labels'],
                y=[data['sub_exec_total']] * len(data['week_labels']),
                mode='lines',
                name='Target Total',
                line=dict(color='#2196f3', width=2, dash='dash'),
                showlegend=True,
                hovertemplate='<b>Target</b><br>Total: %{y}<extra></extra>'
            ),
            row=1, col=2
        )
    
    # Update axes
    fig.update_xaxes(title_text='', row=1, col=1, gridcolor='#e0e0e0', tickfont=dict(size=12))
    fig.update_yaxes(title_text='Count', row=1, col=1, gridcolor='#e0e0e0', tickfont=dict(size=11))
    fig.update_xaxes(title_text='', row=1, col=2, gridcolor='#e0e0e0', tickfont=dict(size=12))
    fig.update_yaxes(title_text='Completed Tests', row=1, col=2, gridcolor='#e0e0e0', tickfont=dict(size=11))
    
    # Update layout
    fig.update_layout(
        title={
            'text': f'DefensePro {version} - Sub Test Execution Status<br><sub>Total: {data["sub_exec_total"]} tasks</sub>',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 24, 'color': '#003366', 'family': 'Arial'}
        },
        xaxis=dict(
            title='',
            showgrid=False,
            tickfont=dict(size=14)
        ),
        yaxis=dict(
            title='Task Count',
            showgrid=True,
            gridcolor='lightgray',
            tickfont=dict(size=12),
            range=[0, max(values) * 1.15] if max(values) > 0 else [0, 10]
        ),
        plot_bgcolor='white',
        paper_bgcolor='white',
        height=400,
        margin=dict(l=80, r=80, t=100, b=80),
        showlegend=False
    )
    
    return fig

def save_data_to_csv(data, version="10.12.0.0"):
    """Save the work summary data to CSV"""
    df = pd.DataFrame({
        'Week Ending': data['week_dates'],
        'Week Label': data['week_labels'],
        'Open on Dev': data['bugs_on_dev'],
        'Open on QA': data['bugs_on_qa'],
        'Accepted This Week': data['accepted_this_week']
    })
    
    filename = f'weekly_work_summary_{version}.csv'
    df.to_csv(filename, index=False)
    print(f"\n✓ Data saved to {filename}")
    return filename

def main():
    """Main execution function"""
    try:
        print("=" * 70)
        print("Weekly Work Summary")
        print("DefensePro 10.13.0.0")
        print("=" * 70)
        print()
        
        # Connect to Jira
        print("Connecting to Jira...")
        jira = connect_to_jira()
        print("✓ Connected successfully\n")
        
        # Fetch work summary data
        version = "10.13.0.0"
        weeks_back = 0  # Just the current/last week
        data = fetch_weekly_work_data(jira, version=version, weeks_back=weeks_back)
        
        # Save data to CSV
        csv_file = save_data_to_csv(data, version=version)
        
        # Fetch all bugs with details for the report
        print("\nFetching detailed bug information...")
        jql_all_bugs = f'project = DP AND fixVersion = "{version}" AND type = Bug ORDER BY priority DESC, created DESC'
        all_bugs_detailed = jira.search_issues(jql_all_bugs, maxResults=False, fields='key,summary,status,priority,created')
        
        # Categorize bugs
        bugs_on_dev = []
        bugs_on_qa = []
        bugs_closed = []
        
        for bug in all_bugs_detailed:
            status_name = bug.fields.status.name.lower()
            if 'accepted' in status_name or 'closed' in status_name:
                bugs_closed.append(bug)
            elif 'completed' in status_name:
                bugs_on_qa.append(bug)
            else:
                bugs_on_dev.append(bug)
        
        print(f"✓ Categorized bugs: Dev={len(bugs_on_dev)}, QA={len(bugs_on_qa)}, Closed={len(bugs_closed)}")
        
        # Generate charts
        print("\nGenerating weekly work summary charts...")
        fig_bugs = generate_work_summary_chart(data, version=version)
        fig_sub_exec = generate_sub_exec_chart(data, version=version)
        fig_historical = generate_historical_bug_trend_chart(data, version=version)
        fig_high_sev = generate_high_severity_bug_trend_chart(data, version=version)
        
        # Fetch bugs by release distribution
        print("\nFetching bug distribution across releases...")
        release_bugs = fetch_bugs_by_release(jira)
        fig_release_dist = generate_bugs_by_release_chart(release_bugs)
        print(f"✓ Found bugs across {len(release_bugs)} releases")
        
        # Build bug tables HTML
        bugs_dev_html = ""
        for bug in bugs_on_dev:
            priority_class = "priority-low"
            if bug.fields.priority.name == "High":
                priority_class = "priority-high"
            elif bug.fields.priority.name == "Medium":
                priority_class = "priority-medium"
            
            created_date = datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').strftime('%b %d, %Y')
            bugs_dev_html += f"""
                <tr>
                    <td><a href="https://rwrnd.atlassian.net/browse/{bug.key}" class="bug-key" target="_blank">{bug.key}</a></td>
                    <td><span class="{priority_class}">{bug.fields.priority.name}</span></td>
                    <td>{bug.fields.summary}</td>
                    <td>{created_date}</td>
                </tr>
            """
        
        bugs_qa_html = ""
        for bug in bugs_on_qa:
            priority_class = "priority-low"
            if bug.fields.priority.name == "High":
                priority_class = "priority-high"
            elif bug.fields.priority.name == "Medium":
                priority_class = "priority-medium"
            
            created_date = datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').strftime('%b %d, %Y')
            bugs_qa_html += f"""
                <tr>
                    <td><a href="https://rwrnd.atlassian.net/browse/{bug.key}" class="bug-key" target="_blank">{bug.key}</a></td>
                    <td><span class="{priority_class}">{bug.fields.priority.name}</span></td>
                    <td>{bug.fields.summary}</td>
                    <td>{created_date}</td>
                </tr>
            """
        
        # Priority breakdown
        priority_counts = {"High": 0, "Medium": 0, "Low": 0}
        for bug in all_bugs_detailed:
            if bug.fields.status.name.lower() not in ['accepted', 'closed']:
                priority_counts[bug.fields.priority.name] = priority_counts.get(bug.fields.priority.name, 0) + 1
        
        # Generate combined HTML report
        output_file = f'weekly_work_summary_{version}.html'
        
        # Create HTML with all sections
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Weekly Work Summary - DefensePro {version}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background-color: white; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); border-radius: 8px; }}
        h1 {{ color: #003366; border-bottom: 3px solid #0070c0; padding-bottom: 10px; margin-bottom: 10px; text-align: center; }}
        h2 {{ color: #0070c0; margin-top: 30px; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }}
        .metadata {{ color: #666; font-size: 14px; margin-bottom: 30px; text-align: center; }}
        .summary-box {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }}
        .metric-card {{ padding: 20px; border-radius: 8px; text-align: center; box-shadow: 0 2px 5px rgba(0,0,0,0.1); color: white; }}
        .metric-card.bugs {{ background: linear-gradient(135deg, #0070c0 0%, #3399dd 100%); }}
        .metric-card.sub-exec {{ background: linear-gradient(135deg, #9c27b0 0%, #ba68c8 100%); }}
        .metric-number {{ font-size: 48px; font-weight: bold; margin: 10px 0; }}
        .metric-label {{ font-size: 16px; font-weight: 500; }}
        .metric-detail {{ font-size: 14px; opacity: 0.9; margin-top: 10px; }}
        .chart-container {{ margin: 30px 0; }}
        .section-title {{ color: #003366; font-size: 20px; font-weight: bold; margin: 30px 0 15px 0; padding-bottom: 5px; border-bottom: 2px solid #e0e0e0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        th {{ background-color: #003366; color: white; padding: 12px; text-align: left; font-weight: 600; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #e0e0e0; }}
        tr:hover {{ background-color: #f9f9f9; }}
        .priority-high {{ color: #d32f2f; font-weight: bold; }}
        .priority-medium {{ color: #f57c00; font-weight: bold; }}
        .priority-low {{ color: #0288d1; font-weight: bold; }}
        .bug-key {{ font-family: monospace; font-weight: bold; color: #0070c0; text-decoration: none; }}
        .bug-key:hover {{ text-decoration: underline; }}
        .observation-list {{ background-color: #f0f7ff; padding: 20px; border-left: 4px solid #0070c0; margin: 20px 0; }}
        .observation-list ul {{ margin: 10px 0; padding-left: 20px; }}
        .observation-list li {{ margin: 8px 0; line-height: 1.6; }}
        .alert-box {{ background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }}
        .alert-box.info {{ background-color: #e3f2fd; border-left-color: #2196f3; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Weekly Work Summary - DefensePro {version}</h1>
        <div class="metadata">
            <strong>Week Ending:</strong> {data['week_dates'][-1]}<br>
            <strong>Report Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>

        <div class="summary-box">
            <div class="metric-card bugs">
                <div class="metric-label">Total Open Bugs</div>
                <div class="metric-number">{len(bugs_on_dev) + len(bugs_on_qa)}</div>
                <div class="metric-detail">Dev: {len(bugs_on_dev)} | QA: {len(bugs_on_qa)}<br>Accepted This Week: {data['accepted_this_week'][-1]}</div>
            </div>
            <div class="metric-card sub-exec">
                <div class="metric-label">Sub Test Executions</div>
                <div class="metric-number">{data['sub_exec_total']}</div>
                <div class="metric-detail">Completed: {data['sub_exec_completed']}<br>In Progress: {data['sub_exec_in_progress']} | Not Started: {data['sub_exec_not_started']}</div>
            </div>
        </div>

        <div class="section-title">📊 Bug Status Distribution</div>
        <div class="chart-container" id="bugs-chart"></div>

        <h2>Historical Bug Trend from Release Start</h2>
        <p>Weekly tracking from {data['release_start']} to present ({len(data['historical_dates'])} weeks) - Current: Total: {data['historical_total'][-1]}, On Dev: {data['historical_dev'][-1]}, On QA: {data['historical_qa'][-1]}</p>
        <div class="chart-container" id="historical-trend-chart"></div>

        <h2>High/Critical Priority Bug Trend</h2>
        <p>Tracking only HIGH, HIGHEST, and CRITICAL priority bugs from {data['release_start']} to present - Current: Total: {data.get('high_sev_total', [0])[-1]}, On Dev: {data.get('high_sev_dev', [0])[-1]}, On QA: {data.get('high_sev_qa', [0])[-1]}</p>
        <div class="chart-container" id="high-sev-trend-chart"></div>

        <h2>Open Bugs Distribution Across Releases</h2>
        <p>In-progress bugs currently being worked on by Dev - Total releases with active work: {len(release_bugs)}</p>
        <div class="chart-container" id="release-dist-chart"></div>

        <h2>Bugs on Dev ({len(bugs_on_dev)} bugs)</h2>
        <p>Status: Bugs assigned but not started or newly reported</p>
        <table>
            <thead><tr><th>Key</th><th>Priority</th><th>Summary</th><th>Created</th></tr></thead>
            <tbody>{bugs_dev_html if bugs_dev_html else '<tr><td colspan="4" style="text-align: center;">No bugs on Dev</td></tr>'}</tbody>
        </table>

        <h2>Bugs on QA ({len(bugs_on_qa)} bugs)</h2>
        <p>Status: Completed - Bugs resolved by Dev, awaiting QA verification</p>
        <table>
            <thead><tr><th>Key</th><th>Priority</th><th>Summary</th><th>Created</th></tr></thead>
            <tbody>{bugs_qa_html if bugs_qa_html else '<tr><td colspan="4" style="text-align: center;">No bugs on QA</td></tr>'}</tbody>
        </table>

        <h2>Priority Breakdown</h2>
        <table>
            <thead><tr><th>Priority</th><th>Count</th><th>Percentage</th></tr></thead>
            <tbody>
                <tr><td><span class="priority-high">High</span></td><td>{priority_counts.get('High', 0)}</td><td>{priority_counts.get('High', 0) / max(len(all_bugs_detailed) - len(bugs_closed), 1) * 100:.1f}%</td></tr>
                <tr><td><span class="priority-medium">Medium</span></td><td>{priority_counts.get('Medium', 0)}</td><td>{priority_counts.get('Medium', 0) / max(len(all_bugs_detailed) - len(bugs_closed), 1) * 100:.1f}%</td></tr>
                <tr><td><span class="priority-low">Low</span></td><td>{priority_counts.get('Low', 0)}</td><td>{priority_counts.get('Low', 0) / max(len(all_bugs_detailed) - len(bugs_closed), 1) * 100:.1f}%</td></tr>
            </tbody>
        </table>

        <div class="section-title">🧪 Sub Test Execution Status</div>
        <div class="chart-container" id="sub-exec-chart"></div>

        <h2>Sub Test Execution Analysis</h2>
        {'<div class="alert-box info"><strong>Status:</strong> No sub test executions found for this version. Test execution tracking may not have started yet, or tests are being tracked in a different manner.</div>' if data['sub_exec_total'] == 0 else ''}
        <div class="observation-list">
            <ul>
                <li><strong>Total Test Executions:</strong> {data['sub_exec_total']}</li>
                <li><strong>Completion Status:</strong> 
                    {'All test executions completed ✓' if data['sub_exec_total'] > 0 and data['sub_exec_completed'] == data['sub_exec_total'] else 
                     f"{data['sub_exec_completed']}/{data['sub_exec_total']} completed ({data['sub_exec_completed']/max(data['sub_exec_total'],1)*100:.1f}%)" if data['sub_exec_total'] > 0 else
                     'No active test executions (0/0 completed)'}
                </li>
                <li><strong>Burndown Progress:</strong> 
                    {'Test execution tracking not yet initiated' if data['sub_exec_total'] == 0 else
                     f"Completed {data['sub_exec_burndown'][-1]} out of {data['sub_exec_total']} test executions"}
                </li>
                <li><strong>Recommendation:</strong> 
                    {'⚠️ Sub test execution tracking should be initiated for this release version to ensure proper test coverage validation' if data['sub_exec_total'] == 0 else
                     '✓ Test execution tracking is active' if data['sub_exec_in_progress'] > 0 else
                     '✓ All test executions completed' if data['sub_exec_completed'] == data['sub_exec_total'] else
                     f'⚠️ {data['sub_exec_not_started']} test executions not started - review test execution plan'}
                </li>
            </ul>
        </div>

        <h2>Key Observations</h2>
        <div class="observation-list">
            <ul>
                <li><strong>Open Bugs:</strong> {len(bugs_on_dev) + len(bugs_on_qa)} total ({len(bugs_on_dev)} on Dev, {len(bugs_on_qa)} on QA)</li>
                <li><strong>Accepted This Week:</strong> {data['accepted_this_week'][-1]} bugs closed</li>
                <li><strong>Priority Distribution:</strong> {priority_counts.get('High', 0)} High, {priority_counts.get('Medium', 0)} Medium, {priority_counts.get('Low', 0)} Low</li>
                <li><strong>Test Executions:</strong> {data['sub_exec_completed']}/{data['sub_exec_total']} sub test executions completed</li>
            </ul>
        </div>

        <div class="footer">
            <p>Generated from Jira Project: DP (DefensePro) | Version: {version}</p>
            <p><strong>Note:</strong> This is a READ-ONLY report. No Jira issues were created or modified during this analysis.</p>
        </div>
    </div>

    {fig_bugs.to_html(include_plotlyjs='cdn', div_id='bugs-chart', full_html=False)}
    {fig_historical.to_html(include_plotlyjs=False, div_id='historical-trend-chart', full_html=False)}
    {fig_high_sev.to_html(include_plotlyjs=False, div_id='high-sev-trend-chart', full_html=False)}
    {fig_release_dist.to_html(include_plotlyjs=False, div_id='release-dist-chart', full_html=False)}
    {fig_sub_exec.to_html(include_plotlyjs=False, div_id='sub-exec-chart', full_html=False)}
</body>
</html>"""
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✓ Report saved to {output_file}")
        
        # Display summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Latest Week: {data['week_labels'][-1]}")
        print(f"  • Open on Dev: {data['bugs_on_dev'][-1]}")
        print(f"  • Open on QA: {data['bugs_on_qa'][-1]}")
        print(f"  • Accepted This Week: {data['accepted_this_week'][-1]}")
        print(f"  • Sub Test Executions: {data['sub_exec_completed']}/{data['sub_exec_total']} completed")
        print()
        
        print("\n✓ Report generation complete!")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
    
    # Generate open bugs report after weekly report
    print("\nGenerating open bugs report...")
    import subprocess
    try:
        subprocess.run(['python', 'list_open_bugs.py'], check=True, cwd=os.path.dirname(__file__) or '.')
    except subprocess.CalledProcessError as e:
        print(f"✗ Error generating bugs report: {e}")
    except Exception as e:
        print(f"✗ Error running bugs report: {e}")
