"""
Unified Weekly Report for DefensePro
Combines weekly work summary with CI iteration automation status

Includes:
- Bug status tracking (Dev, QA, Accepted)
- Sub test execution progress
- CI Iteration automation status (test executions, coverage, failures)
- Historical trends
"""

import os
from dotenv import load_dotenv
from jira import JIRA
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from collections import defaultdict
import psycopg2

load_dotenv()

def get_version_info(jira, version_name):
    """Get version information to check if it's released or active"""
    try:
        # Get DP project versions
        versions = jira.project_versions('DP')
        for v in versions:
            if v.name == version_name:
                # Check if version is released
                is_released = getattr(v, 'released', False)
                is_archived = getattr(v, 'archived', False)
                release_date = getattr(v, 'releaseDate', None)
                
                print(f"Version Info:")
                print(f"  Name: {v.name}")
                print(f"  Released: {is_released}")
                print(f"  Archived: {is_archived}")
                if release_date:
                    print(f"  Release Date: {release_date}")
                print()
                
                return {
                    'name': v.name,
                    'released': is_released,
                    'archived': is_archived,
                    'release_date': release_date,
                    'is_active': not is_released and not is_archived
                }
        
        print(f"⚠️  Version {version_name} not found in Jira, assuming active\n")
        return {'name': version_name, 'released': False, 'archived': False, 'is_active': True}
    except Exception as e:
        print(f"⚠️  Could not fetch version info: {e}\n")
        return {'name': version_name, 'released': False, 'archived': False, 'is_active': True}

def connect_to_jira():
    """Connect to Jira using credentials from .env file"""
    jira_url = os.getenv('JIRA_URL')
    jira_email = os.getenv('JIRA_EMAIL')
    jira_api_token = os.getenv('JIRA_API_TOKEN')
    
    options = {'server': jira_url, 'verify': False}
    jira = JIRA(options=options, basic_auth=(jira_email, jira_api_token))
    return jira

def connect_to_postgres():
    """Connect to PostgreSQL database"""
    conn = psycopg2.connect(
        host=os.getenv('PG_HOST', '10.185.20.124'),
        port=os.getenv('PG_PORT', '5432'),
        database=os.getenv('PG_DATABASE', 'results'),
        user=os.getenv('PG_USER', 'postgres'),
        password=os.getenv('PG_PASSWORD', '')
    )
    return conn

def get_current_sprint(jira, board_id=None):
    """Get current active sprint"""
    if board_id is None:
        boards = jira.boards()
        for board in boards:
            if 'DP' in board.name or 'DefensePro' in board.name:
                board_id = board.id
                break
    
    if board_id:
        sprints = jira.sprints(board_id, state='active')
        if sprints:
            return sprints[0]
    
    # Fallback: use last 2 weeks
    end_date = datetime.now()
    start_date = end_date - timedelta(weeks=2)
    
    class FakeSprint:
        def __init__(self):
            self.name = f"Current Iteration ({start_date.strftime('%b %d')} - {end_date.strftime('%b %d')})"
            self.startDate = start_date.isoformat()
            self.endDate = end_date.isoformat()
    
    return FakeSprint()

def get_automation_data(conn, jira, version, builds, sprint_start, sprint_end):
    """Get automation test data for the sprint period"""
    builds_str = ','.join([f"'{b}'" for b in builds.split(',')])
    
    # Get tests executed in sprint
    tests_query = f"""
        SELECT DISTINCT te.test_id
        FROM test_execution te
        WHERE te.version = '{version}'
          AND te.start_time BETWEEN '{sprint_start}' AND '{sprint_end}'
          AND te.mode = 'regression'
    """
    tests_df = pd.read_sql(tests_query, conn)
    test_ids = tests_df['test_id'].tolist()
    
    if not test_ids:
        return {
            'total_tests': 0,
            'total_executions': 0,
            'passed': 0,
            'failed': 0,
            'pass_ratio': 0,
            'platform_data': [],
            'failed_tests': []
        }
    
    # Get execution results
    test_ids_str = ','.join([str(tid) for tid in test_ids])
    exec_query = f"""
        WITH latest_execution AS (
            SELECT 
                te.test_id,
                t.name as test_name,
                d.platform,
                te.status,
                CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END as mode,
                ROW_NUMBER() OVER (
                    PARTITION BY te.test_id, d.platform, 
                    CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END
                    ORDER BY te.start_time DESC
                ) as rn
            FROM test_execution te
            JOIN device d ON te.device_id = d.id
            JOIN profile p ON te.profile_id = p.id
            JOIN test t ON te.test_id = t.id
            WHERE te.test_id IN ({test_ids_str})
              AND te.version = '{version}'
              AND te.build IN ({builds_str})
              AND te.mode = 'regression'
        )
        SELECT test_id, test_name, platform, status, mode
        FROM latest_execution
        WHERE rn = 1
    """
    executions_df = pd.read_sql(exec_query, conn)
    
    # Normalize status to lowercase for comparison
    executions_df['status_lower'] = executions_df['status'].str.lower()
    
    # Add platform type mapping
    platform_type_map = {
        'UHT': 'FPGA', 'MRQP': 'FPGA', 'MR2': 'FPGA',
        'ESXI': 'Software', 'KVM': 'Software', 'VL3': 'Software', 'HT2': 'Software',
        'MRQ_X': 'EZchip'
    }
    executions_df['platform_type'] = executions_df['platform'].map(platform_type_map)
    executions_df['platform_type_mode'] = executions_df['platform_type'] + ' - ' + executions_df['mode']
    
    # Calculate statistics
    stats = {
        'total_tests': len(test_ids),
        'total_executions': len(executions_df),
        'passed': len(executions_df[executions_df['status_lower'] == 'passed']),
        'failed': len(executions_df[executions_df['status_lower'].isin(['failed', 'error', 'fail'])]),
        'pass_ratio': len(executions_df[executions_df['status_lower'] == 'passed']) / max(len(executions_df), 1) * 100
    }
    
    # Get available tests for coverage calculation (from 10.12.0.0 and 10.11.0.0)
    available_tests_query = f"""
        SELECT d.platform,
               CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END as mode,
               COUNT(DISTINCT te.test_id) as available_tests
        FROM test_execution te
        JOIN device d ON te.device_id = d.id
        JOIN profile p ON te.profile_id = p.id
        WHERE te.version IN ('10.12.0.0', '10.11.0.0')
          AND te.mode = 'regression'
        GROUP BY d.platform, CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END
    """
    available_df = pd.read_sql(available_tests_query, conn)
    available_df['platform_type'] = available_df['platform'].map(platform_type_map)
    available_df['platform_type_mode'] = available_df['platform_type'] + ' - ' + available_df['mode']
    
    # Platform Type + Mode breakdown (aggregated) with coverage
    platform_type_stats = []
    for pt_mode in executions_df['platform_type_mode'].unique():
        pt_df = executions_df[executions_df['platform_type_mode'] == pt_mode]
        passed_count = len(pt_df[pt_df['status_lower'] == 'passed'])
        failed_count = len(pt_df[pt_df['status_lower'].isin(['failed', 'error', 'fail'])])
        unique_tests = len(pt_df['test_id'].unique())
        
        # Calculate coverage
        available_tests = available_df[available_df['platform_type_mode'] == pt_mode]['available_tests'].sum()
        coverage = (unique_tests / max(available_tests, 1)) * 100 if available_tests > 0 else 0
        
        platform_type_stats.append({
            'platform_type_mode': pt_mode,
            'tests': unique_tests,
            'available_tests': int(available_tests),
            'coverage': coverage,
            'executions': len(pt_df),
            'passed': passed_count,
            'failed': failed_count,
            'pass_ratio': passed_count / max(len(pt_df), 1) * 100
        })
    
    stats['platform_type_data'] = platform_type_stats
    
    # Calculate overall coverage
    if platform_type_stats:
        total_executed = sum(p['tests'] for p in platform_type_stats)
        total_available = sum(p['available_tests'] for p in platform_type_stats)
        stats['overall_coverage'] = (total_executed / max(total_available, 1)) * 100
    else:
        stats['overall_coverage'] = 0
    
    # Individual platform breakdown (for detailed view)
    platform_stats = []
    for platform in executions_df['platform'].unique():
        platform_df = executions_df[executions_df['platform'] == platform]
        passed_count = len(platform_df[platform_df['status_lower'] == 'passed'])
        failed_count = len(platform_df[platform_df['status_lower'].isin(['failed', 'error', 'fail'])])
        platform_stats.append({
            'platform': platform,
            'tests': len(platform_df),
            'passed': passed_count,
            'failed': failed_count,
            'pass_ratio': passed_count / max(len(platform_df), 1) * 100
        })
    
    stats['platform_data'] = platform_stats
    
    # Get tests that failed on ALL platforms (using latest test results from builds)
    failed_query = f"""
        WITH test_executions AS (
            SELECT 
                te.test_id,
                t.name as test_name,
                d.platform,
                CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END as mode,
                LOWER(te.status) as status
            FROM test_execution te
            JOIN device d ON te.device_id = d.id
            JOIN profile p ON te.profile_id = p.id
            JOIN test t ON te.test_id = t.id
            WHERE te.test_id IN ({test_ids_str})
              AND te.version = '{version}'
              AND te.build IN ({builds_str})
              AND te.mode = 'regression'
        ),
        test_platform_status AS (
            SELECT 
                test_id,
                test_name,
                platform,
                mode,
                COUNT(CASE WHEN status IN ('failed', 'error', 'fail') THEN 1 END) as failed_count,
                COUNT(CASE WHEN status = 'passed' THEN 1 END) as passed_count
            FROM test_executions
            GROUP BY test_id, test_name, platform, mode
        ),
        tests_failed_everywhere AS (
            SELECT 
                test_id,
                test_name,
                COUNT(DISTINCT platform) as platforms_count,
                SUM(CASE WHEN failed_count > 0 AND passed_count = 0 THEN 1 ELSE 0 END) as failed_platforms_count
            FROM test_platform_status
            GROUP BY test_id, test_name
            HAVING COUNT(DISTINCT platform) = SUM(CASE WHEN failed_count > 0 AND passed_count = 0 THEN 1 ELSE 0 END)
        )
        SELECT test_id, test_name
        FROM tests_failed_everywhere
        ORDER BY test_name
    """
    
    failed_tests_df = pd.read_sql(failed_query, conn)
    stats['failed_tests'] = failed_tests_df.to_dict('records')
    stats['critical_failures'] = len(failed_tests_df)
    
    # Get bugs opened during sprint with automation origin
    automation_bugs_query = f"""
        project = DP 
        AND type = Bug 
        AND fixVersion = "{version}"
        AND created >= "{sprint_start[:10]}" 
        AND created <= "{sprint_end[:10]}"
        AND Origin in ("functional automation", "automation", "Functional Automation", "Automation")
    """
    
    try:
        automation_bugs = jira.search_issues(automation_bugs_query, maxResults=100)
        stats['automation_bugs'] = [{
            'key': bug.key,
            'summary': bug.fields.summary,
            'status': bug.fields.status.name,
            'priority': bug.fields.priority.name if hasattr(bug.fields, 'priority') and bug.fields.priority else 'N/A',
            'created': bug.fields.created[:10]
        } for bug in automation_bugs]
        stats['automation_bugs_count'] = len(automation_bugs)
    except Exception as e:
        print(f"Warning: Could not fetch automation bugs: {e}")
        stats['automation_bugs'] = []
        stats['automation_bugs_count'] = 0
    
    return stats

def generate_insights(platform_type_data, stats, sprint_name):
    """Generate automated insights from platform type data"""
    insights = []
    
    if not platform_type_data:
        insights.append("⚠️ No automation test data available for this sprint period.")
        return insights
    
    # Overall coverage insight
    overall_coverage = stats.get('overall_coverage', 0)
    if overall_coverage >= 90:
        insights.append(f"✓ Excellent test coverage: {overall_coverage:.1f}% of available tests executed during sprint.")
    elif overall_coverage >= 70:
        insights.append(f"⚠️ Good test coverage: {overall_coverage:.1f}% of available tests executed. Target: 90%+")
    else:
        insights.append(f"⚠️ Low test coverage: {overall_coverage:.1f}% of available tests executed. Significant gaps remain.")
    
    # Pass ratio insight
    pass_ratio = stats.get('pass_ratio', 0)
    if pass_ratio >= 95:
        insights.append(f"✓ Excellent quality: {pass_ratio:.1f}% pass ratio across all platforms.")
    elif pass_ratio >= 85:
        insights.append(f"⚠️ Good quality: {pass_ratio:.1f}% pass ratio. Some failures need attention.")
    else:
        insights.append(f"⚠️ Quality concerns: {pass_ratio:.1f}% pass ratio. Significant failures detected.")
    
    # Coverage gaps by platform type
    low_coverage = [p for p in platform_type_data if p['coverage'] < 70]
    if low_coverage:
        insights.append(f"⚠️ Coverage gaps in: {', '.join([p['platform_type_mode'] for p in low_coverage])}")
    
    # Best/worst performers
    sorted_by_pass = sorted(platform_type_data, key=lambda x: x['pass_ratio'], reverse=True)
    if len(sorted_by_pass) > 0:
        best = sorted_by_pass[0]
        worst = sorted_by_pass[-1]
        if best['pass_ratio'] - worst['pass_ratio'] > 10:
            insights.append(f"📊 Performance gap: {best['platform_type_mode']} ({best['pass_ratio']:.1f}%) vs {worst['platform_type_mode']} ({worst['pass_ratio']:.1f}%)")
    
    # Critical failures
    critical_failures = stats.get('critical_failures', 0)
    if critical_failures > 0:
        insights.append(f"🚨 {critical_failures} tests failing on ALL platforms - requires immediate investigation.")
    
    # Automation bugs
    automation_bugs = stats.get('automation_bugs_count', 0)
    if automation_bugs > 0:
        insights.append(f"⚠️ {automation_bugs} bugs with automation origin opened during sprint.")
    
    return insights

def get_bug_status_at_date(issue, target_date):
    """Determine bug status category at a specific date by examining changelog"""
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    
    created_date = datetime.strptime(issue.fields.created[:10], '%Y-%m-%d').date()
    if created_date > target_date:
        return 'not_created'
    
    status_at_date = 'None'
    changelog = issue.changelog
    if hasattr(changelog, 'histories'):
        sorted_histories = sorted(changelog.histories, key=lambda h: h.created)
        
        for history in sorted_histories:
            change_date = datetime.strptime(history.created[:19], '%Y-%m-%dT%H:%M:%S').date()
            if change_date > target_date:
                break
            
            for item in history.items:
                if item.field == 'status':
                    status_at_date = item.toString
    
    status_lower = status_at_date.lower()
    if 'accepted' in status_lower:
        return 'closed'
    elif 'completed' in status_lower:
        return 'qa'
    elif any(s in status_lower for s in ['in progress', 'to do', 'to-do', 'none', 'open']):
        return 'dev'
    else:
        return 'dev'

def main():
    version = os.getenv('VERSION')
    builds = os.getenv('BUILDS', '100,101,102,103,104,105,106')
    
    if not version:
        version = input("Enter version (e.g., 10.12.0.0): ").strip()
    
    print(f"\n{'='*70}")
    print(f"UNIFIED WEEKLY REPORT - DefensePro {version}")
    print(f"{'='*70}\n")
    
    # Connect to Jira and PostgreSQL
    print("Connecting to systems...")
    jira = connect_to_jira()
    conn = connect_to_postgres()
    print("✓ Connected\n")
    
    # Get sprint info
    sprint = get_current_sprint(jira)
    sprint_start = sprint.startDate
    sprint_end = sprint.endDate
    print(f"Sprint: {sprint.name}")
    print(f"Period: {sprint_start[:10]} to {sprint_end[:10]}\n")
    
    # Get version info to check if it's active
    version_info = get_version_info(jira, version)
    
    if version_info['released']:
        print(f"⚠️  WARNING: Version {version} is marked as RELEASED in Jira")
        print(f"   All bugs for this version should be closed.")
        print(f"   Consider using an active/unreleased version for meaningful reports.\n")
    
    if version_info['archived']:
        print(f"⚠️  WARNING: Version {version} is ARCHIVED in Jira")
        print(f"   This is a historical version with no active work.\n")
    
    # Get bug data - filter by state for active versions
    print("Fetching bug data...")
    if version_info['is_active']:
        # For active versions, fetch only open bugs (exclude Done/Accepted)
        jql = f'project = DP AND fixVersion = "{version}" AND type = Bug AND statusCategory != Done'
    else:
        # For released versions, fetch all bugs to show closure status
        jql = f'project = DP AND fixVersion = "{version}" AND type = Bug'
    
    bugs = jira.search_issues(jql, maxResults=False, expand='changelog')
    print(f"✓ Found {len(bugs)} bugs\n")
    
    # Get automation data
    print("Fetching automation data...")
    automation_data = get_automation_data(conn, jira, version, builds, sprint_start, sprint_end)
    print(f"✓ Found {automation_data['total_tests']} tests with {automation_data['total_executions']} executions\n")
    
    # Categorize bugs based on status category and name
    bugs_on_dev = []
    bugs_on_qa = []
    bugs_closed = []
    
    for bug in bugs:
        status_name = bug.fields.status.name.lower() if hasattr(bug.fields, 'status') else 'unknown'
        status_category = bug.fields.status.statusCategory.name.lower() if hasattr(bug.fields, 'status') and hasattr(bug.fields.status, 'statusCategory') else 'unknown'
        
        # Closed/Done status
        if 'done' in status_category or 'complete' in status_category:
            bugs_closed.append(bug)
        elif 'accepted' in status_name:
            bugs_closed.append(bug)
        # On QA status (Completed but not Accepted)
        elif 'completed' in status_name and 'accepted' not in status_name:
            bugs_on_qa.append(bug)
        elif 'resolved' in status_name or 'fixed' in status_name:
            bugs_on_qa.append(bug)
        # On Dev status
        elif 'in progress' in status_category or 'in progress' in status_name:
            bugs_on_dev.append(bug)
        elif 'to do' in status_category or 'to do' in status_name or 'to-do' in status_name:
            bugs_on_dev.append(bug)
        elif 'open' in status_name or 'new' in status_name or status_name == 'none':
            bugs_on_dev.append(bug)
        else:
            # Default: if not clearly closed or on QA, assume on Dev
            print(f"  Warning: Bug {bug.key} defaulting to Dev - Status: {status_name} (Category: {status_category})")
            bugs_on_dev.append(bug)
    
    # Debug output
    print(f"\nBug categorization:")
    print(f"  On Dev: {len(bugs_on_dev)}")
    print(f"  On QA: {len(bugs_on_qa)}")
    print(f"  Closed: {len(bugs_closed)}")
    if bugs_on_dev:
        print(f"  Sample Dev bug status: {bugs_on_dev[0].fields.status.name}")
    if bugs_on_qa:
        print(f"  Sample QA bug status: {bugs_on_qa[0].fields.status.name}")
    
    # Get sub test executions - filter by state and active release
    if version_info['is_active']:
        # For active versions, fetch all sub test executions (to track progress)
        sub_exec_jql = f'project = DP AND fixVersion = "{version}" AND type = "sub test execution"'
    else:
        # For released versions, can skip or fetch all for historical view
        sub_exec_jql = f'project = DP AND fixVersion = "{version}" AND type = "sub test execution"'
    
    sub_execs = jira.search_issues(sub_exec_jql, maxResults=False)
    
    sub_exec_completed = sum(1 for se in sub_execs if hasattr(se.fields, 'status') and 'done' in se.fields.status.name.lower())
    sub_exec_in_progress = sum(1 for se in sub_execs if hasattr(se.fields, 'status') and 'in progress' in se.fields.status.name.lower())
    sub_exec_not_started = len(sub_execs) - sub_exec_completed - sub_exec_in_progress
    
    # Generate HTML report
    output_file = f"unified_weekly_report_{version.replace('.', '_')}.html"
    
    # Create automation charts by platform type + mode
    fig_automation = make_subplots(
        rows=1, cols=2,
        subplot_titles=('Test Coverage by Platform Type & Mode', 'Pass Ratio by Platform Type & Mode'),
        horizontal_spacing=0.12
    )
    
    if automation_data.get('platform_type_data'):
        pt_modes = [p['platform_type_mode'] for p in automation_data['platform_type_data']]
        coverages = [p['coverage'] for p in automation_data['platform_type_data']]
        pass_ratios = [p['pass_ratio'] for p in automation_data['platform_type_data']]
        
        # Sort by platform type and mode
        sorted_data = sorted(zip(pt_modes, coverages, pass_ratios), key=lambda x: x[0])
        pt_modes_sorted, coverages_sorted, pass_ratios_sorted = zip(*sorted_data) if sorted_data else ([], [], [])
        
        # Coverage chart
        fig_automation.add_trace(
            go.Bar(
                x=pt_modes_sorted,
                y=coverages_sorted,
                name='Coverage',
                marker_color='#2196F3',
                text=[f"{c:.1f}%" for c in coverages_sorted],
                textposition='outside',
                showlegend=False
            ),
            row=1, col=1
        )
        
        # Pass ratio chart
        fig_automation.add_trace(
            go.Bar(
                x=pt_modes_sorted,
                y=pass_ratios_sorted,
                name='Pass Ratio',
                marker_color='#4CAF50',
                text=[f"{p:.1f}%" for p in pass_ratios_sorted],
                textposition='outside',
                showlegend=False
            ),
            row=1, col=2
        )
        
        fig_automation.update_xaxes(title_text='Platform Type & Mode', row=1, col=1)
        fig_automation.update_xaxes(title_text='Platform Type & Mode', row=1, col=2)
        fig_automation.update_yaxes(title_text='Coverage (%)', range=[0, 105], row=1, col=1)
        fig_automation.update_yaxes(title_text='Pass Ratio (%)', range=[0, 105], row=1, col=2)
        
        fig_automation.update_layout(
            title_text=f'Automation Metrics ({sprint.name})',
            height=400,
            showlegend=False
        )
    
    # Create bug status chart
    fig_bugs = go.Figure()
    fig_bugs.add_trace(go.Bar(
        x=['Bugs on Dev', 'Bugs on QA', 'Closed'],
        y=[len(bugs_on_dev), len(bugs_on_qa), len(bugs_closed)],
        marker_color=['#ff9800', '#2196f3', '#4caf50'],
        text=[len(bugs_on_dev), len(bugs_on_qa), len(bugs_closed)],
        textposition='outside'
    ))
    fig_bugs.update_layout(
        title=f'Bug Status Distribution - {version}',
        xaxis_title='Status',
        yaxis_title='Count',
        height=400
    )
    
    # Generate HTML
    automation_chart_html = fig_automation.to_html(include_plotlyjs='inline', div_id='automation-chart', full_html=False) if automation_data['platform_data'] else ""
    bugs_chart_html = fig_bugs.to_html(include_plotlyjs='inline' if not automation_data['platform_data'] else False, div_id='bugs-chart', full_html=False)    
    # Generate insights
    insights = generate_insights(automation_data.get('platform_type_data', []), automation_data, sprint.name) if automation_data['total_tests'] > 0 else []    
    # Build platform type stats HTML
    platform_html = ""
    if automation_data.get('platform_type_data'):
        platform_html = '<h3>Platform Type & Mode Summary</h3>'
        platform_html += '<table><thead><tr><th>Platform Type & Mode</th><th>Tests Executed</th><th>Available Tests</th><th>Coverage</th><th>Executions</th><th>Passed</th><th>Failed</th><th>Pass Ratio</th></tr></thead><tbody>'
        sorted_pt_data = sorted(automation_data['platform_type_data'], key=lambda x: x['platform_type_mode'])
        for p in sorted_pt_data:
            coverage_class = 'priority-high' if p['coverage'] < 70 else 'priority-medium' if p['coverage'] < 90 else ''
            platform_html += f'<tr><td><strong>{p["platform_type_mode"]}</strong></td><td>{p["tests"]}</td><td>{p["available_tests"]}</td><td class="{coverage_class}">{p["coverage"]:.1f}%</td><td>{p["executions"]}</td><td>{p["passed"]}</td><td>{p["failed"]}</td><td>{p["pass_ratio"]:.1f}%</td></tr>'
        platform_html += '</tbody></table>'
        
        # Add detailed platform breakdown in collapsible section
        if automation_data.get('platform_data'):
            platform_html += '<details style="margin-top: 20px;"><summary style="cursor: pointer; font-weight: bold; color: #1976d2;">▶ View Individual Platform Details</summary>'
            platform_html += '<table style="margin-top: 10px;"><thead><tr><th>Platform</th><th>Tests</th><th>Passed</th><th>Failed</th><th>Pass Ratio</th></tr></thead><tbody>'
            for p in sorted(automation_data['platform_data'], key=lambda x: x['platform']):
                platform_html += f'<tr><td>{p["platform"]}</td><td>{p["tests"]}</td><td>{p["passed"]}</td><td>{p["failed"]}</td><td>{p["pass_ratio"]:.1f}%</td></tr>'
            platform_html += '</tbody></table></details>'
    
    # Add version status warning if released
    version_warning_html = ""
    if not version_info['is_active']:
        status_text = "RELEASED" if version_info['released'] else "ARCHIVED" if version_info['archived'] else "INACTIVE"
        version_warning_html = f'''<div class="alert-box" style="background-color: #fff3cd; border-left-color: #ffc107;">
            <strong>⚠️ Historical Version:</strong> Version {version} is marked as {status_text} in Jira.
            This report shows historical data. For current sprint work, use an active/unreleased version.
        </div>'''
    
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Unified Weekly Report - DefensePro {version}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background-color: white; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #1976d2; border-bottom: 3px solid #1976d2; padding-bottom: 10px; }}
        h2 {{ color: #424242; margin-top: 30px; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }}
        h3 {{ color: #616161; margin-top: 20px; }}
        .metadata {{ background-color: #e3f2fd; padding: 15px; border-left: 4px solid #1976d2; margin-bottom: 25px; }}
        .summary-box {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 25px 0; }}
        .metric-card {{ padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .metric-card.bugs {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }}
        .metric-card.automation {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; }}
        .metric-card.sub-exec {{ background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white; }}
        .metric-label {{ font-size: 14px; opacity: 0.9; margin-bottom: 8px; }}
        .metric-number {{ font-size: 36px; font-weight: bold; margin: 10px 0; }}
        .metric-detail {{ font-size: 13px; opacity: 0.9; margin-top: 8px; }}
        .chart-container {{ margin: 20px 0; padding: 15px; background-color: #fafafa; border-radius: 8px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        th {{ background-color: #1976d2; color: white; padding: 12px; text-align: left; font-weight: 600; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #e0e0e0; }}
        tr:hover {{ background-color: #f9f9f9; }}
        .priority-high {{ color: #d32f2f; font-weight: bold; }}
        .priority-medium {{ color: #f57c00; font-weight: bold; }}
        .priority-low {{ color: #0288d1; font-weight: bold; }}
        .section-title {{ font-size: 24px; color: #1976d2; margin: 30px 0 20px 0; font-weight: bold; }}
        .alert-box {{ background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }}
        .alert-box.info {{ background-color: #e3f2fd; border-left-color: #2196f3; }}
        .alert-box.danger {{ background-color: #ffebee; border-left-color: #f44336; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Unified Weekly Report - DefensePro {version}</h1>
        <div class="metadata">
            <strong>Sprint:</strong> {sprint.name}<br>
            <strong>Period:</strong> {sprint_start[:10]} to {sprint_end[:10]}<br>
            <strong>Version Status:</strong> {'✓ Active (Unreleased)' if version_info['is_active'] else '⚠️ Released/Archived'}<br>
            <strong>Report Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>

        {version_warning_html}

        <div class="summary-box">
            <div class="metric-card bugs">
                <div class="metric-label">Bug Status</div>
                <div class="metric-number">{len(bugs_on_dev) + len(bugs_on_qa)}</div>
                <div class="metric-detail">Open: Dev {len(bugs_on_dev)} | QA {len(bugs_on_qa)}<br>Closed: {len(bugs_closed)}</div>
            </div>
            <div class="metric-card automation">
                <div class="metric-label">Automation Tests</div>
                <div class="metric-number">{automation_data['total_tests']}</div>
                <div class="metric-detail">Executions: {automation_data['total_executions']}<br>Pass Ratio: {automation_data['pass_ratio']:.1f}%</div>
            </div>
            <div class="metric-card sub-exec">
                <div class="metric-label">Sub Test Executions</div>
                <div class="metric-number">{len(sub_execs)}</div>
                <div class="metric-detail">Completed: {sub_exec_completed}<br>In Progress: {sub_exec_in_progress} | Not Started: {sub_exec_not_started}</div>
            </div>
        </div>

        {'<div class="alert-box danger"><strong>⚠️ Critical Automation Failures:</strong> ' + str(automation_data["critical_failures"]) + ' tests failed on ALL platforms. Immediate investigation required.</div>' if automation_data.get('critical_failures', 0) > 0 else ''}
        {'<div class="alert-box" style="background-color: #fff3cd; border-left-color: #ffc107;"><strong>⚠️ Automation Bugs:</strong> ' + str(automation_data.get("automation_bugs_count", 0)) + ' bugs with automation origin opened during sprint - requires review.</div>' if automation_data.get("automation_bugs_count", 0) > 0 else ''}

        <div class="section-title">🤖 CI Iteration - Automation Status</div>
        <p><strong>Tests executed during sprint:</strong> {automation_data['total_tests']} unique tests, {automation_data['total_executions']} total executions</p>
        <p><strong>Overall results:</strong> Passed: {automation_data['passed']} | Failed: {automation_data['failed']} | Pass Ratio: {automation_data['pass_ratio']:.1f}%</p>
        {'<p><strong>Test Coverage:</strong> Overall: ' + f"{automation_data.get('overall_coverage', 0):.1f}%" + '</p>' if automation_data.get('overall_coverage', 0) > 0 else ''}
        
        {automation_chart_html}
        
        {('<h3>📊 Automated Insights</h3><ul>' + ''.join([f"<li>{insight}</li>" for insight in insights]) + '</ul>') if insights else ''}
        
        {platform_html}
        
        {('<h3>🐛 Automation Bugs During Sprint</h3><p>' + str(len(automation_data.get("automation_bugs", []))) + ' bugs with automation origin found during sprint period</p><table><thead><tr><th>Key</th><th>Summary</th><th>Status</th><th>Priority</th><th>Created</th></tr></thead><tbody>' + ''.join([f'<tr><td><a href="https://rwrnd.atlassian.net/browse/{bug["key"]}">{bug["key"]}</a></td><td>{bug["summary"]}</td><td>{bug["status"]}</td><td>{bug["priority"]}</td><td>{bug["created"]}</td></tr>' for bug in automation_data.get("automation_bugs", [])]) + '</tbody></table>') if automation_data.get("automation_bugs") else ''}

        <div class="section-title">🐛 Bug Status</div>
        {bugs_chart_html}

        <h2>Bugs on Dev ({len(bugs_on_dev)} bugs)</h2>
        <p>Status: In Progress, To-Do, or None (assigned but not started)</p>
        <table>
            <thead><tr><th>Key</th><th>Priority</th><th>Summary</th><th>Status</th></tr></thead>
            <tbody>
                {''.join([f'<tr><td><a href="https://rwrnd.atlassian.net/browse/{bug.key}" class="bug-key">{bug.key}</a></td><td>{bug.fields.priority.name if hasattr(bug.fields, "priority") and bug.fields.priority else "N/A"}</td><td>{bug.fields.summary}</td><td>{bug.fields.status.name}</td></tr>' for bug in bugs_on_dev[:20]]) if bugs_on_dev else '<tr><td colspan="4" style="text-align: center;">No bugs on Dev</td></tr>'}
            </tbody>
        </table>

        <h2>Bugs on QA ({len(bugs_on_qa)} bugs)</h2>
        <p>Status: Completed - awaiting QA verification</p>
        <table>
            <thead><tr><th>Key</th><th>Priority</th><th>Summary</th><th>Status</th></tr></thead>
            <tbody>
                {''.join([f'<tr><td><a href="https://rwrnd.atlassian.net/browse/{bug.key}" class="bug-key">{bug.key}</a></td><td>{bug.fields.priority.name if hasattr(bug.fields, "priority") and bug.fields.priority else "N/A"}</td><td>{bug.fields.summary}</td><td>{bug.fields.status.name}</td></tr>' for bug in bugs_on_qa[:20]]) if bugs_on_qa else '<tr><td colspan="4" style="text-align: center;">No bugs on QA</td></tr>'}
            </tbody>
        </table>

        <div class="section-title">🧪 Sub Test Execution Status</div>
        <p><strong>Total:</strong> {len(sub_execs)} | <strong>Completed:</strong> {sub_exec_completed} ({sub_exec_completed/max(len(sub_execs),1)*100:.1f}%) | <strong>In Progress:</strong> {sub_exec_in_progress} | <strong>Not Started:</strong> {sub_exec_not_started}</p>
        
        {'<div class="alert-box info"><strong>Status:</strong> All test executions completed ✓</div>' if len(sub_execs) > 0 and sub_exec_completed == len(sub_execs) else ''}
        {'<div class="alert-box"><strong>Status:</strong> ' + str(sub_exec_not_started) + ' test executions not started</div>' if sub_exec_not_started > 0 else ''}

        <div class="footer">
            <p>Generated from Jira Project: DP (DefensePro) | Version: {version}</p>
            <p><strong>Note:</strong> This is a READ-ONLY report. No Jira issues were created or modified during this analysis.</p>
        </div>
    </div>
</body>
</html>"""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✓ Report saved to {output_file}\n")
    
    # Print summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Bugs: {len(bugs_on_dev)} on Dev | {len(bugs_on_qa)} on QA | {len(bugs_closed)} closed")
    print(f"Automation: {automation_data['total_tests']} tests | {automation_data['pass_ratio']:.1f}% pass ratio")
    print(f"Critical Failures: {automation_data.get('critical_failures', 0)} tests failing on all platforms")
    print(f"Sub Test Executions: {sub_exec_completed}/{len(sub_execs)} completed")
    print("=" * 70)
    
    conn.close()

if __name__ == "__main__":
    main()
