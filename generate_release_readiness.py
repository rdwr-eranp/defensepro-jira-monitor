"""
Release Readiness Report Generator

This script generates a comprehensive test coverage report for DefensePro releases,
analyzing regression mode test executions with Transparent vs Routing mode distinction.

The report includes:
- Overall coverage metrics
- Coverage by run mode (platform + mode combinations)
- Platform and platform type summaries
- Build-level coverage analysis
- Automated HTML report generation

Methodology:
- Filters for regression mode only
- Counts only the last execution per test per platform per mode
- Distinguishes between Transparent and Routing modes based on test profile
- Pass ratio = (Tests Passed / Tests Executed) × 100%
"""

import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import os
from jira import JIRA
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Prompt for parameters
print("=" * 80)
print("RELEASE READINESS REPORT GENERATOR")
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
    # Check if input is a range (e.g., 95-106)
    if '-' in builds_input and ',' not in builds_input:
        try:
            start_build, end_build = builds_input.split('-')
            start_build = int(start_build.strip())
            end_build = int(end_build.strip())
            builds = [str(b) for b in range(start_build, end_build + 1)]
            print(f"✓ Range parsed: builds {start_build} to {end_build} ({len(builds)} total builds)")
        except ValueError:
            print(f"⚠️  Invalid range format: {builds_input}. Trying comma-separated format.")
            builds = [b.strip() for b in builds_input.split(',')]
            print(f"✓ Parsed {len(builds)} specific builds")
    else:
        # Comma-separated format
        builds = [b.strip() for b in builds_input.split(',')]
        print(f"✓ Parsed {len(builds)} specific builds")
else:
    builds = ['95', '96', '97', '98', '101', '102', '103', '104', '106']
    print(f"✓ Using default builds: {', '.join(builds)}")

# Format builds for SQL
builds_str = "', '".join(builds)
builds_display = ", ".join(builds)

print(f"\nGenerating report for:")
print(f"  Version: {version}")
print(f"  Builds: {builds_display}")
print()

# Connect to Jira for bug trend analysis
print("Connecting to Jira for bug trend analysis...")
jira = None
try:
    jira_server = os.getenv('JIRA_URL') or os.getenv('JIRA_SERVER')  # Support both variable names
    jira_email = os.getenv('JIRA_EMAIL')
    jira_token = os.getenv('JIRA_API_TOKEN')
    verify_ssl = os.getenv('JIRA_VERIFY_SSL', 'True').lower() == 'true'
    
    if not all([jira_server, jira_email, jira_token]):
        raise ValueError("Missing Jira credentials in .env file")
    
    # Connection options with timeout and SSL settings
    options = {
        'server': jira_server,
        'verify': verify_ssl,
        'timeout': 10  # 10 second timeout
    }
    
    jira = JIRA(options=options, basic_auth=(jira_email, jira_token))
    print("✅ Connected to Jira\n")
except KeyboardInterrupt:
    print("\n⚠️ Connection interrupted by user")
    print("Bug trend analysis will be skipped.\n")
    jira = None
except Exception as e:
    print(f"⚠️ Warning: Could not connect to Jira: {e}")
    print("Bug trend analysis will be skipped.\n")
    jira = None

# Database connection
try:
    conn = psycopg2.connect(
        host="10.185.20.124",
        database="results",
        user="postgres",
        password="radware"
    )
    print("✅ Connected to PostgreSQL database\n")
except Exception as e:
    print(f"❌ Error connecting to database: {e}")
    exit(1)

print("=" * 80)
print(f"AUTOMATED TEST COVERAGE REPORT - Regression Mode Only (Last Execution)")
print(f"DefensePro {version} - Builds {builds_display}")
print("Transparent vs Routing Mode Analysis")
print("Excluding consistently skipped tests (not run on 10.12.0.0 or 10.11.0.0)")
print("=" * 80)

# Get consistently skipped tests (never executed on both 10.12.0.0 and 10.11.0.0)
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
print(f"\nConsistently skipped tests (not run on 10.12.0.0 or 10.11.0.0): {len(skipped_test_ids):,}")

# Get total tests in system (excluding consistently skipped)
query_total_tests = "SELECT COUNT(*) as total FROM test"
df_total = pd.read_sql(query_total_tests, conn)
total_tests_all = df_total['total'][0]
total_tests = total_tests_all - len(skipped_test_ids)
print(f"Total tests in system: {total_tests_all:,}")
print(f"Total tests (excluding consistently skipped): {total_tests:,}")

# Query 1: Overall coverage with platform-specific available tests
query_overall = f"""
WITH latest_executions AS (
    SELECT 
        te.test_id,
        te.device_id,
        d.platform,
        te.status,
        te.build,
        te.start_time,
        ROW_NUMBER() OVER (PARTITION BY te.test_id, d.platform ORDER BY te.start_time DESC) as rn
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
    WHERE te.version IN ('10.12.0.0', '10.11.0.0')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
),
execution_stats AS (
    SELECT 
        COUNT(DISTINCT le.test_id) as total_tests_executed,
        COUNT(*) as total_executions,
        SUM(CASE WHEN le.status = 'Passed' THEN 1 ELSE 0 END) as tests_passed,
        SUM(CASE WHEN le.status = 'Failed' THEN 1 ELSE 0 END) as tests_failed
    FROM latest_executions le
    WHERE le.rn = 1
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

df_overall = pd.read_sql(query_overall, conn)
print("\n1. OVERALL COVERAGE (Last Execution per Test per Platform)")
print("-" * 80)

# Check if we have data
if df_overall.empty or df_overall['total_tests_executed'][0] is None or df_overall['total_tests_executed'][0] == 0:
    print("⚠️ No test data found for the specified version and builds!")
    print(f"   Version: {version}")
    print(f"   Builds: {builds_display}")
    print("\nPlease verify:")
    print("   - The version exists in the database")
    print("   - The builds have been executed")
    print("   - Tests are in 'regression' mode")
    conn.close()
    exit(1)

print(f"Total Tests in System: {total_tests:,}")
print(f"Available Tests (excluding MRQ/MR/VL2): {df_overall['total_available'][0]:,}")
print(f"Tests Executed: {df_overall['total_tests_executed'][0]:,} ({df_overall['coverage_percentage'][0]}%)")
print(f"Total Executions Counted: {df_overall['total_executions'][0]:,}")
print(f"Tests Passed: {df_overall['tests_passed'][0]:,}")
print(f"Tests Failed: {df_overall['tests_failed'][0]:,}")
print(f"Pass Ratio: {df_overall['pass_ratio'][0]}%")

# Query 2: Platform coverage by run mode with available tests
query_platform = f"""
WITH latest_executions AS (
    SELECT 
        te.test_id,
        te.device_id,
        d.platform,
        p.name as profile_name,
        CASE 
            WHEN p.name LIKE '%-Routing' THEN 'Routing'
            ELSE 'Transparent'
        END as run_mode,
        te.status,
        te.build,
        te.start_time,
        ROW_NUMBER() OVER (PARTITION BY te.test_id, d.platform, 
            CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END 
            ORDER BY te.start_time DESC) as rn
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    LEFT JOIN profile p ON te.profile_id = p.id
    WHERE te.version = '{version}'
        AND te.build IN ('{builds_str}')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL 
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
),
available_tests AS (
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
    WHERE te.version IN ('10.12.0.0', '10.11.0.0')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
    GROUP BY d.platform, CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END
)
SELECT 
    le.platform,
    le.run_mode as mode,
    COUNT(DISTINCT le.test_id) as tests_executed,
    at.available_tests,
    ROUND(COUNT(DISTINCT le.test_id)::numeric * 100.0 / at.available_tests, 2) as coverage_of_total,
    COUNT(*) as total_executions,
    SUM(CASE WHEN le.status = 'Passed' THEN 1 ELSE 0 END) as tests_passed,
    SUM(CASE WHEN le.status = 'Failed' THEN 1 ELSE 0 END) as tests_failed,
    ROUND(SUM(CASE WHEN le.status = 'Passed' THEN 1 ELSE 0 END)::numeric * 100.0 / COUNT(*), 2) as pass_ratio
FROM latest_executions le
JOIN available_tests at ON le.platform = at.platform AND le.run_mode = at.mode
WHERE le.rn = 1
GROUP BY le.platform, le.run_mode, at.available_tests
ORDER BY le.platform, le.run_mode
"""

df_platform = pd.read_sql(query_platform, conn)
print("\n2. PLATFORM COVERAGE BY RUN MODE (Regression Mode: Transparent vs Routing)")
print("-" * 80)
print(df_platform.to_string(index=False))

# Query 2B: Platform summary with available tests
query_platform_summary = f"""
WITH latest_executions AS (
    SELECT 
        te.test_id,
        te.device_id,
        d.platform,
        te.status,
        te.build,
        te.start_time,
        ROW_NUMBER() OVER (PARTITION BY te.test_id, d.platform ORDER BY te.start_time DESC) as rn
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
    ROUND(COUNT(DISTINCT le.test_id)::numeric * 100.0 / at.available_tests, 2) as coverage_of_total,
    COUNT(*) as total_executions,
    SUM(CASE WHEN le.status = 'Passed' THEN 1 ELSE 0 END) as tests_passed,
    SUM(CASE WHEN le.status = 'Failed' THEN 1 ELSE 0 END) as tests_failed,
    ROUND(SUM(CASE WHEN le.status = 'Passed' THEN 1 ELSE 0 END)::numeric * 100.0 / COUNT(*), 2) as pass_ratio
FROM latest_executions le
JOIN available_tests at ON le.platform = at.platform
WHERE le.rn = 1
GROUP BY le.platform, at.available_tests
ORDER BY tests_executed DESC
"""

df_platform_summary = pd.read_sql(query_platform_summary, conn)
print("\n2B. PLATFORM SUMMARY (Unique tests across all modes per platform)")
print("-" * 80)
print(df_platform_summary.to_string(index=False))

# Query 3: Platform type coverage by mode with available tests
query_platform_type = f"""
WITH latest_executions AS (
    SELECT 
        te.test_id,
        te.device_id,
        d.platform,
        p.name as profile_name,
        CASE 
            WHEN p.name LIKE '%-Routing' THEN 'Routing'
            ELSE 'Transparent'
        END as run_mode,
        te.status,
        te.build,
        te.start_time,
        ROW_NUMBER() OVER (PARTITION BY te.test_id, d.platform, 
            CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END 
            ORDER BY te.start_time DESC) as rn
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    LEFT JOIN profile p ON te.profile_id = p.id
    WHERE te.version = '{version}'
        AND te.build IN ('{builds_str}')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL 
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
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
    LEFT JOIN profile p ON te.profile_id = p.id
    WHERE te.version IN ('10.12.0.0', '10.11.0.0')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
),
available_by_type AS (
    SELECT 
        CASE 
            WHEN at.platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
            WHEN at.platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
            WHEN at.platform = 'MRQ_X' THEN 'EZchip'
            ELSE 'Other'
        END as platform_type,
        at.mode,
        COUNT(DISTINCT at.test_id) as available_tests
    FROM available_tests at
    GROUP BY platform_type, at.mode
)
SELECT 
    CASE 
        WHEN le.platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
        WHEN le.platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
        WHEN le.platform = 'MRQ_X' THEN 'EZchip'
        ELSE 'Other'
    END as platform_type,
    le.run_mode as mode,
    COUNT(DISTINCT le.test_id) as tests_executed,
    abt.available_tests,
    ROUND(COUNT(DISTINCT le.test_id)::numeric * 100.0 / abt.available_tests, 2) as coverage_of_total,
    COUNT(*) as total_executions,
    SUM(CASE WHEN le.status = 'Passed' THEN 1 ELSE 0 END) as tests_passed,
    SUM(CASE WHEN le.status = 'Failed' THEN 1 ELSE 0 END) as tests_failed,
    ROUND(SUM(CASE WHEN le.status = 'Passed' THEN 1 ELSE 0 END)::numeric * 100.0 / COUNT(*), 2) as pass_ratio
FROM latest_executions le
JOIN available_by_type abt ON 
    CASE 
        WHEN le.platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
        WHEN le.platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
        WHEN le.platform = 'MRQ_X' THEN 'EZchip'
        ELSE 'Other'
    END = abt.platform_type 
    AND le.run_mode = abt.mode
WHERE le.rn = 1
GROUP BY 
    CASE 
        WHEN le.platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
        WHEN le.platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
        WHEN le.platform = 'MRQ_X' THEN 'EZchip'
        ELSE 'Other'
    END, 
    le.run_mode, 
    abt.available_tests
ORDER BY platform_type, le.run_mode
"""

df_platform_type = pd.read_sql(query_platform_type, conn)
print("\n3. PLATFORM TYPE COVERAGE BY RUN MODE (Regression Mode: Transparent vs Routing)")
print("-" * 80)
print(df_platform_type.to_string(index=False))

# Query 3B: Platform type summary with available tests
query_platform_type_summary = f"""
WITH latest_executions AS (
    SELECT 
        te.test_id,
        te.device_id,
        d.platform,
        te.status,
        te.build,
        te.start_time,
        ROW_NUMBER() OVER (PARTITION BY te.test_id, d.platform ORDER BY te.start_time DESC) as rn
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
    SELECT 
        d.platform,
        te.test_id
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    WHERE te.version IN ('10.12.0.0', '10.11.0.0')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
),
available_by_type AS (
    SELECT 
        CASE 
            WHEN at.platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
            WHEN at.platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
            WHEN at.platform = 'MRQ_X' THEN 'EZchip'
            ELSE 'Other'
        END as platform_type,
        COUNT(DISTINCT at.test_id) as available_tests
    FROM available_tests at
    GROUP BY platform_type
)
SELECT 
    CASE 
        WHEN le.platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
        WHEN le.platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
        WHEN le.platform = 'MRQ_X' THEN 'EZchip'
        ELSE 'Other'
    END as platform_type,
    COUNT(DISTINCT le.test_id) as tests_executed,
    abt.available_tests,
    ROUND(COUNT(DISTINCT le.test_id)::numeric * 100.0 / abt.available_tests, 2) as coverage_of_total,
    COUNT(*) as total_executions,
    SUM(CASE WHEN le.status = 'Passed' THEN 1 ELSE 0 END) as tests_passed,
    SUM(CASE WHEN le.status = 'Failed' THEN 1 ELSE 0 END) as tests_failed,
    ROUND(SUM(CASE WHEN le.status = 'Passed' THEN 1 ELSE 0 END)::numeric * 100.0 / COUNT(*), 2) as pass_ratio
FROM latest_executions le
JOIN available_by_type abt ON 
    CASE 
        WHEN le.platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
        WHEN le.platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
        WHEN le.platform = 'MRQ_X' THEN 'EZchip'
        ELSE 'Other'
    END = abt.platform_type
WHERE le.rn = 1
GROUP BY 
    CASE 
        WHEN le.platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
        WHEN le.platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
        WHEN le.platform = 'MRQ_X' THEN 'EZchip'
        ELSE 'Other'
    END,
    abt.available_tests
ORDER BY tests_executed DESC
"""

df_platform_type_summary = pd.read_sql(query_platform_type_summary, conn)
print("\n3B. PLATFORM TYPE SUMMARY (Unique tests across all modes per type)")
print("-" * 80)
print(df_platform_type_summary.to_string(index=False))

# Query 4: Build coverage
query_build = f"""
WITH latest_executions AS (
    SELECT 
        te.test_id,
        te.device_id,
        d.platform,
        te.status,
        te.build,
        te.start_time,
        ROW_NUMBER() OVER (PARTITION BY te.test_id ORDER BY te.start_time DESC) as rn
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    WHERE te.version = '{version}'
        AND te.build IN ('{builds_str}')
        AND te.mode = 'regression'
        AND d.platform IS NOT NULL 
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
)
SELECT 
    build,
    COUNT(DISTINCT test_id) as tests_executed,
    ROUND(COUNT(DISTINCT test_id)::numeric * 100.0 / {total_tests}, 2) as coverage_of_total,
    COUNT(*) as total_executions,
    SUM(CASE WHEN status = 'Passed' THEN 1 ELSE 0 END) as tests_passed,
    SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) as tests_failed,
    ROUND(SUM(CASE WHEN status = 'Passed' THEN 1 ELSE 0 END)::numeric * 100.0 / COUNT(*), 2) as pass_ratio
FROM latest_executions
WHERE rn = 1
GROUP BY build
ORDER BY tests_executed DESC
"""

df_build = pd.read_sql(query_build, conn)
print("\n4. BUILD COVERAGE (Last Execution per Test)")
print("-" * 80)
print(df_build.to_string(index=False))

# Query 5: Newly added test cases (executed on current version but not on 10.11.0.0)
query_new_tests = f"""
WITH v1_tests AS (
    SELECT DISTINCT test_id
    FROM test_execution
    WHERE version = '{version}'
),
v2_tests AS (
    SELECT DISTINCT test_id
    FROM test_execution
    WHERE version = '10.11.0.0'
),
new_test_ids AS (
    SELECT test_id
    FROM v1_tests
    WHERE test_id NOT IN (SELECT test_id FROM v2_tests)
),
test_executions AS (
    SELECT 
        te.test_id,
        t.name,
        t.class_name,
        te.device_id,
        d.platform,
        te.status,
        te.start_time,
        ROW_NUMBER() OVER (PARTITION BY te.test_id, d.platform ORDER BY te.start_time DESC) as rn
    FROM test_execution te
    JOIN device d ON te.device_id = d.id
    JOIN test t ON te.test_id = t.id
    WHERE te.version = '{version}'
        AND te.build IN ('{builds_str}')
        AND te.mode = 'regression'
        AND te.test_id IN (SELECT test_id FROM new_test_ids)
        AND d.platform IS NOT NULL
        AND d.platform != 'Unknown'
        AND d.platform NOT IN ('MRQ', 'MR', 'VL2')
)
SELECT 
    test_id,
    name as test_name,
    class_name,
    COUNT(DISTINCT platform) as platform_count,
    STRING_AGG(DISTINCT platform, ', ' ORDER BY platform) as platforms,
    SUM(CASE WHEN status = 'Passed' THEN 1 ELSE 0 END) as passed_count,
    SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) as failed_count
FROM test_executions
WHERE rn = 1
GROUP BY test_id, name, class_name
ORDER BY class_name, name
"""

df_new_tests = pd.read_sql(query_new_tests, conn)
print(f"\n5. NEWLY ADDED TEST CASES (Not in 10.11.0.0)")
print("-" * 80)
print(f"Total Newly Added Tests: {len(df_new_tests):,}")
if not df_new_tests.empty:
    # Group by class_name
    class_groups = df_new_tests.groupby('class_name').agg({
        'test_id': 'count',
        'platform_count': 'mean',
        'passed_count': 'sum',
        'failed_count': 'sum'
    }).round(1)
    class_groups = class_groups.rename(columns={'test_id': 'test_count'})
    class_groups = class_groups.sort_values('test_count', ascending=False)
    
    # Save to CSV
    csv_filename = f"Release_{version.replace('.', '_')}_New_Tests.csv"
    df_new_tests.to_csv(csv_filename, index=False)
    print(f"\n✅ New tests exported to: {csv_filename}")
else:
    print("No newly added tests found.")

conn.close()

# Query 6: Bug trend analysis from Jira
bug_trend_data = None
print(f"\n{'=' * 80}")
print("BUG TREND ANALYSIS SECTION")
print(f"{'=' * 80}")
print(f"Jira connection object status: {jira is not None}")
# Write debug info to file
with open('jira_debug.log', 'w') as f:
    f.write(f"Jira object type: {type(jira)}\n")
    f.write(f"Jira object is None: {jira is None}\n")
    f.write(f"Jira object bool: {bool(jira)}\n")
    if jira:
        f.write(f"Jira server: {jira._options['server']}\n")
if jira:
    print("QUERYING BUG TREND DATA FROM JIRA")
    print(f"Version for query: {version}")
    
    debug_log = open('jira_query_debug.log', 'w')
    debug_log.write(f"Starting bug queries at {datetime.now()}\n")
    debug_log.write(f"Version: {version}\n\n")
    
    try:
        # Query bugs on Dev (In Progress, To-Do, None)
        jql_dev = f'project = DP AND type = Bug AND fixVersion = "{version}" AND status IN ("In Progress", "To-Do", "None") ORDER BY created DESC'
        print(f"\nJQL Dev Query: {jql_dev}")
        debug_log.write(f"JQL Dev: {jql_dev}\n")
        debug_log.flush()
        
        bugs_dev = jira.search_issues(jql_dev, maxResults=1000)
        print(f"✓ Bugs on Dev: {len(bugs_dev)}")
        debug_log.write(f"Bugs on Dev: {len(bugs_dev)}\n\n")
        debug_log.flush()
        
        # Query bugs on QA (Completed but not Accepted)
        jql_qa = f'project = DP AND type = Bug AND fixVersion = "{version}" AND status = Completed ORDER BY created DESC'
        print(f"\nJQL QA Query: {jql_qa}")
        debug_log.write(f"JQL QA: {jql_qa}\n")
        debug_log.flush()
        
        bugs_qa = jira.search_issues(jql_qa, maxResults=1000)
        print(f"✓ Bugs on QA: {len(bugs_qa)}")
        debug_log.write(f"Bugs on QA: {len(bugs_qa)}\n\n")
        debug_log.flush()
        
        # Query all open bugs for the release
        jql_all = f'project = DP AND type = Bug AND fixVersion = "{version}" AND status NOT IN (Accepted, Closed) ORDER BY created DESC'
        print(f"\nJQL All Query: {jql_all}")
        debug_log.write(f"JQL All: {jql_all}\n")
        debug_log.flush()
        
        bugs_all = jira.search_issues(jql_all, maxResults=1000)
        print(f"✓ Total Open Bugs: {len(bugs_all)}\n")
        debug_log.write(f"Total Open Bugs: {len(bugs_all)}\n\n")
        debug_log.flush()
        
        # Create weekly aggregation
        bug_list = []
        for bug in bugs_all:
            created = datetime.strptime(bug.fields.created[:10], '%Y-%m-%d')
            status = bug.fields.status.name
            
            # Categorize
            if status in ["In Progress", "To-Do", "None"]:
                category = "Dev"
            elif status == "Completed":
                category = "QA"
            else:
                category = "Other"
            
            bug_list.append({
                'key': bug.key,
                'created': created,
                'status': status,
                'category': category,
                'summary': bug.fields.summary
            })
        
        df_bugs = pd.DataFrame(bug_list)
        
        if not df_bugs.empty:
            # Group by week
            df_bugs['week'] = df_bugs['created'].dt.to_period('W').apply(lambda r: r.start_time)
            
            # Count bugs by week and category
            bug_trend = df_bugs.groupby(['week', 'category']).size().unstack(fill_value=0).reset_index()
            bug_trend['week_label'] = bug_trend['week'].dt.strftime('%b %d')
            
            # Calculate cumulative
            if 'Dev' not in bug_trend.columns:
                bug_trend['Dev'] = 0
            if 'QA' not in bug_trend.columns:
                bug_trend['QA'] = 0
            
            bug_trend['cumulative_dev'] = bug_trend['Dev'].cumsum()
            bug_trend['cumulative_qa'] = bug_trend['QA'].cumsum()
            bug_trend['cumulative_total'] = bug_trend['cumulative_dev'] + bug_trend['cumulative_qa']
            
            bug_trend_data = bug_trend
            
            print(f"\nBug trend data collected for {len(bug_trend)} weeks")
            debug_log.write(f"SUCCESS: Bug trend data collected for {len(bug_trend)} weeks\n")
            debug_log.close()
        else:
            # No bugs found - create empty data structure to show 0 bugs
            print("⚠️ No open bugs found for this release (showing 0 bugs in report)")
            debug_log.write("No open bugs found - creating empty data structure\n")
            debug_log.close()
            
            # Create a minimal data structure with current date and 0 bugs
            bug_trend_data = pd.DataFrame({
                'week': [datetime.now()],
                'Dev': [0],
                'QA': [0],
                'week_label': [datetime.now().strftime('%b %d')],
                'cumulative_dev': [0],
                'cumulative_qa': [0],
                'cumulative_total': [0]
            })
            
    except Exception as e:
        print(f"\n❌ Error querying Jira: {e}")
        print(f"Error type: {type(e).__name__}")
        debug_log.write(f"\nERROR: {e}\n")
        debug_log.write(f"Error type: {type(e).__name__}\n")
        import traceback
        traceback.print_exc()
        debug_log.write(traceback.format_exc())
        debug_log.close()
        bug_trend_data = None
else:
    print("\n⚠️ Skipping bug trend analysis (Jira not connected)")
    with open('jira_query_debug.log', 'w') as f:
        f.write("Jira was None - connection failed\n")

# Query 6: Sub Test Execution Status from Jira
sub_exec_data = None
if jira:
    print(f"\n{'=' * 80}")
    print("QUERYING SUB TEST EXECUTION STATUS")
    print(f"{'=' * 80}")
    
    try:
        jql_sub_exec = f'project = DP AND type = "sub test execution" AND fixVersion = "{version}" ORDER BY status'
        print(f"JQL: {jql_sub_exec}")
        
        sub_executions = jira.search_issues(jql_sub_exec, maxResults=1000, fields='status,summary,created')
        print(f"✓ Found {len(sub_executions)} sub test executions\n")
        
        if sub_executions:
            # Categorize by status
            exec_list = []
            for execution in sub_executions:
                status = execution.fields.status.name
                created = datetime.strptime(execution.fields.created[:10], '%Y-%m-%d')
                
                # Skip executions in Trash status
                if status.lower() == 'trash':
                    continue
                
                # Categorize status
                if status.lower() in ['done', 'completed', 'passed', 'failed', 'closed', 'accepted']:
                    category = 'Completed'
                elif status.lower() in ['in progress', 'executing', 'in review']:
                    category = 'In Progress'
                else:
                    category = 'Not Started'
                
                exec_list.append({
                    'key': execution.key,
                    'summary': execution.fields.summary,
                    'status': status,
                    'category': category,
                    'created': created
                })
            
            df_exec = pd.DataFrame(exec_list)
            
            # Calculate statistics
            total = len(df_exec)
            completed = len(df_exec[df_exec['category'] == 'Completed'])
            in_progress = len(df_exec[df_exec['category'] == 'In Progress'])
            not_started = len(df_exec[df_exec['category'] == 'Not Started'])
            completion_rate = (completed / total * 100) if total > 0 else 0
            
            # Group by week for burndown
            df_exec['week'] = df_exec['created'].dt.to_period('W').apply(lambda r: r.start_time)
            exec_by_week = df_exec.groupby('week').size().reset_index(name='created')
            exec_by_week['week_label'] = exec_by_week['week'].dt.strftime('%b %d')
            exec_by_week['cumulative'] = exec_by_week['created'].cumsum()
            
            # Status breakdown over time
            status_by_week = df_exec.groupby(['week', 'category']).size().unstack(fill_value=0).reset_index()
            status_by_week['week_label'] = status_by_week['week'].dt.strftime('%b %d')
            
            sub_exec_data = {
                'total': total,
                'completed': completed,
                'in_progress': in_progress,
                'not_started': not_started,
                'completion_rate': completion_rate,
                'by_week': exec_by_week,
                'status_by_week': status_by_week,
                'details': df_exec
            }
            
            print(f"Sub Test Execution Summary:")
            print(f"  Total: {total}")
            print(f"  Completed: {completed} ({completion_rate:.1f}%)")
            print(f"  In Progress: {in_progress}")
            print(f"  Not Started: {not_started}\n")
        else:
            print("No sub test executions found for this release\n")
            
    except Exception as e:
        print(f"\n❌ Error querying sub test executions: {e}")
        print(f"Error type: {type(e).__name__}\n")
        import traceback
        traceback.print_exc()
        sub_exec_data = None
else:
    print("\n⚠️ Skipping sub test execution analysis (Jira not connected)")

# Save all data
output_prefix = f"Release_{version.replace('.', '_')}_Builds_{'_'.join(builds)}"
df_overall.to_csv(f'{output_prefix}_overall.csv', index=False)
df_platform.to_csv(f'{output_prefix}_platform_mode.csv', index=False)
df_platform_summary.to_csv(f'{output_prefix}_platform_summary.csv', index=False)
df_platform_type.to_csv(f'{output_prefix}_platform_type_mode.csv', index=False)
df_platform_type_summary.to_csv(f'{output_prefix}_platform_type_summary.csv', index=False)
df_build.to_csv(f'{output_prefix}_build.csv', index=False)
if bug_trend_data is not None:
    bug_trend_data.to_csv(f'{output_prefix}_bug_trend.csv', index=False)
if sub_exec_data is not None:
    sub_exec_data['details'].to_csv(f'{output_prefix}_sub_test_executions.csv', index=False)

print("\n" + "=" * 80)
print("✅ Data saved to CSV files:")
print(f"   - {output_prefix}_overall.csv")
print(f"   - {output_prefix}_platform_mode.csv")
print(f"   - {output_prefix}_platform_summary.csv")
print(f"   - {output_prefix}_platform_type_mode.csv")
print(f"   - {output_prefix}_platform_type_summary.csv")
print(f"   - {output_prefix}_build.csv")
if bug_trend_data is not None:
    print(f"   - {output_prefix}_bug_trend.csv")
if sub_exec_data is not None:
    print(f"   - {output_prefix}_sub_test_executions.csv")
print("=" * 80)

conn.close()

# Generate HTML report
print("\nGenerating HTML report...")

# Add platform type mapping
platform_type_map = {
    'ESXI': 'Software', 'VL3': 'Software', 'KVM': 'Software', 'HT2': 'Software',
    'UHT': 'FPGA', 'MR2': 'FPGA', 'MRQP': 'FPGA',
    'MRQ_X': 'EZchip'
}
df_platform['type'] = df_platform['platform'].map(platform_type_map)
df_platform_summary['type'] = df_platform_summary['platform'].map(platform_type_map)
df_platform['run_mode'] = df_platform['platform'] + ' - ' + df_platform['mode']

# Generate HTML
html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Release Readiness Report - {version} Builds {builds_display}</title>
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
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
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
        .header p {{
            margin: 10px 0;
            font-size: 1.1em;
        }}
        .methodology-note {{
            background-color: #e3f2fd;
            border-left: 5px solid #2196f3;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 5px;
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
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .metric-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }}
        .metric-card .value {{
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }}
        .metric-card .label {{
            font-size: 0.9em;
            opacity: 0.9;
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
        .pass-high {{ color: #4caf50; font-weight: bold; }}
        .pass-medium {{ color: #ff9800; font-weight: bold; }}
        .pass-low {{ color: #f44336; font-weight: bold; }}
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
        <h1>🎯 Release Readiness Report</h1>
        <p>DefensePro {version} - Builds {builds_display}</p>
        <p><strong>Regression Mode Only:</strong> Transparent vs Routing Analysis</p>
        <p><strong>Methodology:</strong> Last Execution Only per Test per Platform per Mode</p>
        <p>Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}</p>
    </div>
    
    <div class="methodology-note">
        <strong>📋 Report Methodology:</strong> This report analyzes <strong>regression mode</strong> test executions only, distinguishing between 
        <strong>Transparent</strong> and <strong>Routing</strong> modes based on the test profile. For each unique test on each platform in each mode, 
        only the <strong>last (most recent) execution</strong> is counted. Pass ratio is calculated as <strong>passed tests % out of executed tests</strong>.
        Total of {total_tests:,} tests are available in the system (excluding {len(skipped_test_ids):,} tests that were not run on both 10.12.0.0 and 10.11.0.0).
    </div>
    
    <div class="summary-box">
        <h2>Overall Coverage Summary (Regression Mode)</h2>
        <div class="metric-grid">
            <div class="metric-card">
                <div class="label">Total Available Tests</div>
                <div class="value">{df_overall['total_available'][0]:,}</div>
                <div class="label">Excluding MRQ/MR/VL2</div>
            </div>
            <div class="metric-card">
                <div class="label">Tests Executed</div>
                <div class="value">{df_overall['total_tests_executed'][0]:,}</div>
                <div class="label">Unique tests run</div>
            </div>
            <div class="metric-card">
                <div class="label">Total Coverage</div>
                <div class="value">{df_overall['coverage_percentage'][0]:.2f}%</div>
                <div class="label">Executed / Available</div>
            </div>
            <div class="metric-card">
                <div class="label">Tests Passed</div>
                <div class="value">{df_overall['tests_passed'][0]:,}</div>
                <div class="label">Successful executions</div>
            </div>
            <div class="metric-card">
                <div class="label">Total Pass Ratio</div>
                <div class="value">{df_overall['pass_ratio'][0]:.2f}%</div>
                <div class="label">Passed / Executed</div>
            </div>
        </div>
    </div>
    
    <div class="summary-box">
        <h2>Platform Type Coverage</h2>
        <table>
            <thead>
                <tr>
                    <th>Platform Type</th>
                    <th>Tests Executed</th>
                    <th>Available Tests</th>
                    <th>Coverage</th>
                    <th>Tests Passed</th>
                    <th>Tests Failed</th>
                    <th>Pass Ratio</th>
                </tr>
            </thead>
            <tbody>
"""

for _, row in df_platform_type_summary.sort_values('tests_executed', ascending=False).iterrows():
    pass_class = 'pass-high' if row['pass_ratio'] >= 90 else ('pass-medium' if row['pass_ratio'] >= 85 else 'pass-low')
    html_content += f"""                <tr>
                    <td><strong>{row['platform_type']}</strong></td>
                    <td>{row['tests_executed']:,}</td>
                    <td>{row['available_tests']:,}</td>
                    <td><strong>{row['coverage_of_total']:.2f}%</strong></td>
                    <td>{row['tests_passed']:,}</td>
                    <td>{row['tests_failed']:,}</td>
                    <td class="{pass_class}">{row['pass_ratio']:.2f}%</td>
                </tr>
"""

html_content += """            </tbody>
        </table>
        
        <h3>By Platform Type and Mode</h3>
        <table>
            <thead>
                <tr>
                    <th>Platform Type</th>
                    <th>Mode</th>
                    <th>Tests Executed</th>
                    <th>Available Tests</th>
                    <th>Coverage</th>
                    <th>Pass Ratio</th>
                </tr>
            </thead>
            <tbody>
"""

for _, row in df_platform_type.sort_values(['platform_type', 'mode']).iterrows():
    pass_class = 'pass-high' if row['pass_ratio'] >= 90 else ('pass-medium' if row['pass_ratio'] >= 85 else 'pass-low')
    html_content += f"""                <tr>
                    <td>{row['platform_type']}</td>
                    <td><strong>{row['mode']}</strong></td>
                    <td>{row['tests_executed']:,}</td>
                    <td>{row['available_tests']:,}</td>
                    <td>{row['coverage_of_total']:.2f}%</td>
                    <td class="{pass_class}">{row['pass_ratio']:.2f}%</td>
                </tr>
"""

html_content += f"""            </tbody>
        </table>
    </div>
    
    <div class="summary-box">
        <h2>🔧 Run Mode Coverage (Platform + Mode Combinations)</h2>
        <p><strong>Note:</strong> Each "Run Mode" represents a unique combination of platform and mode (Transparent or Routing). 
        Pass ratio = (Tests Passed / Tests Executed) × 100%</p>
        <table>
            <thead>
                <tr>
                    <th>Run Mode</th>
                    <th>Platform Type</th>
                    <th>Available Tests</th>
                    <th>Tests Executed</th>
                    <th>Coverage %</th>
                    <th>Tests Passed</th>
                    <th>Tests Failed</th>
                    <th>Pass Ratio</th>
                </tr>
            </thead>
            <tbody>
"""

for _, row in df_platform.sort_values(['type', 'platform', 'mode']).iterrows():
    pass_class = 'pass-high' if row['pass_ratio'] >= 90 else ('pass-medium' if row['pass_ratio'] >= 85 else 'pass-low')
    html_content += f"""                <tr>
                    <td><strong>{row['run_mode']}</strong></td>
                    <td>{row['type']}</td>
                    <td>{row['available_tests']:,}</td>
                    <td>{row['tests_executed']:,}</td>
                    <td>{row['coverage_of_total']:.2f}%</td>
                    <td>{row['tests_passed']:,}</td>
                    <td>{row['tests_failed']:,}</td>
                    <td class="{pass_class}">{row['pass_ratio']:.2f}%</td>
                </tr>
"""

html_content += """            </tbody>
        </table>
    </div>
    
    <div class="summary-box">
        <h2>Platform Coverage Details</h2>
        <h3>Summary by Platform</h3>
        <table>
            <thead>
                <tr>
                    <th>Platform</th>
                    <th>Tests Executed</th>
                    <th>Available Tests</th>
                    <th>Coverage</th>
                    <th>Tests Passed</th>
                    <th>Tests Failed</th>
                    <th>Pass Ratio</th>
                </tr>
            </thead>
            <tbody>
"""

for _, row in df_platform_summary.sort_values('tests_executed', ascending=False).iterrows():
    pass_class = 'pass-high' if row['pass_ratio'] >= 90 else ('pass-medium' if row['pass_ratio'] >= 85 else 'pass-low')
    html_content += f"""                <tr>
                    <td><strong>{row['platform']}</strong></td>
                    <td>{row['tests_executed']:,}</td>
                    <td>{row['available_tests']:,}</td>
                    <td><strong>{row['coverage_of_total']:.2f}%</strong></td>
                    <td>{row['tests_passed']:,}</td>
                    <td>{row['tests_failed']:,}</td>
                    <td class="{pass_class}">{row['pass_ratio']:.2f}%</td>
                </tr>
"""

html_content += """            </tbody>
        </table>
        
        <h3>Detailed Breakdown by Platform and Mode</h3>
        <p><strong>Formula:</strong> Pass Ratio = (Tests Passed / Tests Executed) × 100%</p>
        <table>
            <thead>
                <tr>
                    <th>Platform</th>
                    <th>Mode</th>
                    <th>Tests Executed</th>
                    <th>Available Tests</th>
                    <th>Coverage</th>
                    <th>Tests Passed</th>
                    <th>Tests Failed</th>
                    <th>Pass Ratio</th>
                </tr>
            </thead>
            <tbody>
"""

for _, row in df_platform.sort_values(['platform', 'mode']).iterrows():
    pass_class = 'pass-high' if row['pass_ratio'] >= 90 else ('pass-medium' if row['pass_ratio'] >= 85 else 'pass-low')
    html_content += f"""                <tr>
                    <td><strong>{row['platform']}</strong></td>
                    <td><strong>{row['mode']}</strong></td>
                    <td>{row['tests_executed']:,}</td>
                    <td>{row['available_tests']:,}</td>
                    <td>{row['coverage_of_total']:.2f}%</td>
                    <td>{row['tests_passed']:,}</td>
                    <td>{row['tests_failed']:,}</td>
                    <td class="{pass_class}">{row['pass_ratio']:.2f}%</td>
                </tr>
"""

html_content += """            </tbody>
        </table>
    </div>
    
    <div class="summary-box">
        <h2>Build Coverage Analysis</h2>
        <table>
            <thead>
                <tr>
                    <th>Build</th>
                    <th>Tests Executed</th>
                    <th>Coverage</th>
                    <th>Tests Passed</th>
                    <th>Tests Failed</th>
                    <th>Pass Ratio</th>
                </tr>
            </thead>
            <tbody>
"""

for _, row in df_build.sort_values('tests_executed', ascending=False).iterrows():
    pass_class = 'pass-high' if row['pass_ratio'] >= 90 else ('pass-medium' if row['pass_ratio'] >= 85 else 'pass-low')
    html_content += f"""                <tr>
                    <td><strong>Build {row['build']}</strong></td>
                    <td>{row['tests_executed']:,}</td>
                    <td>{row['coverage_of_total']:.2f}%</td>
                    <td>{row['tests_passed']:,}</td>
                    <td>{row['tests_failed']:,}</td>
                    <td class="{pass_class}">{row['pass_ratio']:.2f}%</td>
                </tr>
"""

html_content += f"""            </tbody>
        </table>
    </div>
"""

# Add newly added test cases section
if not df_new_tests.empty:
    # Extract main features from test names (taking the first part before |)
    features = df_new_tests['test_name'].apply(lambda x: x.split('|')[0].strip() if '|' in x else x.split()[0] if x else 'Other')
    top_features = features.value_counts().head(5)
    
    # Build features list as HTML
    features_html = ""
    for i, (feat, count) in enumerate(top_features.items(), 1):
        features_html += f"<div style='padding: 5px 0; border-bottom: 1px solid #eee;'><strong>{i}. {feat}</strong>: {count} tests</div>"
    
    html_content += f"""
    <div class="summary-box">
        <h2>🆕 Newly Added Test Cases (Not in 10.11.0.0)</h2>
        <div class="metric-grid">
            <div class="metric-card">
                <div class="label">Total New Tests</div>
                <div class="value">{len(df_new_tests)}</div>
                <div class="label">First executed in {version}</div>
            </div>
            <div class="metric-card">
                <div class="label">Main Features Added</div>
                <div class="value">{len(features.unique())}</div>
                <div class="label">Top: {top_features.index[0] if len(top_features) > 0 else 'N/A'}</div>
            </div>
        </div>
        <div style="margin-top: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 5px;">
            <h3 style="margin: 0 0 10px 0; color: #333;">Top 5 Features by Test Count:</h3>
            {features_html}
        </div>
        <p style="margin-top: 15px;"><strong>Note:</strong> Full list of {len(df_new_tests)} new tests available in Release_{version.replace('.', '_')}_New_Tests.csv</p>
    </div>
"""

# Add bug trend section if data is available
if bug_trend_data is not None and not bug_trend_data.empty:
    current_dev = int(bug_trend_data['cumulative_dev'].iloc[-1]) if 'cumulative_dev' in bug_trend_data.columns else 0
    current_qa = int(bug_trend_data['cumulative_qa'].iloc[-1]) if 'cumulative_qa' in bug_trend_data.columns else 0
    current_total = current_dev + current_qa
    
    html_content += f"""
    <div class="summary-box">
        <h2>🐛 Open Bug Trend Analysis</h2>
        <div class="metric-grid">
            <div class="metric-card">
                <div class="label">Bugs on Dev</div>
                <div class="value">{current_dev}</div>
                <div class="label">In Progress / To-Do / None</div>
            </div>
            <div class="metric-card">
                <div class="label">Bugs on QA</div>
                <div class="value">{current_qa}</div>
                <div class="label">Completed (awaiting QA)</div>
            </div>
            <div class="metric-card">
                <div class="label">Total Open Bugs</div>
                <div class="value">{current_total}</div>
                <div class="label">Dev + QA</div>
            </div>
        </div>
        
        <h3>Weekly Bug Trend</h3>
        <table>
            <thead>
                <tr>
                    <th>Week Starting</th>
                    <th>New Bugs on Dev</th>
                    <th>New Bugs on QA</th>
                    <th>Cumulative Dev</th>
                    <th>Cumulative QA</th>
                    <th>Total Open</th>
                </tr>
            </thead>
            <tbody>
"""
    
    for _, row in bug_trend_data.iterrows():
        week_label = row['week_label'] if 'week_label' in row else row['week'].strftime('%b %d')
        new_dev = int(row['Dev']) if 'Dev' in row else 0
        new_qa = int(row['QA']) if 'QA' in row else 0
        cum_dev = int(row['cumulative_dev']) if 'cumulative_dev' in row else 0
        cum_qa = int(row['cumulative_qa']) if 'cumulative_qa' in row else 0
        cum_total = int(row['cumulative_total']) if 'cumulative_total' in row else 0
        
        html_content += f"""                <tr>
                    <td><strong>{week_label}</strong></td>
                    <td>{new_dev}</td>
                    <td>{new_qa}</td>
                    <td>{cum_dev}</td>
                    <td>{cum_qa}</td>
                    <td><strong>{cum_total}</strong></td>
                </tr>
"""
    
    html_content += """            </tbody>
        </table>
        
        <p style="margin-top: 20px;"><strong>Note:</strong> Bug categories:</p>
        <ul>
            <li><strong>Bugs on Dev:</strong> Status IN ("In Progress", "To-Do", "None") - Bugs being worked on by development</li>
            <li><strong>Bugs on QA:</strong> Status = "Completed" - Bugs resolved by dev awaiting QA verification</li>
        </ul>
    </div>
"""

# Add sub test execution section if data is available
if sub_exec_data is not None:
    total = sub_exec_data['total']
    completed = sub_exec_data['completed']
    in_progress = sub_exec_data['in_progress']
    not_started = sub_exec_data['not_started']
    completion_rate = sub_exec_data['completion_rate']
    
    html_content += f"""
    <div class="summary-box">
        <h2>🧪 Sub Test Execution Status</h2>
        <div class="metric-grid">
            <div class="metric-card">
                <div class="label">Total Executions</div>
                <div class="value">{total}</div>
                <div class="label">Sub test execution tasks</div>
            </div>
            <div class="metric-card">
                <div class="label">Completed</div>
                <div class="value">{completed}</div>
                <div class="label">{completion_rate:.1f}% Complete</div>
            </div>
            <div class="metric-card">
                <div class="label">In Progress</div>
                <div class="value">{in_progress}</div>
                <div class="label">Currently executing</div>
            </div>
            <div class="metric-card">
                <div class="label">Not Started</div>
                <div class="value">{not_started}</div>
                <div class="label">Pending execution</div>
            </div>
        </div>
        
        <h3>Execution Progress by Week</h3>
        <table>
            <thead>
                <tr>
                    <th>Week Starting</th>
                    <th>Created</th>
                    <th>Cumulative Total</th>
                </tr>
            </thead>
            <tbody>
"""
    
    for _, row in sub_exec_data['by_week'].iterrows():
        html_content += f"""                <tr>
                    <td><strong>{row['week_label']}</strong></td>
                    <td>{int(row['created'])}</td>
                    <td><strong>{int(row['cumulative'])}</strong></td>
                </tr>
"""
    
    html_content += """            </tbody>
        </table>
        
        <h3>Execution Burndown Chart</h3>
        <div style="width: 100%; height: 400px; position: relative;">
            <canvas id="burndownChart"></canvas>
        </div>
        
        <h3 style="margin-top: 30px;">Test Execution Details</h3>
        <table>
            <thead>
                <tr>
                    <th>Key</th>
                    <th>Summary</th>
                    <th>Status</th>
                    <th>Category</th>
                    <th>Created</th>
                </tr>
            </thead>
            <tbody>
"""
    
    # Add execution details sorted by status (Completed, In Progress, Not Started)
    for _, row in sub_exec_data['details'].sort_values(['category', 'created']).iterrows():
        status_class = ''
        if row['category'] == 'Completed':
            status_class = 'pass-high'
        elif row['category'] == 'In Progress':
            status_class = 'pass-medium'
        else:
            status_class = 'pass-low'
        
        html_content += f"""                <tr>
                    <td><strong>{row['key']}</strong></td>
                    <td>{row['summary'][:80]}{'...' if len(row['summary']) > 80 else ''}</td>
                    <td class="{status_class}">{row['status']}</td>
                    <td>{row['category']}</td>
                    <td>{row['created'].strftime('%Y-%m-%d')}</td>
                </tr>
"""
    
    html_content += """            </tbody>
        </table>
        
        <p style="margin-top: 20px;"><strong>Note:</strong> Sub test executions track the completion status of test execution tasks assigned for the release.</p>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        // Burndown Chart Data
        const burndownData = {
"""
    
    # Add chart data
    weeks = [f"'{row['week_label']}'" for _, row in sub_exec_data['by_week'].iterrows()]
    cumulative = [int(row['cumulative']) for _, row in sub_exec_data['by_week'].iterrows()]
    
    # Calculate completion trend by status
    status_by_week = sub_exec_data['status_by_week']
    completed_trend = []
    completion_percent = []
    
    for idx, (_, row) in enumerate(sub_exec_data['by_week'].iterrows()):
        week = row['week']
        total_at_week = int(row['cumulative'])
        
        # Get cumulative completed up to this week
        week_status = status_by_week[status_by_week['week'] <= week]
        
        if not week_status.empty:
            comp = int(week_status['Completed'].sum()) if 'Completed' in week_status.columns else 0
        else:
            comp = 0
        
        completed_trend.append(comp)
        
        # Calculate completion percentage
        if total_at_week > 0:
            pct = round((comp / total_at_week) * 100, 1)
        else:
            pct = 0
        completion_percent.append(pct)
    
    html_content += f"""            labels: [{', '.join(weeks)}],
            datasets: [
                {{
                    label: 'Completion %',
                    data: {completion_percent},
                    borderColor: 'rgb(76, 175, 80)',
                    backgroundColor: 'rgba(76, 175, 80, 0.2)',
                    borderWidth: 3,
                    fill: true,
                    yAxisID: 'y'
                }},
                {{
                    label: 'Total Executions',
                    data: {cumulative},
                    borderColor: 'rgb(102, 126, 234)',
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    yAxisID: 'y1'
                }},
                {{
                    label: 'Completed Count',
                    data: {completed_trend},
                    borderColor: 'rgb(76, 175, 80)',
                    backgroundColor: 'rgba(76, 175, 80, 0.1)',
                    borderWidth: 2,
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    yAxisID: 'y1'
                }}
            ]
        }};
        
        const config = {{
            type: 'line',
            data: burndownData,
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: 'index',
                    intersect: false
                }},
                plugins: {{
                    title: {{
                        display: true,
                        text: 'Sub Test Execution Burndown - Completion Progress',
                        font: {{ size: 16, weight: 'bold' }}
                    }},
                    legend: {{
                        display: true,
                        position: 'top'
                    }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                let label = context.dataset.label || '';
                                if (label) {{
                                    label += ': ';
                                }}
                                if (context.parsed.y !== null) {{
                                    if (context.datasetIndex === 0) {{
                                        label += context.parsed.y.toFixed(1) + '%';
                                    }} else {{
                                        label += context.parsed.y;
                                    }}
                                }}
                                return label;
                            }}
                        }}
                    }}
                }},
                scales: {{
                    y: {{
                        type: 'linear',
                        display: true,
                        position: 'left',
                        beginAtZero: true,
                        max: 100,
                        title: {{
                            display: true,
                            text: 'Completion %',
                            color: 'rgb(76, 175, 80)'
                        }},
                        ticks: {{
                            callback: function(value) {{
                                return value + '%';
                            }}
                        }}
                    }},
                    y1: {{
                        type: 'linear',
                        display: true,
                        position: 'right',
                        beginAtZero: true,
                        title: {{
                            display: true,
                            text: 'Number of Executions',
                            color: 'rgb(102, 126, 234)'
                        }},
                        grid: {{
                            drawOnChartArea: false
                        }}
                    }},
                    x: {{
                        title: {{
                            display: true,
                            text: 'Week Starting'
                        }}
                    }}
                }}
            }}
        }};
        
        const ctx = document.getElementById('burndownChart').getContext('2d');
        new Chart(ctx, config);
    </script>
"""

html_content += f"""    
    <div class="footer">
        <p>Release Readiness Report generated on {datetime.now().strftime('%B %d, %Y at %H:%M')}</p>
        <p>DefensePro {version} - Builds {builds_display}</p>
    </div>
</body>
</html>
"""

html_filename = f'{output_prefix}_Report.html'
with open(html_filename, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"✅ HTML report generated: {html_filename}")
print("\n" + "=" * 80)
print("REPORT GENERATION COMPLETE")
print("=" * 80)
