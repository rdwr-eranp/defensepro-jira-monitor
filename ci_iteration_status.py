"""
CI Iteration Status Report Generator

This script generates a report for automation test results introduced during the current sprint.
Similar structure to release readiness report, but focused on new tests added in the current iteration.

The report includes:
- New tests introduced in current sprint
- Test execution results (pass/fail)
- Coverage by platform and mode
- Test status breakdown
- Build-level analysis
- Automated HTML report generation
"""

import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import os
from jira import JIRA
from dotenv import load_dotenv
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Load environment variables
load_dotenv()

def connect_to_jira():
    """Connect to Jira"""
    print("Connecting to Jira...")
    jira_url = os.getenv('JIRA_URL')
    jira_email = os.getenv('JIRA_EMAIL')
    jira_api_token = os.getenv('JIRA_API_TOKEN')
    
    options = {'server': jira_url, 'verify': False}
    jira = JIRA(options=options, basic_auth=(jira_email, jira_api_token))
    print("✓ Connected to Jira\n")
    return jira

def connect_to_postgres():
    """Connect to PostgreSQL database"""
    print("Connecting to PostgreSQL...")
    conn = psycopg2.connect(
        host=os.getenv('PG_HOST', '10.185.20.124'),
        port=os.getenv('PG_PORT', '5432'),
        database=os.getenv('PG_DATABASE', 'results'),
        user=os.getenv('PG_USER', 'postgres'),
        password=os.getenv('PG_PASSWORD', '')
    )
    print("✓ Connected to PostgreSQL\n")
    return conn

def get_current_sprint(jira, board_id=None):
    """Get current active sprint"""
    print("Fetching current sprint...")
    # Get active sprint from DP board
    if board_id is None:
        boards = jira.boards()
        # Find DP board
        for board in boards:
            if 'DP' in board.name or 'DefensePro' in board.name:
                board_id = board.id
                break
    
    if board_id:
        sprints = jira.sprints(board_id, state='active')
        if sprints:
            sprint = sprints[0]
            print(f"✓ Current sprint: {sprint.name}")
            print(f"  Start: {sprint.startDate}")
            print(f"  End: {sprint.endDate}\n")
            return sprint
    
    # Fallback: use last 2 weeks
    end_date = datetime.now()
    start_date = end_date - timedelta(weeks=2)
    print(f"✓ Using default 2-week window: {start_date.date()} to {end_date.date()}\n")
    
    class FakeSprint:
        def __init__(self):
            self.name = f"Current Iteration ({start_date.strftime('%b %d')} - {end_date.strftime('%b %d')})"
            self.startDate = start_date.isoformat()
            self.endDate = end_date.isoformat()
    
    return FakeSprint()

def get_bugs_opened_in_sprint(jira, sprint_start, sprint_end, version):
    """Get bugs opened during sprint period with automation origin"""
    print(f"Querying bugs opened during sprint with automation origin...")
    
    # Format dates for JQL (YYYY-MM-DD)
    start_date_str = sprint_start[:10]
    end_date_str = sprint_end[:10]
    
    # Query bugs created during sprint with automation origin
    jql = f"""
        project = DP 
        AND type = Bug 
        AND fixVersion = "{version}"
        AND created >= "{start_date_str}" 
        AND created <= "{end_date_str}"
        AND Origin in ("functional automation", "automation", "Functional Automation", "Automation")
        ORDER BY created DESC
    """
    
    bugs = []
    start_at = 0
    max_results = 100
    
    while True:
        issues = jira.search_issues(jql, startAt=start_at, maxResults=max_results)
        if not issues:
            break
        
        for issue in issues:
            bugs.append({
                'key': issue.key,
                'summary': issue.fields.summary,
                'status': issue.fields.status.name,
                'priority': issue.fields.priority.name if issue.fields.priority else 'None',
                'created': issue.fields.created[:10],
                'assignee': issue.fields.assignee.displayName if issue.fields.assignee else 'Unassigned',
                'origin': getattr(issue.fields, 'customfield_10047', 'Unknown') if hasattr(issue.fields, 'customfield_10047') else 'Unknown'
            })
        
        if len(issues) < max_results:
            break
        start_at += max_results
    
    print(f"✓ Found {len(bugs)} automation bugs opened in sprint\n")
    return pd.DataFrame(bugs)

def get_unique_failed_tests(conn, test_ids, version, builds, sprint_start, sprint_end):
    """Get unique test cases that failed on ALL platforms during sprint"""
    print(f"Analyzing tests that failed on ALL platforms...")
    
    builds_str = "', '".join(builds)
    test_ids_str = ", ".join(str(tid) for tid in test_ids)
    
    query = f"""
    WITH test_executions AS (
        -- Get all test executions during sprint period
        SELECT 
            te.test_id,
            t.name as test_name,
            t.class_name,
            d.platform,
            CASE 
                WHEN p.name LIKE '%-Routing' THEN 'Routing'
                ELSE 'Transparent'
            END as mode,
            te.status
        FROM test_execution te
        JOIN test t ON te.test_id = t.id
        JOIN device d ON te.device_id = d.id
        LEFT JOIN profile p ON te.profile_id = p.id
        WHERE te.version = '{version}'
            AND te.build IN ('{builds_str}')
            AND te.test_id IN ({test_ids_str})
            AND te.mode = 'regression'
            AND te.start_time BETWEEN '{sprint_start}' AND '{sprint_end}'
    ),
    test_platform_status AS (
        -- Get status per test per platform/mode
        SELECT 
            test_id,
            test_name,
            class_name,
            platform,
            mode,
            COUNT(*) as total_executions,
            SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) as failed_count,
            SUM(CASE WHEN status = 'Passed' THEN 1 ELSE 0 END) as passed_count
        FROM test_executions
        GROUP BY test_id, test_name, class_name, platform, mode
    ),
    tests_failed_everywhere AS (
        -- Find tests that failed on ALL platforms they were executed on
        SELECT 
            test_id,
            test_name,
            class_name,
            COUNT(DISTINCT platform) as platforms_count,
            SUM(CASE WHEN failed_count > 0 AND passed_count = 0 THEN 1 ELSE 0 END) as failed_platforms_count
        FROM test_platform_status
        GROUP BY test_id, test_name, class_name
        HAVING COUNT(DISTINCT platform) = SUM(CASE WHEN failed_count > 0 AND passed_count = 0 THEN 1 ELSE 0 END)
    )
    SELECT 
        tfe.test_id,
        tfe.test_name,
        tfe.class_name,
        tfe.platforms_count as failed_platforms_count,
        STRING_AGG(DISTINCT tps.platform || ' (' || tps.mode || ')', ', ' ORDER BY tps.platform || ' (' || tps.mode || ')') as platforms_failed
    FROM tests_failed_everywhere tfe
    JOIN test_platform_status tps ON tfe.test_id = tps.test_id
    GROUP BY tfe.test_id, tfe.test_name, tfe.class_name, tfe.platforms_count
    ORDER BY tfe.platforms_count DESC, tfe.test_name
    """
    
    df = pd.read_sql_query(query, conn)
    print(f"✓ Found {len(df)} tests that failed on ALL platforms they were executed on\n")
    return df

def get_tests_executed_in_sprint(conn, sprint_start, sprint_end, version):
    """Get all tests executed during the sprint period"""
    print(f"Querying test executions between {sprint_start} and {sprint_end}...")
    
    query = f"""
    WITH sprint_executions AS (
        SELECT DISTINCT te.test_id,
            MIN(te.start_time) as first_execution_in_sprint,
            MAX(te.start_time) as last_execution_in_sprint,
            COUNT(*) as execution_count
        FROM test_execution te
        WHERE te.start_time BETWEEN '{sprint_start}' AND '{sprint_end}'
            AND te.version = '{version}'
            AND te.mode = 'regression'
        GROUP BY te.test_id
    )
    SELECT 
        t.id as test_id,
        t.name as test_name,
        t.class_name,
        se.first_execution_in_sprint,
        se.last_execution_in_sprint,
        se.execution_count
    FROM sprint_executions se
    JOIN test t ON se.test_id = t.id
    ORDER BY se.execution_count DESC, t.class_name, t.name
    """
    
    df = pd.read_sql_query(query, conn)
    print(f"✓ Found {len(df)} tests executed in current sprint\n")
    return df

def get_test_execution_results(conn, test_ids, version, builds):
    """Get execution results for specific tests"""
    print(f"Fetching execution results for {len(test_ids)} tests...")
    
    builds_str = "', '".join(builds)
    test_ids_str = ", ".join(str(tid) for tid in test_ids)
    
    query = f"""
    WITH latest_executions AS (
        SELECT 
            te.test_id,
            t.name as test_name,
            t.class_name,
            d.platform,
            p.name as profile_name,
            CASE 
                WHEN p.name LIKE '%-Routing' THEN 'Routing'
                ELSE 'Transparent'
            END as mode,
            te.build,
            te.status,
            te.start_time,
            ROW_NUMBER() OVER (
                PARTITION BY te.test_id, d.platform, 
                    CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END
                ORDER BY te.start_time DESC
            ) as rn
        FROM test_execution te
        JOIN test t ON te.test_id = t.id
        JOIN device d ON te.device_id = d.id
        LEFT JOIN profile p ON te.profile_id = p.id
        WHERE te.version = '{version}'
            AND te.build IN ('{builds_str}')
            AND te.test_id IN ({test_ids_str})
            AND te.mode = 'regression'
    )
    SELECT 
        test_id,
        test_name,
        class_name,
        platform,
        mode,
        build,
        status,
        start_time
    FROM latest_executions
    WHERE rn = 1
    ORDER BY test_name, platform, mode
    """
    
    df = pd.read_sql_query(query, conn)
    
    print(f"✓ Retrieved {len(df)} test execution records\n")
    return df

def generate_insights(platform_type_agg, stats, total_tests):
    """Generate insights from aggregated platform type & mode data"""
    insights = []
    
    # Overall coverage insight
    total_executed = platform_type_agg['Tests Executed'].sum()
    total_available = platform_type_agg['available_tests'].sum()
    overall_coverage = (total_executed / total_available * 100) if total_available > 0 else 0
    
    if overall_coverage >= 90:
        insights.append(("✅", "Excellent Coverage", f"Sprint achieved {overall_coverage:.1f}% test coverage across all platforms, exceeding the 90% target."))
    elif overall_coverage >= 80:
        insights.append(("⚠️", "Good Coverage", f"Sprint achieved {overall_coverage:.1f}% test coverage across all platforms. Target is 90%."))
    else:
        insights.append(("❌", "Low Coverage", f"Sprint achieved only {overall_coverage:.1f}% test coverage across all platforms. Significant gap from 90% target."))
    
    # Overall pass ratio insight
    if stats['pass_ratio'] >= 90:
        insights.append(("✅", "High Quality", f"Pass ratio of {stats['pass_ratio']:.1f}% indicates stable test suite."))
    elif stats['pass_ratio'] >= 80:
        insights.append(("⚠️", "Moderate Quality", f"Pass ratio of {stats['pass_ratio']:.1f}% suggests some instability. Target is 90%."))
    else:
        insights.append(("❌", "Quality Issues", f"Pass ratio of {stats['pass_ratio']:.1f}% indicates significant test failures requiring attention."))
    
    # Platform type & mode specific insights
    low_coverage_types = platform_type_agg[platform_type_agg['Coverage %'] < 80]
    if len(low_coverage_types) > 0:
        types_list = ", ".join([f"{row['Type']} {row['Mode']}" for _, row in low_coverage_types.iterrows()])
        insights.append(("⚠️", "Coverage Gaps", f"Low coverage on: {types_list}"))
    
    low_quality_types = platform_type_agg[platform_type_agg['Pass Ratio %'] < 80]
    if len(low_quality_types) > 0:
        types_list = ", ".join([f"{row['Type']} {row['Mode']} ({row['Pass Ratio %']:.1f}%)" for _, row in low_quality_types.iterrows()])
        insights.append(("❌", "Quality Hotspots", f"High failure rates on: {types_list}"))
    
    # Mode comparison across platform types
    mode_comparison = platform_type_agg.groupby('Mode').agg({
        'Coverage %': 'mean',
        'Pass Ratio %': 'mean'
    }).round(2)
    
    if len(mode_comparison) > 1:
        routing_coverage = mode_comparison.loc['Routing', 'Coverage %'] if 'Routing' in mode_comparison.index else 0
        transparent_coverage = mode_comparison.loc['Transparent', 'Coverage %'] if 'Transparent' in mode_comparison.index else 0
        
        if abs(routing_coverage - transparent_coverage) > 10:
            if routing_coverage > transparent_coverage:
                insights.append(("ℹ️", "Mode Imbalance", f"Routing mode has {routing_coverage:.1f}% avg coverage vs Transparent {transparent_coverage:.1f}%"))
            else:
                insights.append(("ℹ️", "Mode Imbalance", f"Transparent mode has {transparent_coverage:.1f}% avg coverage vs Routing {routing_coverage:.1f}%"))
    
    # Best and worst performing platform types
    if len(platform_type_agg) > 0:
        best_coverage = platform_type_agg.loc[platform_type_agg['Coverage %'].idxmax()]
        worst_coverage = platform_type_agg.loc[platform_type_agg['Coverage %'].idxmin()]
        insights.append(("ℹ️", "Coverage Leaders", f"Best: {best_coverage['Type']} {best_coverage['Mode']} ({best_coverage['Coverage %']:.1f}%), Lowest: {worst_coverage['Type']} {worst_coverage['Mode']} ({worst_coverage['Coverage %']:.1f}%)"))
    
    return insights
    
    return insights

def calculate_statistics(df_executions):
    """Calculate overall statistics"""
    total_executions = len(df_executions)
    passed = len(df_executions[df_executions['status'] == 'Passed'])
    failed = len(df_executions[df_executions['status'] == 'Failed'])
    
    pass_ratio = (passed / total_executions * 100) if total_executions > 0 else 0
    
    unique_tests = df_executions['test_name'].nunique()
    platforms = df_executions['platform'].nunique()
    
    return {
        'total_executions': total_executions,
        'passed': passed,
        'failed': failed,
        'pass_ratio': pass_ratio,
        'unique_tests': unique_tests,
        'platforms': platforms
    }

def generate_html_report(sprint, sprint_tests, executions, stats, version, builds, total_tests, conn, sprint_start, sprint_end, bugs_df, failed_tests_df):
    """Generate HTML report"""
    
    # For each platform/mode, get available tests (tests that CAN run on that platform/mode)
    # This is based on what tests have EVER run on that platform/mode in this version or previous versions
    query_platform_available = f"""
    SELECT 
        d.platform,
        CASE 
            WHEN p.name LIKE '%-Routing' THEN 'Routing'
            ELSE 'Transparent'
        END as mode,
        COUNT(DISTINCT te.test_id) as available_tests
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    LEFT JOIN profile p ON te.profile_id = p.id
    WHERE te.version IN ('{version}', '10.11.0.0')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL
    GROUP BY d.platform, 
        CASE 
            WHEN p.name LIKE '%-Routing' THEN 'Routing'
            ELSE 'Transparent'
        END
    """
    
    df_available = pd.read_sql_query(query_platform_available, conn)
    
    # Group by platform and mode for executed tests
    platform_stats = executions.groupby(['platform', 'mode']).agg({
        'test_id': 'nunique',
        'status': lambda x: (x == 'Passed').sum()
    }).reset_index()
    platform_stats.columns = ['Platform', 'Mode', 'Tests Executed', 'Passed']
    platform_stats['Failed'] = platform_stats['Tests Executed'] - platform_stats['Passed']
    platform_stats['Pass Ratio %'] = (platform_stats['Passed'] / platform_stats['Tests Executed'] * 100).round(2)
    
    # Merge with available tests to calculate correct coverage
    platform_stats = platform_stats.merge(
        df_available.rename(columns={'platform': 'Platform', 'mode': 'Mode'}),
        on=['Platform', 'Mode'],
        how='left'
    )
    platform_stats['Coverage %'] = (platform_stats['Tests Executed'] / platform_stats['available_tests'] * 100).round(2)
    
    # Build platform summary table HTML
    platform_rows = ""
    for _, row in platform_stats.iterrows():
        coverage_color = '#00b050' if row['Coverage %'] >= 90 else '#ffc107' if row['Coverage %'] >= 80 else '#d32f2f'
        pass_ratio_color = '#00b050' if row['Pass Ratio %'] >= 90 else '#ffc107' if row['Pass Ratio %'] >= 80 else '#d32f2f'
        platform_rows += f"""
        <tr>
            <td>{row['Platform']}</td>
            <td>{row['Mode']}</td>
            <td>{row['Tests Executed']}</td>
            <td style="color: {coverage_color}; font-weight: bold;">{row['Coverage %']}%</td>
            <td>{row['Passed']}</td>
            <td>{row['Failed']}</td>
            <td style="color: {pass_ratio_color}; font-weight: bold;">{row['Pass Ratio %']}%</td>
        </tr>
        """
    
    # Create aggregated platform type & mode summary
    # Map platforms to types
    platform_type_map = {
        'UHT': 'FPGA', 'MRQP': 'FPGA', 'MR2': 'FPGA',
        'ESXI': 'Software', 'KVM': 'Software', 'VL3': 'Software', 'HT2': 'Software',
        'MRQ_X': 'EZchip'
    }
    
    # Add platform type column
    platform_stats['Type'] = platform_stats['Platform'].map(platform_type_map).fillna('Other')
    
    # Aggregate by type and mode
    platform_type_agg = platform_stats.groupby(['Type', 'Mode']).agg({
        'Tests Executed': 'sum',
        'available_tests': 'sum',
        'Passed': 'sum',
        'Failed': 'sum'
    }).reset_index()
    
    # Recalculate percentages
    platform_type_agg['Coverage %'] = (platform_type_agg['Tests Executed'] / platform_type_agg['available_tests'] * 100).round(2)
    platform_type_agg['Pass Ratio %'] = (platform_type_agg['Passed'] / platform_type_agg['Tests Executed'] * 100).round(2)
    
    # Build platform type summary table HTML
    platform_type_rows = ""
    for _, row in platform_type_agg.sort_values(['Type', 'Mode']).iterrows():
        coverage_color = '#00b050' if row['Coverage %'] >= 90 else '#ffc107' if row['Coverage %'] >= 80 else '#d32f2f'
        pass_ratio_color = '#00b050' if row['Pass Ratio %'] >= 90 else '#ffc107' if row['Pass Ratio %'] >= 80 else '#d32f2f'
        platform_type_label = f"{row['Type']} {row['Mode']}"
        platform_type_rows += f"""
        <tr>
            <td><strong>{platform_type_label}</strong></td>
            <td>{row['Tests Executed']}</td>
            <td style="color: {coverage_color}; font-weight: bold;">{row['Coverage %']}%</td>
            <td>{row['Passed']}</td>
            <td>{row['Failed']}</td>
            <td style="color: {pass_ratio_color}; font-weight: bold;">{row['Pass Ratio %']}%</td>
        </tr>
        """
    
    # Generate insights based on aggregated platform type & mode data
    insights = generate_insights(platform_type_agg, stats, total_tests)
    
    # Calculate overall coverage across all platforms
    total_executed_all_platforms = platform_stats['Tests Executed'].sum()
    total_available_all_platforms = platform_stats['available_tests'].sum()
    overall_coverage_pct = (total_executed_all_platforms / total_available_all_platforms * 100) if total_available_all_platforms > 0 else 0
    
    # Create bar chart using aggregated platform type & mode data
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=('Test Coverage by Platform Type & Mode', 'Pass Ratio by Platform Type & Mode'),
        specs=[[{'type': 'bar'}, {'type': 'bar'}]]
    )
    
    # Sort by type and mode for better visualization
    platform_type_sorted = platform_type_agg.sort_values(['Type', 'Mode'])
    
    # Create labels for x-axis (e.g., "FPGA Routing", "Software Transparent")
    x_labels = [f"{row['Type']}<br>{row['Mode']}" for _, row in platform_type_sorted.iterrows()]
    
    # Coverage bar chart
    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=platform_type_sorted['Coverage %'],
            name='Coverage %',
            marker_color=['#00b050' if x >= 90 else '#ffc107' if x >= 80 else '#d32f2f' 
                         for x in platform_type_sorted['Coverage %']],
            text=[f"{x:.1f}%" for x in platform_type_sorted['Coverage %']],
            textposition='auto',
            hovertemplate='<b>%{x}</b><br>Coverage: %{y:.1f}%<extra></extra>'
        ),
        row=1, col=1
    )
    
    # Pass Ratio bar chart
    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=platform_type_sorted['Pass Ratio %'],
            name='Pass Ratio %',
            marker_color=['#00b050' if x >= 90 else '#ffc107' if x >= 80 else '#d32f2f' 
                         for x in platform_type_sorted['Pass Ratio %']],
            text=[f"{x:.1f}%" for x in platform_type_sorted['Pass Ratio %']],
            textposition='auto',
            hovertemplate='<b>%{x}</b><br>Pass Ratio: %{y:.1f}%<extra></extra>'
        ),
        row=1, col=2
    )
    
    # Add target line at 90%
    for col in [1, 2]:
        fig.add_hline(y=90, line_dash="dash", line_color="green", 
                     annotation_text="Target: 90%", annotation_position="right",
                     row=1, col=col)
    
    # Update layout
    fig.update_layout(
        height=500,
        showlegend=False,
        title_text=f"Sprint Test Execution Analysis - {version}",
        title_x=0.5,
        title_font_size=18
    )
    
    fig.update_xaxes(title_text="Platform Type / Mode", row=1, col=1)
    fig.update_xaxes(title_text="Platform Type / Mode", row=1, col=2)
    fig.update_yaxes(title_text="Coverage %", range=[0, 100], row=1, col=1)
    fig.update_yaxes(title_text="Pass Ratio %", range=[0, 100], row=1, col=2)
    
    # Convert to HTML with inline JS
    chart_html = fig.to_html(include_plotlyjs='inline', div_id='sprint_chart')
    
    # Build insights HTML
    insights_html = ""
    for icon, title, description in insights:
        color = '#00b050' if icon == '✅' else '#ffc107' if icon == '⚠️' else '#d32f2f' if icon == '❌' else '#0070c0'
        insights_html += f"""
        <div style="display: flex; align-items: flex-start; margin-bottom: 15px; padding: 12px; background: #f9f9f9; border-left: 4px solid {color}; border-radius: 4px;">
            <div style="font-size: 24px; margin-right: 12px;">{icon}</div>
            <div>
                <div style="font-weight: bold; color: {color}; margin-bottom: 4px;">{title}</div>
                <div style="color: #333;">{description}</div>
            </div>
        </div>
        """
    
    # Build bugs table HTML
    bugs_table_html = ""
    if len(bugs_df) > 0:
        bugs_table_html = "<table><thead><tr>"
        bugs_table_html += "<th>Bug Key</th><th>Summary</th><th>Status</th><th>Priority</th><th>Created</th><th>Assignee</th>"
        bugs_table_html += "</tr></thead><tbody>"
        
        for _, bug in bugs_df.iterrows():
            status_color = '#00b050' if bug['status'] in ['Closed', 'Done', 'Accepted'] else '#ffc107' if bug['status'] == 'In Progress' else '#d32f2f'
            priority_color = '#d32f2f' if bug['priority'] in ['Critical', 'Highest'] else '#ffc107' if bug['priority'] == 'High' else '#666'
            bugs_table_html += f"""
            <tr>
                <td><a href="https://rwrnd.atlassian.net/browse/{bug['key']}" target="_blank" style="color: #0070c0; text-decoration: none;"><strong>{bug['key']}</strong></a></td>
                <td>{bug['summary']}</td>
                <td style="color: {status_color}; font-weight: bold;">{bug['status']}</td>
                <td style="color: {priority_color}; font-weight: bold;">{bug['priority']}</td>
                <td>{bug['created']}</td>
                <td>{bug['assignee']}</td>
            </tr>
            """
        bugs_table_html += "</tbody></table>"
    else:
        bugs_table_html = "<p style='color: #00b050; font-size: 16px;'>✓ No automation bugs were opened during this sprint period.</p>"
    
    # Build failed tests summary by feature
    failed_tests_html = ""
    if len(failed_tests_df) > 0:
        # Extract feature from test name (text before first "|") or class name
        failed_tests_df['feature'] = failed_tests_df['test_name'].apply(
            lambda x: x.split('|')[0].strip() if '|' in x else x.split()[0] if ' ' in x else 'Other'
        )
        
        # Group by feature
        feature_summary = failed_tests_df.groupby('feature').agg({
            'test_id': 'count',
            'failed_platforms_count': 'mean'
        }).reset_index()
        feature_summary.columns = ['Feature', 'Failed Tests Count', 'Avg Platforms Failed']
        feature_summary = feature_summary.sort_values('Failed Tests Count', ascending=False)
        
        # Build feature summary table
        failed_tests_html = "<table><thead><tr>"
        failed_tests_html += "<th>Feature / Component</th><th>Failed Tests</th><th>Avg Platforms Failed</th>"
        failed_tests_html += "</tr></thead><tbody>"
        
        for _, feature in feature_summary.iterrows():
            count_color = '#d32f2f' if feature['Failed Tests Count'] >= 10 else '#ffc107' if feature['Failed Tests Count'] >= 5 else '#666'
            failed_tests_html += f"""
            <tr>
                <td><strong>{feature['Feature']}</strong></td>
                <td style="color: {count_color}; font-weight: bold; text-align: center;">{int(feature['Failed Tests Count'])}</td>
                <td style="text-align: center;">{feature['Avg Platforms Failed']:.1f}</td>
            </tr>
            """
        failed_tests_html += "</tbody></table>"
        failed_tests_html += f"<p style='color: #666; font-size: 13px; margin-top: 10px;'><em>Detailed test-level data available in CSV export: ci_iteration_status_failed_tests_{version.replace('.', '_')}.csv</em></p>"
    else:
        failed_tests_html = "<p style='color: #00b050; font-size: 16px;'>✓ No test failures found during this sprint period.</p>"
    
    builds_display = ", ".join(builds)
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CI Iteration Status - {sprint.name}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background-color: white; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); border-radius: 8px; }}
        h1 {{ color: #003366; border-bottom: 3px solid #0070c0; padding-bottom: 10px; }}
        h2 {{ color: #0070c0; margin-top: 30px; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }}
        .metadata {{ color: #666; font-size: 14px; margin-bottom: 20px; background: #f9f9f9; padding: 15px; border-radius: 5px; }}
        .summary-box {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }}
        .metric-card {{ padding: 20px; border-radius: 8px; text-align: center; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        .metric-card.tests {{ background: linear-gradient(135deg, #0070c0 0%, #3399dd 100%); color: white; }}
        .metric-card.passed {{ background: linear-gradient(135deg, #00b050 0%, #4cd964 100%); color: white; }}
        .metric-card.failed {{ background: linear-gradient(135deg, #d32f2f 0%, #ff5252 100%); color: white; }}
        .metric-number {{ font-size: 42px; font-weight: bold; margin: 10px 0; }}
        .metric-label {{ font-size: 16px; font-weight: 500; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        th {{ background-color: #003366; color: white; padding: 12px; text-align: left; font-weight: 600; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #e0e0e0; }}
        tr:hover {{ background-color: #f9f9f9; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>CI Iteration Status Report</h1>
        <div class="metadata">
            <strong>Sprint:</strong> {sprint.name}<br>
            <strong>Sprint Period:</strong> {sprint.startDate[:10]} to {sprint.endDate[:10]}<br>
            <strong>Version:</strong> {version}<br>
            <strong>Builds:</strong> {builds_display}<br>
            <strong>Report Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>

        <div class="summary-box">
            <div class="metric-card tests">
                <div class="metric-label">Tests Executed in Sprint</div>
                <div class="metric-number">{stats['unique_tests']}</div>
                <div style="font-size: 14px; margin-top: 10px;">{total_executed_all_platforms} total across platforms ({overall_coverage_pct:.1f}% coverage)</div>
            </div>
            <div class="metric-card passed">
                <div class="metric-label">Tests Passed</div>
                <div class="metric-number">{stats['passed']}</div>
                <div style="font-size: 14px; margin-top: 10px;">{stats['pass_ratio']:.1f}% pass ratio</div>
            </div>
            <div class="metric-card failed">
                <div class="metric-label">Tests Failed</div>
                <div class="metric-number">{stats['failed']}</div>
                <div style="font-size: 14px; margin-top: 10px;">{stats['platforms']} platforms tested</div>
            </div>
        </div>

        <h2>Platform & Mode Summary</h2>
        <table>
            <thead>
                <tr>
                    <th>Platform</th>
                    <th>Mode</th>
                    <th>Tests Executed</th>
                    <th>Coverage</th>
                    <th>Passed</th>
                    <th>Failed</th>
                    <th>Pass Ratio</th>
                </tr>
            </thead>
            <tbody>
                {platform_rows}
            </tbody>
        </table>

        <h2>Platform Type & Mode Summary</h2>
        <table>
            <thead>
                <tr>
                    <th>Platform Type & Mode</th>
                    <th>Tests Executed</th>
                    <th>Coverage</th>
                    <th>Passed</th>
                    <th>Failed</th>
                    <th>Pass Ratio</th>
                </tr>
            </thead>
            <tbody>
                {platform_type_rows}
            </tbody>
        </table>

        <h2>Key Insights</h2>
        {insights_html}

        <h2>Visual Analysis</h2>
        {chart_html}

        <h2>🐛 Automation Bugs Opened in Sprint</h2>
        <p><strong>Total Bugs:</strong> {len(bugs_df)} bugs opened during sprint with automation origin</p>
        {bugs_table_html}

        <h2>❌ Tests That Failed on ALL Platforms</h2>
        <p><strong>Total:</strong> {len(failed_tests_df)} tests failed on ALL platforms they were executed on</p>
        <p style="color: #d32f2f; font-size: 14px;"><strong>Note:</strong> These tests had 0% pass rate across all platforms - indicating potential product issues or test infrastructure problems requiring immediate attention.</p>
        {failed_tests_html}

        <div class="footer">
            <p>Generated from PostgreSQL Database (10.185.20.124) | Version: {version}</p>
            <p><strong>Note:</strong> This report tracks all test executions that occurred during the current sprint period.</p>
        </div>
    </div>
</body>
</html>"""
    
    filename = f"ci_iteration_status_{version.replace('.', '_')}.html"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✓ Report saved to {filename}")
    
    # Save bugs data to CSV
    if len(bugs_df) > 0:
        bugs_csv_filename = f"ci_iteration_status_bugs_{version.replace('.', '_')}.csv"
        bugs_df.to_csv(bugs_csv_filename, index=False)
        print(f"✓ Bugs data saved to {bugs_csv_filename}")
    
    # Save failed tests data to CSV
    if len(failed_tests_df) > 0:
        failed_tests_csv_filename = f"ci_iteration_status_failed_tests_{version.replace('.', '_')}.csv"
        failed_tests_df.to_csv(failed_tests_csv_filename, index=False)
        print(f"✓ Failed tests data saved to {failed_tests_csv_filename}")
    
    return filename

def main():
    """Main execution"""
    print("=" * 70)
    print("CI ITERATION STATUS REPORT")
    print("=" * 70)
    print()
    
    # Get version from environment or prompt
    version = os.getenv('VERSION') or input("Version (e.g., 10.13.0.0) [default: 10.13.0.0]: ").strip() or "10.13.0.0"
    print(f"✓ Version: {version}\n")
    
    # Get builds
    builds_input = input("Builds (comma-separated, e.g., 1,2,3) [default: last 10]: ").strip()
    if builds_input:
        builds = [b.strip() for b in builds_input.split(',')]
    else:
        builds = [str(i) for i in range(1, 11)]  # Default last 10 builds
    print(f"✓ Builds: {', '.join(builds)}\n")
    
    try:
        # Connect to services
        jira = connect_to_jira()
        conn = connect_to_postgres()
        
        # Get current sprint
        sprint = get_current_sprint(jira)
        sprint_start = sprint.startDate[:10]
        sprint_end = sprint.endDate[:10]
        
        # Get tests executed in sprint
        sprint_tests = get_tests_executed_in_sprint(conn, sprint_start, sprint_end, version)
        
        if len(sprint_tests) == 0:
            print("⚠️  No test executions found in current sprint")
            conn.close()
            return
        
        # Get bugs opened during sprint with automation origin
        bugs_df = get_bugs_opened_in_sprint(jira, sprint.startDate, sprint.endDate, version)
        
        # Get execution results for tests
        test_ids = sprint_tests['test_id'].tolist()
        executions = get_test_execution_results(conn, test_ids, version, builds)
        
        # Get unique failed tests across platforms
        failed_tests_df = get_unique_failed_tests(conn, test_ids, version, builds, sprint_start, sprint_end)
        
        # Calculate statistics
        stats = calculate_statistics(executions)
        
        # Get total available tests for coverage calculation
        query_total = f"""
        SELECT COUNT(DISTINCT test_id) as total
        FROM test_execution
        WHERE version IN ('{version}', '10.11.0.0')
            AND mode = 'regression'
        """
        df_total = pd.read_sql_query(query_total, conn)
        total_tests = df_total['total'][0] if not df_total.empty else stats['unique_tests']
        
        # Generate report
        print("\nGenerating HTML report...")
        filename = generate_html_report(sprint, sprint_tests, executions, stats, version, builds, total_tests, conn, sprint_start, sprint_end, bugs_df, failed_tests_df)
        
        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Sprint: {sprint.name}")
        print(f"Tests Executed: {stats['unique_tests']}")
        print(f"Total Executions: {stats['total_executions']}")
        print(f"Passed: {stats['passed']} ({stats['pass_ratio']:.1f}%)")
        print(f"Failed: {stats['failed']}")
        print(f"Platforms: {stats['platforms']}")
        print(f"\n✓ Report: {filename}")
        
        conn.close()
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
