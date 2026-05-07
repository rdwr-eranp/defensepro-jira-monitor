"""
CI Automation Test Result Report - DefensePro 10.14.0.0
Date: 2026-05-03

Generates an HTML report of automation test results for version 10.14.0.0
for tests executed on 2026-05-03, similar to the CI Iteration section
in the weekly report.
"""

import os
import html
from datetime import datetime
import psycopg2
import pandas as pd
from dotenv import load_dotenv
from jira import JIRA
import plotly.graph_objects as go
from plotly.subplots import make_subplots

load_dotenv()

VERSION = '10.14.0.0'
PREV_VERSION = '10.13.0.0'
DATE_FROM = '2026-05-03'
DATE_TO = '2026-05-07'
DATE_START = '2026-05-03 00:00:00'
DATE_END = '2026-05-07 23:59:59'

PLATFORM_TYPE_MAP = {
    'UHT': 'FPGA', 'MRQP': 'FPGA', 'MR2': 'FPGA',
    'ESXI': 'Software', 'KVM': 'Software', 'VL3': 'Software', 'HT2': 'Software',
    'MRQ_X': 'EZchip', 'MRQX': 'EZchip'
}


def connect_to_jira():
    jira_url = os.getenv('JIRA_URL')
    jira_email = os.getenv('JIRA_EMAIL')
    jira_api_token = os.getenv('JIRA_API_TOKEN')
    options = {'server': jira_url, 'verify': False}
    return JIRA(options=options, basic_auth=(jira_email, jira_api_token))


def connect_to_postgres():
    return psycopg2.connect(
        host=os.getenv('PG_HOST', '10.185.20.124'),
        port=os.getenv('PG_PORT', '5432'),
        database=os.getenv('PG_DATABASE', 'results'),
        user=os.getenv('PG_USER', 'postgres'),
        password=os.getenv('PG_PASSWORD', '')
    )


def get_automation_data(conn, jira):
    """Get automation test data for the report date range"""
    print(f"Querying test executions from {DATE_FROM} to {DATE_TO}...")

    # Get tests executed on the date
    tests_query = f"""
        SELECT DISTINCT te.test_id
        FROM test_execution te
        JOIN test t2 ON te.test_id = t2.id
        WHERE te.version = '{VERSION}'
          AND te.start_time BETWEEN '{DATE_START}' AND '{DATE_END}'
          AND te.mode = 'regression'
          AND LOWER(t2.name) NOT LIKE '%qdos%'
    """
    tests_df = pd.read_sql(tests_query, conn)
    test_ids = tests_df['test_id'].tolist()
    print(f"✓ Found {len(test_ids)} unique tests executed from {DATE_FROM} to {DATE_TO}")

    if not test_ids:
        print("⚠️ No test executions found!")
        return None

    test_ids_str = ','.join([str(tid) for tid in test_ids])

    # Get builds used on this date
    builds_query = f"""
        SELECT DISTINCT te.build
        FROM test_execution te
        WHERE te.version = '{VERSION}'
          AND te.start_time BETWEEN '{DATE_START}' AND '{DATE_END}'
          AND te.mode = 'regression'
        ORDER BY te.build
    """
    builds_df = pd.read_sql(builds_query, conn)
    builds = builds_df['build'].tolist()
    builds_str = ','.join([str(b) for b in builds])
    print(f"✓ Builds: {builds_str}")

    # Get execution results (latest per test/platform/mode)
    exec_query = f"""
        WITH latest_execution AS (
            SELECT 
                te.test_id,
                t.name as test_name,
                d.platform,
                te.status,
                te.build,
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
              AND te.version = '{VERSION}'
              AND te.build IN ({builds_str})
              AND te.mode = 'regression'
              AND te.start_time BETWEEN '{DATE_START}' AND '{DATE_END}'
              AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
              AND LOWER(t.name) NOT LIKE '%qdos%'
        )
        SELECT test_id, test_name, platform, status, build, mode
        FROM latest_execution
        WHERE rn = 1
    """
    executions_df = pd.read_sql(exec_query, conn)
    executions_df['status_lower'] = executions_df['status'].str.lower()
    executions_df['platform_type'] = executions_df['platform'].map(PLATFORM_TYPE_MAP)
    executions_df['platform_type_mode'] = executions_df['platform_type'] + ' - ' + executions_df['mode']

    # Deduplicate per (test_id, platform_type, mode)
    pt_dedup_df = (
        executions_df
        .sort_values('build', ascending=False)
        .drop_duplicates(subset=['test_id', 'platform_type', 'mode'])
    )

    # Baseline from previous version
    baseline_ids_query = f"""
        SELECT DISTINCT te.test_id
        FROM test_execution te
        WHERE te.version = '{PREV_VERSION}'
          AND te.mode = 'regression'
    """
    baseline_ids_df = pd.read_sql(baseline_ids_query, conn)
    baseline_test_ids = set(baseline_ids_df['test_id'].tolist())

    pt_dedup_df = pt_dedup_df.copy()
    pt_dedup_df['is_new_test'] = ~pt_dedup_df['test_id'].isin(baseline_test_ids)
    legacy_pt_dedup_df = pt_dedup_df[~pt_dedup_df['is_new_test']]
    new_pt_dedup_df = pt_dedup_df[pt_dedup_df['is_new_test']]

    # Available tests from previous version
    available_tests_query = f"""
        SELECT 
               CASE 
                   WHEN d.platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
                   WHEN d.platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
                   WHEN d.platform IN ('MRQ_X', 'MRQX') THEN 'EZchip'
                   ELSE 'Other'
               END as platform_type,
               CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END as mode,
               COUNT(DISTINCT te.test_id) as available_tests
        FROM test_execution te
        JOIN device d ON te.device_id = d.id
        JOIN profile p ON te.profile_id = p.id
        JOIN test t ON te.test_id = t.id
        WHERE te.version = '{PREV_VERSION}'
          AND te.mode = 'regression'
          AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
          AND LOWER(t.name) NOT LIKE '%qdos%'
        GROUP BY 1, 2
    """
    available_df = pd.read_sql(available_tests_query, conn)
    available_df['platform_type_mode'] = available_df['platform_type'] + ' - ' + available_df['mode']

    # Platform Type + Mode breakdown
    all_platform_types = ['EZchip', 'FPGA', 'Software']
    all_modes = ['Routing', 'Transparent']
    all_combinations = [f"{pt} - {mode}" for pt in all_platform_types for mode in all_modes]

    platform_type_stats = []
    for pt_mode in all_combinations:
        if len(legacy_pt_dedup_df) > 0 and pt_mode in legacy_pt_dedup_df['platform_type_mode'].values:
            pt_df = legacy_pt_dedup_df[legacy_pt_dedup_df['platform_type_mode'] == pt_mode]
            passed_count = len(pt_df[pt_df['status_lower'] == 'passed'])
            failed_count = len(pt_df[pt_df['status_lower'].isin(['failed', 'error', 'fail'])])
            unique_tests = len(pt_df)
        else:
            passed_count = 0
            failed_count = 0
            unique_tests = 0

        if len(new_pt_dedup_df) > 0 and pt_mode in new_pt_dedup_df['platform_type_mode'].values:
            pt_new_df = new_pt_dedup_df[new_pt_dedup_df['platform_type_mode'] == pt_mode]
            new_tests_count = len(pt_new_df)
            new_tests_passed = len(pt_new_df[pt_new_df['status_lower'] == 'passed'])
            new_tests_failed = len(pt_new_df[pt_new_df['status_lower'].isin(['failed', 'error', 'fail'])])
        else:
            new_tests_count = 0
            new_tests_passed = 0
            new_tests_failed = 0

        available_tests = available_df[available_df['platform_type_mode'] == pt_mode]['available_tests'].sum()
        coverage = min((unique_tests / max(available_tests, 1)) * 100, 100.0) if available_tests > 0 else 0

        platform_type_stats.append({
            'platform_type_mode': pt_mode,
            'tests': unique_tests,
            'available_tests': int(available_tests),
            'coverage': coverage,
            'passed': passed_count,
            'failed': failed_count,
            'pass_ratio': passed_count / max(unique_tests, 1) * 100 if unique_tests > 0 else 0,
            'new_tests': new_tests_count,
            'new_tests_passed': new_tests_passed,
            'new_tests_failed': new_tests_failed,
        })

    # Overall stats
    total_tests = len(test_ids)
    total_executions = len(executions_df)
    passed = len(executions_df[executions_df['status_lower'] == 'passed'])
    failed = len(executions_df[executions_df['status_lower'].isin(['failed', 'error', 'fail'])])
    pass_ratio = passed / max(total_executions, 1) * 100

    total_executed_pt = sum(p['tests'] for p in platform_type_stats)
    total_available_pt = sum(p['available_tests'] for p in platform_type_stats)
    overall_coverage = min((total_executed_pt / max(total_available_pt, 1)) * 100, 100.0)

    # Failed on all platforms
    failed_all_query = f"""
        WITH test_executions AS (
            SELECT 
                te.test_id, t.name as test_name, d.platform,
                CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END as mode,
                LOWER(te.status) as status
            FROM test_execution te
            JOIN device d ON te.device_id = d.id
            JOIN profile p ON te.profile_id = p.id
            JOIN test t ON te.test_id = t.id
            WHERE te.test_id IN ({test_ids_str})
              AND te.version = '{VERSION}'
              AND te.build IN ({builds_str})
              AND te.mode = 'regression'
              AND te.start_time BETWEEN '{DATE_START}' AND '{DATE_END}'
              AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
              AND LOWER(t.name) NOT LIKE '%qdos%'
        ),
        test_platform_status AS (
            SELECT test_id, test_name, platform, mode,
                COUNT(CASE WHEN status IN ('failed','error','fail') THEN 1 END) as failed_count,
                COUNT(CASE WHEN status = 'passed' THEN 1 END) as passed_count
            FROM test_executions
            GROUP BY test_id, test_name, platform, mode
        ),
        tests_failed_everywhere AS (
            SELECT test_id, test_name,
                COUNT(DISTINCT platform) as platforms_count,
                SUM(CASE WHEN failed_count > 0 AND passed_count = 0 THEN 1 ELSE 0 END) as failed_platforms_count
            FROM test_platform_status
            GROUP BY test_id, test_name
            HAVING COUNT(DISTINCT platform) = SUM(CASE WHEN failed_count > 0 AND passed_count = 0 THEN 1 ELSE 0 END)
        )
        SELECT test_id, test_name, platforms_count
        FROM tests_failed_everywhere
        ORDER BY platforms_count DESC, test_name
    """
    failed_all_df = pd.read_sql(failed_all_query, conn)

    # Automation bugs for the date
    try:
        jql = f"""
            project = DP AND type = Bug AND fixVersion = "{VERSION}"
            AND created >= "{DATE_FROM}" AND created <= "{DATE_TO}"
            AND status != Trash
            AND Origin in ("functional automation", "automation", "Functional Automation", "Automation")
        """
        automation_bugs = jira.search_issues(jql, maxResults=100)
        bugs_list = [{
            'key': bug.key,
            'summary': bug.fields.summary,
            'status': bug.fields.status.name,
            'priority': bug.fields.priority.name if bug.fields.priority else 'N/A',
        } for bug in automation_bugs]
    except Exception as e:
        print(f"⚠️ Could not fetch automation bugs: {e}")
        bugs_list = []

    return {
        'total_tests': total_tests,
        'total_executions': total_executions,
        'passed': passed,
        'failed': failed,
        'pass_ratio': pass_ratio,
        'overall_coverage': overall_coverage,
        'platform_type_data': platform_type_stats,
        'new_tests_total': sum(p['new_tests'] for p in platform_type_stats),
        'builds': builds_str,
        'critical_failures': len(failed_all_df),
        'failed_tests': failed_all_df.to_dict('records'),
        'automation_bugs': bugs_list,
    }


def generate_html_report(data):
    """Generate HTML report"""

    # Build platform type table
    pt_rows = ""
    for pt in data['platform_type_data']:
        cov_color = '#1565c0' if pt['coverage'] >= 90 else '#1976d2' if pt['coverage'] >= 70 else '#42a5f5'
        pr_color = '#4caf50' if pt['pass_ratio'] >= 90 else '#ff9800' if pt['pass_ratio'] >= 70 else '#f44336'
        new_info = f" (+{pt['new_tests']} new)" if pt['new_tests'] > 0 else ""
        pt_rows += f"""
        <tr>
            <td><strong>{pt['platform_type_mode']}</strong></td>
            <td style="text-align:center;">{pt['tests']}{new_info}</td>
            <td style="text-align:center;">{pt['available_tests']}</td>
            <td style="text-align:center; color:{cov_color}; font-weight:bold;">{pt['coverage']:.1f}%</td>
            <td style="text-align:center;">{pt['passed']}</td>
            <td style="text-align:center;">{pt['failed']}</td>
            <td style="text-align:center; color:{pr_color}; font-weight:bold;">{pt['pass_ratio']:.1f}%</td>
        </tr>"""

    # Chart
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=('Test Coverage by Platform Type & Mode', 'Pass Ratio by Platform Type & Mode'),
    )

    labels = [pt['platform_type_mode'] for pt in data['platform_type_data']]
    coverages = [pt['coverage'] for pt in data['platform_type_data']]
    pass_ratios = [pt['pass_ratio'] for pt in data['platform_type_data']]

    fig.add_trace(go.Bar(
        x=labels, y=coverages, name='Coverage %',
        marker_color=['#1565c0' if x >= 90 else '#1976d2' if x >= 70 else '#42a5f5' for x in coverages],
        text=[f"{x:.1f}%" for x in coverages], textposition='auto',
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=labels, y=pass_ratios, name='Pass Ratio %',
        marker_color=['#4caf50' if x >= 90 else '#ff9800' if x >= 70 else '#f44336' for x in pass_ratios],
        text=[f"{x:.1f}%" for x in pass_ratios], textposition='auto',
    ), row=1, col=2)

    for col in [1, 2]:
        fig.add_hline(y=90, line_dash="dash", line_color="green",
                      annotation_text="Target: 90%", row=1, col=col)

    fig.update_layout(height=450, showlegend=False,
                      title_text=f"CI Automation Results - {VERSION} ({DATE_FROM} to {DATE_TO})", title_x=0.5)
    fig.update_yaxes(range=[0, 105], row=1, col=1)
    fig.update_yaxes(range=[0, 105], row=1, col=2)

    chart_html = fig.to_html(include_plotlyjs='cdn', div_id='chart', full_html=False)

    # Failed tests table
    failed_html = ""
    if data['failed_tests']:
        failed_html = "<table><thead><tr><th>Test Name</th><th>Platforms Failed</th></tr></thead><tbody>"
        for t in data['failed_tests'][:30]:
            failed_html += f"<tr><td>{html.escape(t['test_name'])}</td><td style='text-align:center;'>{t['platforms_count']}</td></tr>"
        failed_html += "</tbody></table>"
        if len(data['failed_tests']) > 30:
            failed_html += f"<p><em>...and {len(data['failed_tests']) - 30} more</em></p>"
    else:
        failed_html = "<p style='color:#4caf50;'>✓ No tests failed on ALL platforms.</p>"

    # Bugs table
    bugs_html = ""
    if data['automation_bugs']:
        bugs_html = "<table><thead><tr><th>Key</th><th>Summary</th><th>Status</th><th>Priority</th></tr></thead><tbody>"
        for bug in data['automation_bugs']:
            bugs_html += f"<tr><td><a href='https://rwrnd.atlassian.net/browse/{bug['key']}'>{bug['key']}</a></td><td>{html.escape(bug['summary'])}</td><td>{html.escape(bug['status'])}</td><td>{html.escape(bug['priority'])}</td></tr>"
        bugs_html += "</tbody></table>"
    else:
        bugs_html = "<p style='color:#4caf50;'>✓ No automation bugs opened in this period.</p>"

    # Overall pass ratio color
    pr_color = '#4caf50' if data['pass_ratio'] >= 90 else '#ff9800' if data['pass_ratio'] >= 70 else '#f44336'
    cov_color = '#1565c0' if data['overall_coverage'] >= 90 else '#1976d2' if data['overall_coverage'] >= 70 else '#42a5f5'

    report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>CI Automation Report - {VERSION} - {DATE_FROM} to {DATE_TO}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); border-radius: 8px; }}
        h1 {{ color: #003366; border-bottom: 3px solid #0070c0; padding-bottom: 10px; }}
        h2 {{ color: #0070c0; margin-top: 30px; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }}
        .metadata {{ color: #666; font-size: 14px; margin-bottom: 20px; background: #f9f9f9; padding: 15px; border-radius: 5px; }}
        .summary-box {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }}
        .metric-card {{ padding: 20px; border-radius: 8px; text-align: center; box-shadow: 0 2px 5px rgba(0,0,0,0.1); color: white; }}
        .metric-number {{ font-size: 42px; font-weight: bold; margin: 10px 0; }}
        .metric-label {{ font-size: 16px; font-weight: 500; }}
        .metric-detail {{ font-size: 13px; margin-top: 8px; opacity: 0.9; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th {{ background-color: #003366; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #e0e0e0; }}
        tr:hover {{ background-color: #f9f9f9; }}
        .alert {{ background: #fff3cd; border-left: 5px solid #ffc107; padding: 15px; margin: 15px 0; border-radius: 4px; }}
        .alert-danger {{ background: #f8d7da; border-left-color: #dc3545; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
<div class="container">
    <h1>🤖 CI Automation Test Results Report</h1>
    <div class="metadata">
        <strong>Version:</strong> {VERSION}<br>
        <strong>Period:</strong> {DATE_FROM} to {DATE_TO}<br>
        <strong>Builds:</strong> {data['builds']}<br>
        <strong>Baseline (Coverage):</strong> {PREV_VERSION}<br>
        <strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>

    <div class="summary-box">
        <div class="metric-card" style="background: linear-gradient(135deg, #0070c0, #3399dd);">
            <div class="metric-label">Unique Tests Executed</div>
            <div class="metric-number">{data['total_tests']}</div>
            <div class="metric-detail">{data['total_executions']} total executions across platforms</div>
        </div>
        <div class="metric-card" style="background: linear-gradient(135deg, {cov_color}, {cov_color}dd);">
            <div class="metric-label">Overall Coverage</div>
            <div class="metric-number">{data['overall_coverage']:.1f}%</div>
            <div class="metric-detail">vs {PREV_VERSION} baseline</div>
        </div>
        <div class="metric-card" style="background: linear-gradient(135deg, #4caf50, #66bb6a);">
            <div class="metric-label">Passed</div>
            <div class="metric-number">{data['passed']}</div>
            <div class="metric-detail">{data['pass_ratio']:.1f}% pass ratio</div>
        </div>
        <div class="metric-card" style="background: linear-gradient(135deg, #f44336, #ef5350);">
            <div class="metric-label">Failed</div>
            <div class="metric-number">{data['failed']}</div>
            <div class="metric-detail">{data['critical_failures']} failed on ALL platforms</div>
        </div>
    </div>

    {'<div class="alert alert-danger"><strong>⚠️ Critical:</strong> ' + str(data["critical_failures"]) + ' tests failed on ALL platforms.</div>' if data['critical_failures'] > 0 else ''}
    {'<div class="alert"><strong>🐛 Automation Bugs:</strong> ' + str(len(data["automation_bugs"])) + ' bugs with automation origin opened in this period.</div>' if data['automation_bugs'] else ''}

    {('<div class="alert" style="background:#e8f5e9; border-left-color:#4caf50;"><strong>🆕 New Tests:</strong> ' + str(data["new_tests_total"]) + ' new tests (not in ' + PREV_VERSION + ' baseline) executed.</div>') if data['new_tests_total'] > 0 else ''}

    <h2>Platform Type & Mode Breakdown</h2>
    <p>Coverage calculated against {PREV_VERSION} baseline. New tests shown separately.</p>
    <table>
        <thead>
            <tr>
                <th>Platform Type - Mode</th>
                <th>Tests Executed</th>
                <th>Available (Baseline)</th>
                <th>Coverage</th>
                <th>Passed</th>
                <th>Failed</th>
                <th>Pass Ratio</th>
            </tr>
        </thead>
        <tbody>
            {pt_rows}
        </tbody>
    </table>

    <h2>Visual Analysis</h2>
    {chart_html}

    <h2>❌ Tests Failed on ALL Platforms ({data['critical_failures']})</h2>
    {failed_html}

    <h2>🐛 Automation Bugs ({len(data['automation_bugs'])})</h2>
    {bugs_html}

    <div class="footer">
        <p>Generated from PostgreSQL (10.185.20.124) | Version: {VERSION} | Period: {DATE_FROM} to {DATE_TO}</p>
    </div>
</div>
</body>
</html>"""

    filename = f"ci_report_{VERSION.replace('.', '_')}_{DATE_FROM.replace('-', '')}_to_{DATE_TO.replace('-', '')}.html"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report_html)
    print(f"\n✓ Report saved to {filename}")
    return filename


def main():
    print("=" * 70)
    print(f"CI AUTOMATION TEST RESULTS - {VERSION} - {DATE_FROM} to {DATE_TO}")
    print("=" * 70)
    print()

    try:
        jira = connect_to_jira()
        print("✓ Connected to Jira")
        conn = connect_to_postgres()
        print("✓ Connected to PostgreSQL")
        print()

        data = get_automation_data(conn, jira)
        if data is None:
            print("No data to report.")
            conn.close()
            return

        filename = generate_html_report(data)

        print(f"\n{'=' * 70}")
        print("SUMMARY")
        print(f"{'=' * 70}")
        print(f"Period: {DATE_FROM} to {DATE_TO}")
        print(f"Tests Executed: {data['total_tests']}")
        print(f"Total Executions: {data['total_executions']}")
        print(f"Passed: {data['passed']} ({data['pass_ratio']:.1f}%)")
        print(f"Failed: {data['failed']}")
        print(f"Coverage: {data['overall_coverage']:.1f}%")
        print(f"Critical Failures: {data['critical_failures']}")
        print(f"Automation Bugs: {len(data['automation_bugs'])}")
        print(f"\n✓ Report: {filename}")

        conn.close()

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
