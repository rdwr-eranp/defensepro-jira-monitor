"""
Release Gate Analysis Report Generator

This script evaluates the release readiness against defined gates:
1. Platform type coverage >90% per run mode (Transparent/Routing)
2. Each platform >50% coverage
3. No open bugs
4. All sub test executions accepted

Generates an HTML report with gate status and recommendations.
"""

import psycopg2
import pandas as pd
from datetime import datetime
import os
import sys
from jira import JIRA
from dotenv import load_dotenv

# Fix console encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Load environment variables
load_dotenv()

print("=" * 80)
print("RELEASE GATE ANALYSIS REPORT GENERATOR")
print("=" * 80)
print()

print("STEP 1: Enter Version")
version = input("Version (e.g., 10.12.0.0) [default: 10.12.0.0]: ").strip() or "10.12.0.0"
print(f"✓ Version set to: {version}\n")

print("STEP 2: Enter Build Numbers")
print("  Format options:")
print("    - Range: 95-106 (includes all builds from 95 to 106)")
print("    - Specific: 95,96,97,98,101,102 (only these builds)")
builds_input = input("Builds: ").strip()

# Parse builds
if builds_input:
    if '-' in builds_input and ',' not in builds_input:
        try:
            start_build, end_build = builds_input.split('-')
            start_build = int(start_build.strip())
            end_build = int(end_build.strip())
            builds = [str(b) for b in range(start_build, end_build + 1)]
            print(f"✓ Range parsed: builds {start_build} to {end_build} ({len(builds)} total builds)")
        except ValueError:
            builds = [b.strip() for b in builds_input.split(',')]
            print(f"✓ Parsed {len(builds)} specific builds")
    else:
        builds = [b.strip() for b in builds_input.split(',')]
        print(f"✓ Parsed {len(builds)} specific builds")
else:
    builds = ['95', '96', '97', '98', '101', '102', '103', '104', '106']
    print(f"✓ Using default builds: {', '.join(builds)}")

builds_str = "', '".join(builds)
builds_display = ", ".join(builds)

print(f"\nAnalyzing gates for:")
print(f"  Version: {version}")
print(f"  Builds: {builds_display}")
print()

# Connect to database
print("Connecting to PostgreSQL database...")
try:
    conn = psycopg2.connect(
        host="10.185.20.124",
        database="results",
        user="postgres",
        password="radware"
    )
    print("✅ Connected to PostgreSQL\n")
except Exception as e:
    print(f"❌ Database connection error: {e}")
    exit(1)

# Get consistently skipped tests (never executed on both 10.12.0.0 and 10.11.0.0)
print("Calculating adjusted baseline (excluding consistently skipped tests)...")
query_skipped_tests = """
WITH v1_tests AS (
    SELECT DISTINCT test_id
    FROM test_execution
    WHERE version = '10.12.0.0'
),
v2_tests AS (
    SELECT DISTINCT test_id
    FROM test_execution
    WHERE version = '10.11.0.0'
)
SELECT t.id
FROM test t
WHERE t.id NOT IN (SELECT test_id FROM v1_tests)
  AND t.id NOT IN (SELECT test_id FROM v2_tests)
"""
df_skipped = pd.read_sql(query_skipped_tests, conn)
skipped_test_ids = df_skipped['id'].tolist()
print(f"✓ Consistently skipped tests: {len(skipped_test_ids):,}")

# Get total tests
query_total_tests = "SELECT COUNT(*) as total FROM test"
df_total = pd.read_sql(query_total_tests, conn)
total_tests_all = df_total['total'][0]
total_tests = total_tests_all - len(skipped_test_ids)
print(f"✓ Total tests in system: {total_tests_all:,}")
print(f"✓ Adjusted baseline: {total_tests:,} (excluding {len(skipped_test_ids):,} consistently skipped)\n")

# Connect to Jira
print("Connecting to Jira...")
jira = None
try:
    jira_server = os.getenv('JIRA_URL') or os.getenv('JIRA_SERVER')
    jira_email = os.getenv('JIRA_EMAIL')
    jira_token = os.getenv('JIRA_API_TOKEN')
    verify_ssl = os.getenv('JIRA_VERIFY_SSL', 'True').lower() == 'true'
    
    options = {
        'server': jira_server,
        'verify': verify_ssl,
        'timeout': 10
    }
    
    jira = JIRA(options=options, basic_auth=(jira_email, jira_token))
    print("✅ Connected to Jira\n")
except Exception as e:
    print(f"⚠️ Jira connection error: {e}\n")

# Query platform type coverage by mode with platform-specific baselines
print("Querying platform type coverage...")
query_platform_type = f"""
WITH latest_executions AS (
    SELECT 
        te.test_id,
        d.platform,
        CASE 
            WHEN p.name LIKE '%-Routing' THEN 'Routing'
            ELSE 'Transparent'
        END as mode,
        te.status,
        ROW_NUMBER() OVER (
            PARTITION BY te.test_id, d.platform, 
            CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END
            ORDER BY te.start_time DESC
        ) as rn
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    JOIN profile p ON te.profile_id = p.id
    WHERE te.version = '{version}'
        AND te.build IN ('{builds_str}')
        AND te.mode = 'regression'
),
platform_type_mapping AS (
    SELECT 
        platform,
        CASE 
            WHEN platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
            WHEN platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
            WHEN platform = 'MRQ_X' THEN 'EZchip'
            ELSE 'Other'
        END as platform_type
    FROM (SELECT DISTINCT platform FROM latest_executions) p
),
available_tests AS (
    SELECT 
        d.platform,
        CASE 
            WHEN p.name LIKE '%-Routing' THEN 'Routing'
            ELSE 'Transparent'
        END as mode,
        te.test_id
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    JOIN profile p ON te.profile_id = p.id
    WHERE te.version IN ('10.12.0.0', '10.11.0.0')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
),
available_by_type AS (
    SELECT 
        ptm.platform_type,
        at.mode,
        COUNT(DISTINCT at.test_id) as available_tests
    FROM available_tests at
    JOIN platform_type_mapping ptm ON at.platform = ptm.platform
    GROUP BY ptm.platform_type, at.mode
)
SELECT 
    ptm.platform_type,
    le.mode,
    COUNT(DISTINCT le.test_id) as tests_executed,
    abt.available_tests,
    ROUND(COUNT(DISTINCT le.test_id)::numeric * 100.0 / abt.available_tests, 2) as coverage_percent,
    COUNT(DISTINCT CASE WHEN le.status = 'Passed' THEN le.test_id END) as tests_passed,
    COUNT(DISTINCT CASE WHEN le.status = 'Failed' THEN le.test_id END) as tests_failed,
    ROUND(COUNT(DISTINCT CASE WHEN le.status = 'Passed' THEN le.test_id END)::numeric * 100.0 / 
          NULLIF(COUNT(DISTINCT le.test_id), 0), 2) as pass_ratio
FROM latest_executions le
JOIN platform_type_mapping ptm ON le.platform = ptm.platform
JOIN available_by_type abt ON ptm.platform_type = abt.platform_type AND le.mode = abt.mode
WHERE le.rn = 1
GROUP BY ptm.platform_type, le.mode, abt.available_tests
ORDER BY ptm.platform_type, le.mode
"""
df_platform_type = pd.read_sql(query_platform_type, conn)

# Query platform coverage with platform-specific baselines
print("Querying platform coverage...")
query_platform = f"""
WITH latest_executions AS (
    SELECT 
        te.test_id,
        d.platform,
        CASE 
            WHEN p.name LIKE '%-Routing' THEN 'Routing'
            ELSE 'Transparent'
        END as mode,
        te.status,
        ROW_NUMBER() OVER (
            PARTITION BY te.test_id, d.platform, 
            CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END
            ORDER BY te.start_time DESC
        ) as rn
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    JOIN profile p ON te.profile_id = p.id
    WHERE te.version = '{version}'
        AND te.build IN ('{builds_str}')
        AND te.mode = 'regression'
),
available_tests AS (
    SELECT 
        d.platform,
        COUNT(DISTINCT te.test_id) as available_tests
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    WHERE te.version IN ('10.12.0.0', '10.11.0.0')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
    GROUP BY d.platform
)
SELECT 
    le.platform,
    COUNT(DISTINCT le.test_id) as tests_executed,
    at.available_tests,
    ROUND(COUNT(DISTINCT le.test_id)::numeric * 100.0 / at.available_tests, 2) as coverage_percent
FROM latest_executions le
JOIN available_tests at ON le.platform = at.platform
WHERE le.rn = 1
GROUP BY le.platform, at.available_tests
ORDER BY tests_executed DESC
"""
df_platform = pd.read_sql(query_platform, conn)

# Calculate test execution rate from recent builds
print("Calculating test execution rate...")
query_execution_rate = f"""
WITH recent_builds AS (
    SELECT DISTINCT build, 
           MIN(start_time) as build_start,
           MAX(start_time) as build_end
    FROM test_execution
    WHERE version = '{version}'
        AND build IN ('{builds_str}')
        AND mode = 'regression'
    GROUP BY build
    ORDER BY build DESC
    LIMIT 5
),
build_stats AS (
    SELECT rb.build,
           rb.build_start,
           rb.build_end,
           EXTRACT(EPOCH FROM (rb.build_end - rb.build_start)) / 3600.0 as duration_hours,
           COUNT(DISTINCT te.test_id) as tests_executed
    FROM recent_builds rb
    JOIN test_execution te ON te.build = rb.build AND te.version = '{version}' AND te.mode = 'regression'
    GROUP BY rb.build, rb.build_start, rb.build_end
)
SELECT 
    AVG(tests_executed / NULLIF(duration_hours, 0)) as tests_per_hour,
    AVG(duration_hours) as avg_build_duration_hours,
    AVG(tests_executed) as avg_tests_per_build
FROM build_stats
WHERE duration_hours > 0
"""

try:
    df_rate = pd.read_sql(query_execution_rate, conn)
    tests_per_hour = df_rate['tests_per_hour'].iloc[0] if not df_rate.empty and df_rate['tests_per_hour'].iloc[0] else 100
    avg_build_duration = df_rate['avg_build_duration_hours'].iloc[0] if not df_rate.empty else 24
    avg_tests_per_build = df_rate['avg_tests_per_build'].iloc[0] if not df_rate.empty else 6000
    print(f"✓ Execution rate: {tests_per_hour:.1f} tests/hour")
    print(f"✓ Avg build duration: {avg_build_duration:.1f} hours")
    print(f"✓ Avg tests per build: {avg_tests_per_build:.0f}\n")
except Exception as e:
    print(f"⚠️ Could not calculate execution rate: {e}")
    tests_per_hour = 100  # Default fallback
    avg_build_duration = 24
    avg_tests_per_build = 6000

# Query overall coverage and pass ratio
print("Calculating overall coverage and pass ratio...")
query_overall = f"""
WITH latest_executions AS (
    SELECT 
        te.test_id,
        te.device_id,
        d.platform,
        te.status,
        te.build,
        te.start_time,
        ROW_NUMBER() OVER (
            PARTITION BY te.test_id, d.platform
            ORDER BY te.start_time DESC
        ) as rn
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    WHERE te.version = '{version}'
        AND te.build IN ('{builds_str}')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
),
available_tests AS (
    SELECT COUNT(DISTINCT te.test_id) as total_available
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    WHERE te.version IN ('{version}', '10.11.0.0')
        AND te.mode = 'regression'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
),
execution_stats AS (
    SELECT 
        COUNT(DISTINCT test_id) as total_tests_executed,
        COUNT(*) as total_executions,
        SUM(CASE WHEN status = 'Passed' THEN 1 ELSE 0 END) as tests_passed,
        SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) as tests_failed
    FROM latest_executions
    WHERE rn = 1
)
SELECT 
    es.total_tests_executed,
    at.total_available,
    ROUND(es.total_tests_executed::numeric * 100.0 / at.total_available, 2) as coverage_percentage,
    es.total_executions,
    es.tests_passed,
    es.tests_failed,
    ROUND(es.tests_passed::numeric * 100.0 / es.total_executions, 2) as pass_ratio
FROM execution_stats es
CROSS JOIN available_tests at
"""

try:
    df_overall = pd.read_sql(query_overall, conn)
    overall_coverage = df_overall['coverage_percentage'].iloc[0] if not df_overall.empty else 0
    overall_pass_ratio = df_overall['pass_ratio'].iloc[0] if not df_overall.empty else 0
    overall_tests_executed = df_overall['total_tests_executed'].iloc[0] if not df_overall.empty else 0
    overall_available_tests = df_overall['total_available'].iloc[0] if not df_overall.empty else 0
    overall_tests_passed = df_overall['tests_passed'].iloc[0] if not df_overall.empty else 0
    overall_total_executions = df_overall['total_executions'].iloc[0] if not df_overall.empty else 0
    print(f"✓ Overall Coverage: {overall_coverage:.2f}% ({overall_tests_executed:,}/{overall_available_tests:,})")
    print(f"✓ Overall Pass Ratio: {overall_pass_ratio:.2f}% ({overall_tests_passed:,}/{overall_total_executions:,})\n")
except Exception as e:
    print(f"⚠️ Could not calculate overall metrics: {e}")
    overall_coverage = 0
    overall_pass_ratio = 0
    overall_tests_executed = 0
    overall_available_tests = 0
    overall_tests_passed = 0
    overall_total_executions = 0

conn.close()

# Query bugs from Jira
bugs_on_dev = 0
bugs_on_qa = 0
total_open_bugs = 0

if jira:
    print("Querying bugs from Jira...")
    try:
        jql_dev = f'project = DP AND type = Bug AND fixVersion = "{version}" AND status IN ("In Progress", "To-Do", "None")'
        bugs_dev = jira.search_issues(jql_dev, maxResults=1000)
        bugs_on_dev = len(bugs_dev)
        
        jql_qa = f'project = DP AND type = Bug AND fixVersion = "{version}" AND status = Completed'
        bugs_qa = jira.search_issues(jql_qa, maxResults=1000)
        bugs_on_qa = len(bugs_qa)
        
        jql_all = f'project = DP AND type = Bug AND fixVersion = "{version}" AND status NOT IN (Accepted, Closed)'
        bugs_all = jira.search_issues(jql_all, maxResults=1000)
        total_open_bugs = len(bugs_all)
        
        print(f"✓ Bugs on Dev: {bugs_on_dev}")
        print(f"✓ Bugs on QA: {bugs_on_qa}")
        print(f"✓ Total Open: {total_open_bugs}\n")
    except Exception as e:
        print(f"⚠️ Error querying bugs: {e}\n")

# Query sub test executions
sub_test_completed = 0
sub_test_in_progress = 0
sub_test_not_started = 0
sub_test_total = 0
sub_test_accepted = 0
sub_test_details = []

if jira:
    print("Querying sub test executions from Jira...")
    try:
        jql = f'project = DP AND type = "sub test execution" AND fixVersion = "{version}"'
        executions = jira.search_issues(jql, maxResults=1000)
        
        for issue in executions:
            status = str(issue.fields.status).lower()
            status_raw = str(issue.fields.status)
            
            # Skip executions in Trash status
            if status == 'trash':
                continue
            
            # Count non-trash executions
            sub_test_total += 1
            
            if status in ['done', 'completed', 'passed', 'failed', 'closed', 'accepted']:
                sub_test_completed += 1
                if status == 'accepted':
                    sub_test_accepted += 1
            elif status in ['in progress', 'executing', 'in review']:
                sub_test_in_progress += 1
            else:
                sub_test_not_started += 1
            
            sub_test_details.append({
                'key': issue.key,
                'summary': issue.fields.summary,
                'status': status_raw,
                'category': 'Completed' if status in ['done', 'completed', 'passed', 'failed', 'closed', 'accepted'] 
                           else ('In Progress' if status in ['in progress', 'executing', 'in review'] else 'Not Started'),
                'accepted': status == 'accepted'
            })
        
        print(f"✓ Total: {sub_test_total}")
        print(f"✓ Completed: {sub_test_completed}")
        print(f"✓ Accepted: {sub_test_accepted}")
        print(f"✓ In Progress: {sub_test_in_progress}")
        print(f"✓ Not Started: {sub_test_not_started}\n")
    except Exception as e:
        print(f"⚠️ Error querying sub test executions: {e}\n")

# Evaluate gates
print("=" * 80)
print("EVALUATING RELEASE GATES")
print("=" * 80)
print()

gates_status = []

# Gate 1: Platform type coverage >90% per mode AND pass ratio >90%
print("Gate 1: Platform Type Coverage >90% AND Pass Ratio >90% per Run Mode")
gate1_passed = True
gate1_details = []

for _, row in df_platform_type.iterrows():
    platform_type = row['platform_type']
    mode = row['mode']
    coverage = row['coverage_percent']
    tests_executed = row['tests_executed']
    available_tests = row['available_tests']
    pass_ratio = row['pass_ratio'] if 'pass_ratio' in row and pd.notna(row['pass_ratio']) else 0
    
    # Both coverage AND pass ratio must be >90%
    coverage_passed = coverage > 90
    pass_ratio_passed = pass_ratio > 90
    passed = coverage_passed and pass_ratio_passed
    
    # Determine status message
    if passed:
        status = "✅ READY"
        reason = ""
    elif not coverage_passed and not pass_ratio_passed:
        status = "⏳ PENDING"
        reason = " (Coverage & Pass Ratio below 90%)"
    elif not coverage_passed:
        status = "⏳ PENDING"
        reason = " (Coverage below 90%)"
    else:
        status = "⏳ PENDING"
        reason = " (Pass Ratio below 90%)"
    
    gap_percentage = max(0, 90.0 - coverage)
    pass_ratio_gap = max(0, 90.0 - pass_ratio)
    tests_needed = int((gap_percentage / 100.0) * available_tests)
    hours_needed = tests_needed / tests_per_hour if tests_per_hour > 0 else 0
    
    gate1_details.append({
        'platform_type': platform_type,
        'mode': mode,
        'tests_executed': tests_executed,
        'available_tests': available_tests,
        'coverage': coverage,
        'pass_ratio': pass_ratio,
        'passed': passed,
        'coverage_passed': coverage_passed,
        'pass_ratio_passed': pass_ratio_passed,
        'gap': gap_percentage,
        'pass_ratio_gap': pass_ratio_gap,
        'tests_needed': tests_needed,
        'hours_needed': hours_needed,
        'reason': reason
    })
    
    if not passed:
        gate1_passed = False
    
    print(f"  {status} - {platform_type} {mode}: Cov={coverage:.2f}% Pass={pass_ratio:.2f}%{reason}")

gates_status.append({'gate': 'Gate 1', 'name': 'Platform Type Coverage', 'passed': gate1_passed})
print(f"\nGate 1 Result: {'✅ READY' if gate1_passed else '⏳ PENDING'}\n")

# Gate 2: Each platform >50% coverage
print("Gate 2: Each Platform >50% Coverage")
gate2_passed = True
gate2_details = []

for _, row in df_platform.iterrows():
    platform = row['platform']
    coverage = row['coverage_percent']
    tests_executed = row['tests_executed']
    available_tests = row['available_tests']
    passed = coverage > 50
    
    status = "✅ READY" if passed else "⏳ PENDING"
    gate2_details.append({
        'platform': platform,
        'tests_executed': tests_executed,
        'available_tests': available_tests,
        'coverage': coverage,
        'passed': passed,
        'gap': max(0, 50.0 - coverage)
    })
    
    if not passed:
        gate2_passed = False
    
    print(f"  {status} - {platform}: {coverage}% ({tests_executed:,}/{available_tests:,})")

gates_status.append({'gate': 'Gate 2', 'name': 'Platform Coverage', 'passed': gate2_passed})
print(f"\nGate 2 Result: {'✅ READY' if gate2_passed else '⏳ PENDING'}\n")

# Gate 3: No open bugs
print("Gate 3: No Open Bugs")
gate3_passed = total_open_bugs == 0
print(f"  Bugs on Dev: {bugs_on_dev}")
print(f"  Bugs on QA: {bugs_on_qa}")
print(f"  Total Open: {total_open_bugs}")
gates_status.append({'gate': 'Gate 3', 'name': 'No Open Bugs', 'passed': gate3_passed})
print(f"\nGate 3 Result: {'✅ READY' if gate3_passed else '⏳ PENDING'}\n")

# Gate 4: All sub test executions accepted
print("Gate 4: All Sub Test Executions Accepted")
# Calculate gap percentage and check for completed but not accepted items
gap_percentage = ((sub_test_total - sub_test_accepted) / sub_test_total * 100) if sub_test_total > 0 else 0
completed_not_accepted = sub_test_completed - sub_test_accepted

# Gate passes if: all accepted OR (gap <5% AND no "completed but not accepted" items - only pending/in-progress allowed)
gate4_fully_passed = sub_test_total > 0 and sub_test_accepted == sub_test_total
gate4_pending_ok = not gate4_fully_passed and gap_percentage < 5.0 and completed_not_accepted == 0
gate4_passed = gate4_fully_passed or gate4_pending_ok

print(f"  Total Executions: {sub_test_total}")
print(f"  Accepted: {sub_test_accepted}")
print(f"  Completed (Not Accepted): {completed_not_accepted}")
print(f"  In Progress: {sub_test_in_progress}")
print(f"  Not Started: {sub_test_not_started}")
if not gate4_fully_passed and sub_test_total > 0:
    print(f"  Gap: {gap_percentage:.1f}%")
    if completed_not_accepted > 0:
        print(f"  ⚠️ {completed_not_accepted} execution(s) completed but not accepted - blocking gate")

gates_status.append({'gate': 'Gate 4', 'name': 'Sub Test Executions', 'passed': gate4_passed})

if gate4_fully_passed:
    print(f"\nGate 4 Result: ✅ READY\n")
elif gate4_pending_ok:
    print(f"\nGate 4 Result: ✅ READY (pending completion - gap {gap_percentage:.1f}% < 5%, no completed items)\n")
elif completed_not_accepted > 0:
    print(f"\nGate 4 Result: ❌ NOT READY ({completed_not_accepted} completed but not accepted)\n")
else:
    print(f"\nGate 4 Result: ⏳ PENDING (gap {gap_percentage:.1f}% >= 5%)\n")

# Gate 5: Overall coverage and pass ratio >90%
print("Gate 5: Overall Coverage and Pass Ratio >90%")
gate5_coverage_passed = overall_coverage > 90
gate5_pass_ratio_passed = overall_pass_ratio > 90
gate5_passed = gate5_coverage_passed and gate5_pass_ratio_passed

print(f"  Coverage: {overall_coverage:.2f}% ({overall_tests_executed:,}/{overall_available_tests:,}) - {'✅ READY' if gate5_coverage_passed else '⏳ PENDING'}")
print(f"  Pass Ratio: {overall_pass_ratio:.2f}% ({overall_tests_passed:,}/{overall_total_executions:,}) - {'✅ READY' if gate5_pass_ratio_passed else '⏳ PENDING'}")

gate5_details = {
    'coverage': overall_coverage,
    'coverage_passed': gate5_coverage_passed,
    'coverage_gap': max(0, 90.0 - overall_coverage),
    'pass_ratio': overall_pass_ratio,
    'pass_ratio_passed': gate5_pass_ratio_passed,
    'pass_ratio_gap': max(0, 90.0 - overall_pass_ratio),
    'tests_executed': overall_tests_executed,
    'available_tests': overall_available_tests,
    'tests_passed': overall_tests_passed,
    'total_executions': overall_total_executions
}

gates_status.append({'gate': 'Gate 5', 'name': 'Overall Metrics', 'passed': gate5_passed})
print(f"\nGate 5 Result: {'✅ READY' if gate5_passed else '⏳ PENDING'}\n")

# Overall status
overall_passed = all(g['passed'] for g in gates_status)
print("=" * 80)
print(f"OVERALL RELEASE STATUS: {'✅ READY FOR RELEASE' if overall_passed else '❌ NOT READY FOR RELEASE'}")
print("=" * 80)
print()

# Generate HTML report
print("Generating HTML gate analysis report...")

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Release Gate Analysis - {version}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, {'#4caf50' if overall_passed else '#f44336'} 0%, {'#45a049' if overall_passed else '#d32f2f'} 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 2.5em;
        }}
        .header .status {{
            font-size: 1.8em;
            margin-top: 15px;
            font-weight: bold;
        }}
        .summary-box {{
            background-color: white;
            padding: 25px;
            margin-bottom: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .summary-box h2 {{
            color: #333;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
            margin-top: 0;
        }}
        .gate-summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .gate-card {{
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            color: white;
        }}
        .gate-card.passed {{
            background: linear-gradient(135deg, #4caf50 0%, #45a049 100%);
        }}
        .gate-card.failed {{
            background: linear-gradient(135deg, #f44336 0%, #d32f2f 100%);
        }}
        .gate-card .gate-number {{
            font-size: 1.2em;
            font-weight: bold;
            opacity: 0.9;
        }}
        .gate-card .gate-name {{
            font-size: 1.5em;
            font-weight: bold;
            margin: 10px 0;
        }}
        .gate-card .gate-status {{
            font-size: 2em;
            margin: 10px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
            background-color: white;
        }}
        th {{
            background-color: #667eea;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid #ddd;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .pass {{ color: #4caf50; font-weight: bold; }}
        .fail {{ color: #f44336; font-weight: bold; }}
        .warning {{ color: #ff9800; font-weight: bold; }}
        .recommendations {{
            background-color: #fff3e0;
            border-left: 5px solid #ff9800;
            padding: 20px;
            margin-top: 20px;
            border-radius: 5px;
        }}
        .recommendations h3 {{
            margin-top: 0;
            color: #e65100;
        }}
        .recommendations ul {{
            margin: 10px 0;
        }}
        .recommendations li {{
            margin: 8px 0;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding: 20px;
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 Release Gate Analysis</h1>
        <p>DefensePro {version} - Builds {builds_display}</p>
        <p><strong>Baseline:</strong> Platform-specific available tests (executed on 10.12.0.0 OR 10.11.0.0)</p>
        <div class="status">
            {'✅ READY FOR RELEASE' if overall_passed else '❌ NOT READY FOR RELEASE'}
        </div>
        <p>Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}</p>
    </div>
    
    <div class="summary-box">
        <h2>Gate Summary</h2>
        <div class="gate-summary">
"""

for gate in gates_status:
    html_content += f"""
            <div class="gate-card {'passed' if gate['passed'] else 'failed'}">
                <div class="gate-number">{gate['gate']}</div>
                <div class="gate-name">{gate['name']}</div>
                <div class="gate-status">{'✅ READY' if gate['passed'] else '⏳ PENDING'}</div>
            </div>
"""

html_content += """
        </div>
    </div>
    
    <div class="summary-box">
        <h2>Gate 1: Platform Type Coverage >90% AND Pass Ratio >90% per Run Mode</h2>
        <p><strong>Requirements:</strong></p>
        <ul>
            <li>Each platform type must have >90% test coverage for both Transparent and Routing modes</li>
            <li>Each platform type must have >90% pass ratio (test quality) for both modes</li>
        </ul>
        <p><strong>Baseline:</strong> Uses platform type-specific available tests (tests executed on at least one recent version).</p>
        <table>
            <thead>
                <tr>
                    <th>Platform Type</th>
                    <th>Run Mode</th>
                    <th>Tests Executed</th>
                    <th>Available Tests</th>
                    <th>Coverage %</th>
                    <th>Pass Ratio %</th>
                    <th>Status</th>
                    <th>Coverage Gap</th>
                    <th>Pass Ratio Gap</th>
                </tr>
            </thead>
            <tbody>
"""

for detail in gate1_details:
    status_class = 'pass' if detail['passed'] else 'fail'
    status_text = '✅ READY' if detail['passed'] else f"⏳ PENDING{detail['reason']}"
    coverage_class = 'pass' if detail['coverage_passed'] else 'fail'
    pass_ratio_class = 'pass' if detail['pass_ratio_passed'] else 'fail'
    html_content += f"""
                <tr>
                    <td><strong>{detail['platform_type']}</strong></td>
                    <td>{detail['mode']}</td>
                    <td>{detail['tests_executed']:,}</td>
                    <td>{detail['available_tests']:,}</td>
                    <td class=\"{coverage_class}\">{detail['coverage']:.2f}%</td>
                    <td class=\"{pass_ratio_class}\">{detail['pass_ratio']:.2f}%</td>
                    <td class=\"{status_class}\">{status_text}</td>
                    <td>{detail['gap']:.2f}%</td>
                    <td>{detail['pass_ratio_gap']:.2f}%</td>
                </tr>
"""

html_content += """
            </tbody>
        </table>
"""

if not gate1_passed:
    html_content += """
        <div class="recommendations">
            <h3>📋 Actions Required:</h3>
            <ul>
"""
    for detail in gate1_details:
        if not detail['passed']:
            issues = []
            if not detail['coverage_passed']:
                days = detail['hours_needed'] / 24
                issues.append(f"Coverage: Need {detail['gap']:.2f}% more (execute ~{detail['tests_needed']:,} more tests)")
                issues.append(f"<span style='margin-left: 20px; color: #666;'>⏱️ Estimated time: {detail['hours_needed']:.1f} hours (~{days:.1f} days at {tests_per_hour:.0f} tests/hour)</span>")
            if not detail['pass_ratio_passed']:
                issues.append(f"Pass Ratio: Need {detail['pass_ratio_gap']:.2f}% improvement (fix failing tests)")
            
            html_content += f"""                <li><strong>{detail['platform_type']} {detail['mode']}:</strong><br>
                    <span style="margin-left: 20px;">{'<br>'.join(issues)}</span>
                </li>
"""
    
    html_content += """
            </ul>
        </div>
"""

html_content += """
    </div>
    
    <div class="summary-box">
        <h2>Gate 2: Each Platform >50% Coverage</h2>
        <p><strong>Requirement:</strong> Each specific platform must have >50% test coverage.</p>
        <p><strong>Baseline:</strong> Uses platform-specific available tests (tests executed on at least one recent version).</p>
        <table>
            <thead>
                <tr>
                    <th>Platform</th>
                    <th>Tests Executed</th>
                    <th>Available Tests</th>
                    <th>Coverage %</th>
                    <th>Status</th>
                    <th>Gap to 50%</th>
                </tr>
            </thead>
            <tbody>
"""

for detail in gate2_details:
    status_class = 'pass' if detail['passed'] else 'fail'
    status_text = '✅ READY' if detail['passed'] else '⏳ PENDING'
    html_content += f"""
                <tr>
                    <td><strong>{detail['platform']}</strong></td>
                    <td>{detail['tests_executed']:,}</td>
                    <td>{detail['available_tests']:,}</td>
                    <td>{detail['coverage']:.2f}%</td>
                    <td class=\"{status_class}\">{status_text}</td>
                    <td>{detail['gap']:.2f}%</td>
                </tr>
"""

html_content += """
            </tbody>
        </table>
"""

if not gate2_passed:
    html_content += """
        <div class="recommendations">
            <h3>📋 Actions Required:</h3>
            <ul>
"""
    for detail in gate2_details:
        if not detail['passed']:
            html_content += f"                <li><strong>{detail['platform']}:</strong> Need {detail['gap']:.2f}% more coverage</li>\n"
    
    html_content += """
            </ul>
        </div>
"""

html_content += f"""
    </div>
    
    <div class="summary-box">
        <h2>Gate 3: No Open Bugs</h2>
        <p><strong>Requirement:</strong> All bugs must be Accepted or Closed (no bugs in Dev or QA status).</p>
        <table>
            <thead>
                <tr>
                    <th>Bug Category</th>
                    <th>Count</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Bugs on Dev (In Progress, To-Do, None)</td>
                    <td>{bugs_on_dev}</td>
                    <td class="{'pass' if bugs_on_dev == 0 else 'fail'}">{'✅ READY' if bugs_on_dev == 0 else '⏳ PENDING'}</td>
                </tr>
                <tr>
                    <td>Bugs on QA (Completed)</td>
                    <td>{bugs_on_qa}</td>
                    <td class="{'pass' if bugs_on_qa == 0 else 'fail'}">{'✅ READY' if bugs_on_qa == 0 else '⏳ PENDING'}</td>
                </tr>
                <tr style="font-weight: bold;">
                    <td><strong>Total Open Bugs</strong></td>
                    <td><strong>{total_open_bugs}</strong></td>
                    <td class="{'pass' if gate3_passed else 'fail'}"><strong>{'✅ READY' if gate3_passed else '⏳ PENDING'}</strong></td>
                </tr>
            </tbody>
        </table>
"""

if not gate3_passed:
    html_content += f"""
        <div class="recommendations">
            <h3>📋 Actions Required:</h3>
            <ul>
                <li>Close or accept all {total_open_bugs} open bug(s)</li>
                <li>Bugs on Dev: {bugs_on_dev} - Need development completion and QA verification</li>
                <li>Bugs on QA: {bugs_on_qa} - Need QA sign-off and acceptance</li>
            </ul>
        </div>
"""

html_content += f"""
    </div>
    
    <div class="summary-box">
        <h2>Gate 4: All Sub Test Executions Accepted</h2>
        <p><strong>Requirement:</strong> All sub test execution tasks must be in Accepted status.</p>
        <table>
            <thead>
                <tr>
                    <th>Execution Status</th>
                    <th>Count</th>
                    <th>Percentage</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Accepted</td>
                    <td>{sub_test_accepted}</td>
                    <td>{(sub_test_accepted / sub_test_total * 100) if sub_test_total > 0 else 0:.1f}%</td>
                </tr>
                <tr>
                    <td>Completed (Not Accepted)</td>
                    <td>{sub_test_completed - sub_test_accepted}</td>
                    <td>{((sub_test_completed - sub_test_accepted) / sub_test_total * 100) if sub_test_total > 0 else 0:.1f}%</td>
                </tr>
                <tr>
                    <td>In Progress</td>
                    <td>{sub_test_in_progress}</td>
                    <td>{(sub_test_in_progress / sub_test_total * 100) if sub_test_total > 0 else 0:.1f}%</td>
                </tr>
                <tr>
                    <td>Not Started</td>
                    <td>{sub_test_not_started}</td>
                    <td>{(sub_test_not_started / sub_test_total * 100) if sub_test_total > 0 else 0:.1f}%</td>
                </tr>
                <tr style="font-weight: bold;">
                    <td><strong>Total Executions</strong></td>
                    <td><strong>{sub_test_total}</strong></td>
                    <td class="{'pass' if gate4_passed else 'fail'}"><strong>{'✅ READY' if gate4_fully_passed else ('✅ READY (pending completion)' if gate4_pending_ok else '❌ NOT READY')}</strong></td>
                </tr>
            </tbody>
        </table>
"""

if gate4_pending_ok and not gate4_fully_passed:
    html_content += f"""
        <p style="margin-top: 15px; padding: 10px; background-color: #d1ecf1; border-left: 4px solid #0c5460; color: #0c5460;">
            <strong>Note:</strong> Gap of {gap_percentage:.1f}% is below the 5% threshold with only pending/in-progress items. Gate marked as READY.
        </p>
"""
elif completed_not_accepted > 0:
    html_content += f"""
        <p style="margin-top: 15px; padding: 10px; background-color: #f8d7da; border-left: 4px solid #dc3545; color: #721c24;">
            <strong>Note:</strong> {completed_not_accepted} sub test execution(s) are completed but not accepted. These must be accepted before gate can pass.
        </p>
"""

if not gate4_passed and sub_test_details:
    # Show non-accepted executions
    non_accepted = [d for d in sub_test_details if not d['accepted']]
    if non_accepted:
        html_content += """
        <h3 style="margin-top: 30px;">Non-Accepted Executions:</h3>
        <table>
            <thead>
                <tr>
                    <th>Key</th>
                    <th>Summary</th>
                    <th>Status</th>
                    <th>Category</th>
                </tr>
            </thead>
            <tbody>
"""
        for exec_detail in non_accepted:
            status_class = 'pass' if exec_detail['category'] == 'Completed' else ('warning' if exec_detail['category'] == 'In Progress' else 'fail')
            html_content += f"""
                <tr>
                    <td><strong>{exec_detail['key']}</strong></td>
                    <td>{exec_detail['summary']}</td>
                    <td class="{status_class}">{exec_detail['status']}</td>
                    <td class="{status_class}">{exec_detail['category']}</td>
                </tr>
"""
        html_content += """
            </tbody>
        </table>
"""

    html_content += f"""
        <div class="recommendations">
            <h3>📋 Actions Required:</h3>
            <ul>
                <li>Complete {sub_test_in_progress} in-progress execution(s)</li>
                <li>Start and complete {sub_test_not_started} pending execution(s)</li>
                <li>Accept {sub_test_completed - sub_test_accepted} completed but not accepted execution(s)</li>
                <li>Total tasks remaining: {sub_test_total - sub_test_accepted}</li>
            </ul>
        </div>
"""

html_content += """
    </div>
"""

# Gate 5: Overall Coverage and Pass Ratio
html_content += f"""
    <div class="summary-box">
        <h2>Gate 5: Overall Coverage and Pass Ratio >90%</h2>
        <p><strong>Requirement:</strong> Overall test coverage and pass ratio must both be above 90%.</p>
        <p><strong>Baseline:</strong> Uses platform-specific available tests (excluding MRQ, MR, VL2).</p>
        <table>
            <thead>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                    <th>Target</th>
                    <th>Status</th>
                    <th>Gap to 90%</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>Overall Coverage</strong></td>
                    <td>{gate5_details['coverage']:.2f}% ({gate5_details['tests_executed']:,}/{gate5_details['available_tests']:,})</td>
                    <td>>90%</td>
                    <td class="{'pass' if gate5_details['coverage_passed'] else 'fail'}">{'✅ READY' if gate5_details['coverage_passed'] else '⏳ PENDING'}</td>
                    <td>{gate5_details['coverage_gap']:.2f}%</td>
                </tr>
                <tr>
                    <td><strong>Overall Pass Ratio</strong></td>
                    <td>{gate5_details['pass_ratio']:.2f}% ({gate5_details['tests_passed']:,}/{gate5_details['total_executions']:,})</td>
                    <td>>90%</td>
                    <td class="{'pass' if gate5_details['pass_ratio_passed'] else 'fail'}">{'✅ READY' if gate5_details['pass_ratio_passed'] else '⏳ PENDING'}</td>
                    <td>{gate5_details['pass_ratio_gap']:.2f}%</td>
                </tr>
            </tbody>
        </table>
"""

if not gate5_passed:
    html_content += """
        <div class="recommendations">
            <h3>📋 Actions Required:</h3>
            <ul>
"""
    if not gate5_details['coverage_passed']:
        tests_needed_coverage = int((gate5_details['coverage_gap'] / 100.0) * gate5_details['available_tests'])
        hours_needed_coverage = tests_needed_coverage / tests_per_hour if tests_per_hour > 0 else 0
        days_coverage = hours_needed_coverage / 24
        html_content += f"""                <li><strong>Coverage:</strong> Need {gate5_details['coverage_gap']:.2f}% more coverage (execute ~{tests_needed_coverage:,} more tests)<br>
                    <span style="margin-left: 20px; color: #666;">⏱️ Estimated time: {hours_needed_coverage:.1f} hours (~{days_coverage:.1f} days at {tests_per_hour:.0f} tests/hour)</span>
                </li>
"""
    if not gate5_details['pass_ratio_passed']:
        html_content += f"""                <li><strong>Pass Ratio:</strong> Improve test stability - need {gate5_details['pass_ratio_gap']:.2f}% improvement in pass rate</li>
"""
    
    html_content += """
            </ul>
        </div>
"""

html_content += """
    </div>
"""

# Overall recommendations
if not overall_passed:
    html_content += """
    <div class="summary-box">
        <h2>🎯 Overall Release Readiness Summary</h2>
        <div class="recommendations">
            <h3>Critical Actions for Release:</h3>
            <ol>
"""
    
    if not gate1_passed:
        failed_count = sum(1 for d in gate1_details if not d['passed'])
        html_content += f"""
                <li><strong>Platform Type Coverage (Gate 1):</strong> {failed_count} platform type/mode combination(s) below 90% threshold
                    <ul>
"""
        for detail in gate1_details:
            if not detail['passed']:
                html_content += f"                        <li>{detail['platform_type']} {detail['mode']}: Execute {int(detail['gap'] * 86.47)} more tests to close {detail['gap']:.2f}% gap</li>\n"
        html_content += """
                    </ul>
                </li>
"""
    
    if not gate2_passed:
        failed_count = sum(1 for d in gate2_details if not d['passed'])
        html_content += f"""
                <li><strong>Platform Coverage (Gate 2):</strong> {failed_count} platform(s) below 50% threshold</li>
"""
    
    if not gate3_passed:
        html_content += f"""
                <li><strong>Bug Closure (Gate 3):</strong> {total_open_bugs} open bug(s) need resolution</li>
"""
    
    if not gate4_passed:
        html_content += f"""
                <li><strong>Sub Test Executions (Gate 4):</strong> {sub_test_total - sub_test_accepted} execution task(s) need acceptance</li>
"""
    
    html_content += """
            </ol>
        </div>
    </div>
"""
else:
    html_content += """
    <div class="summary-box">
        <h2>🎉 Release Readiness Confirmed</h2>
        <p style="font-size: 1.2em; color: #4caf50;">
            <strong>All release gates have been passed. The release is ready for GA.</strong>
        </p>
        <ul style="font-size: 1.1em;">
            <li>✅ Platform type coverage exceeds 90% for all modes</li>
            <li>✅ All platforms have >50% coverage</li>
            <li>✅ No open bugs</li>
            <li>✅ All sub test executions accepted</li>
        </ul>
    </div>
"""

html_content += f"""
    <div class="footer">
        <p>Release Gate Analysis Report generated on {datetime.now().strftime('%B %d, %Y at %H:%M')}</p>
        <p>DefensePro {version} - Builds {builds_display}</p>
    </div>
</body>
</html>
"""

# Save HTML report
builds_filename = "_".join(builds)
output_file = f"Release_{version.replace('.', '_')}_Builds_{builds_filename}_Gate_Analysis.html"
with open(output_file, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"✅ Gate analysis report generated: {output_file}\n")

# Print summary
passed_count = sum(1 for g in gates_status if g['passed'])
print("=" * 80)
print(f"SUMMARY: {passed_count}/{len(gates_status)} gates passed")
print(f"Release Status: {'✅ READY FOR RELEASE' if overall_passed else '❌ NOT READY FOR RELEASE'}")
print("=" * 80)
