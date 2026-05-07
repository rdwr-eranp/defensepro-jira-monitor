"""
Unified Weekly Report for DefensePro
Combines weekly work summary with CI iteration automation status

Includes:
- Bug status tracking (Dev, QA, Accepted)
- Sub test execution progress with Xray data (execution rate, automation coverage)
- CI Iteration automation status (test executions, coverage, failures)
- Historical trends
"""

import os
import time
from dotenv import load_dotenv
from jira import JIRA
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import psycopg2
import html
import csv
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

# Xray Cloud API Configuration
XRAY_AUTH_URL = 'https://xray.cloud.getxray.app/api/v2/authenticate'
XRAY_GRAPHQL_URL = 'https://xray.cloud.getxray.app/api/v2/graphql'
XRAY_CLIENT_ID = os.getenv('XRAY_CLIENT_ID', '7DC37640C3B6422D91E978570801CCF8')
XRAY_CLIENT_SECRET = os.getenv('XRAY_CLIENT_SECRET', '757b92c3039c706606ee29fe74e7c9d28c0a9c80bc013f6999f5910f20d347d8')


def get_xray_token():
    """Authenticate with Xray Cloud API and return bearer token"""
    try:
        response = requests.post(
            XRAY_AUTH_URL,
            json={'client_id': XRAY_CLIENT_ID, 'client_secret': XRAY_CLIENT_SECRET},
            headers={'Content-Type': 'application/json'},
            verify=False,
            timeout=30
        )
        if response.status_code == 200:
            return response.text.strip('"')
        else:
            print(f"   ⚠️ Xray auth failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"   ⚠️ Xray auth error: {e}")
        return None


def get_xray_ids_for_sub_test_executions(jira_keys, max_pages=20):
    """
    Find Xray issueIds for a list of Jira keys by scanning Test Executions in Xray.
    Returns dict mapping jira_key -> xray_id
    """
    key_to_xray_id = {}
    start = 0
    limit = 100
    pages = 0
    
    query = """
    query($limit: Int!, $start: Int!) {
        getTestExecutions(limit: $limit, start: $start) {
            total
            results {
                issueId
                jira(fields: ["key"])
            }
        }
    }
    """
    
    target_set = set(jira_keys)
    
    while pages < max_pages:
        token = get_xray_token()
        if not token:
            break
        
        try:
            response = requests.post(
                XRAY_GRAPHQL_URL,
                json={'query': query, 'variables': {'limit': limit, 'start': start}},
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                verify=False,
                timeout=60
            )
            
            if response.status_code != 200:
                break
            
            data = response.json()
            executions = data.get('data', {}).get('getTestExecutions', {})
            results = executions.get('results', [])
            total = executions.get('total', 0)
            
            if not results:
                break
            
            for exec_data in results:
                key = exec_data.get('jira', {}).get('key')
                if key in target_set:
                    key_to_xray_id[key] = exec_data.get('issueId')
            
            # Check if we found all
            if len(key_to_xray_id) == len(target_set):
                break
            
            start += limit
            pages += 1
            
            if start >= total:
                break
                
        except Exception as e:
            print(f"   ⚠️ Error getting Xray IDs: {e}")
            break
        
        time.sleep(0.5)  # Brief pause between requests
    
    return key_to_xray_id


def get_sub_test_execution_xray_data(jira, sub_execs, version):
    """
    Query Xray Cloud API to get detailed execution data for Sub Test Executions.
    Returns a dict with:
    - executions: list of dicts with per-execution stats
    - summary: overall totals
    """
    print("   Fetching Xray data for Sub Test Executions...")
    
    # Empty default result
    empty_result = {
        'executions': [],
        'summary': {
            'total_tests': 0,
            'total_executed': 0,
            'total_passed': 0,
            'pass_ratio': 0,
            'execution_rate': 0,
            'testing_coverage': 0,
            'methods': {},
            'automation_coverage': 0,
            'automation_potential': 0,
            'automated_count': 0,
            'candidate_count': 0,
            'manual_count': 0,
            'na_count': 0,
            'automated_rate': 0,
            'candidate_rate': 0,
            'manual_rate': 0,
            'na_rate': 0
        }
    }
    
    # Get Jira keys
    jira_keys = [se.key for se in sub_execs]
    if not jira_keys:
        return empty_result
    
    # Get Xray IDs
    print(f"   Mapping {len(jira_keys)} Sub Test Executions to Xray IDs...")
    try:
        key_to_xray_id = get_xray_ids_for_sub_test_executions(jira_keys)
        print(f"   Found {len(key_to_xray_id)} Xray mappings")
    except Exception as e:
        print(f"   ⚠️ Failed to get Xray mappings: {e}")
        return empty_result
    
    if not key_to_xray_id:
        print("   ⚠️ No Xray mappings found")
        return empty_result
    
    # Query each Test Execution
    query_exec = """
    query($issueId: String!) {
        getTestExecution(issueId: $issueId) {
            issueId
            jira(fields: ["key", "summary"])
            testRuns(limit: 100) {
                total
                results {
                    status { name }
                    test {
                        issueId
                        jira(fields: ["key"])
                    }
                }
            }
        }
    }
    """
    
    executions = []
    all_test_keys = set()
    processed = 0
    
    for se in sub_execs:
        jira_key = se.key
        xray_id = key_to_xray_id.get(jira_key)
        processed += 1
        
        exec_data = {
            'key': jira_key,
            'summary': se.fields.summary[:50] + '...' if len(se.fields.summary) > 50 else se.fields.summary,
            'jira_status': se.fields.status.name,
            'tests': 0,
            'executed': 0,
            'statuses': {},
            'methods': {},
            'test_keys': []
        }
        
        if not xray_id:
            executions.append(exec_data)
            continue
        
        print(f"   [{processed}/{len(sub_execs)}] Querying {jira_key}...", end='', flush=True)
        
        # Query Xray with shorter timeout
        for attempt in range(2):  # Reduce retry attempts
            try:
                token = get_xray_token()
                if not token:
                    print(" auth failed")
                    break
                
                response = requests.post(
                    XRAY_GRAPHQL_URL,
                    json={'query': query_exec, 'variables': {'issueId': xray_id}},
                    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                    verify=False,
                    timeout=15  # Shorter timeout
                )
                
                if response.status_code != 200:
                    print(f" HTTP {response.status_code}")
                    continue
                
                data = response.json()
                if 'errors' in data:
                    print(" API error")
                    continue
                
                te_data = data.get('data', {}).get('getTestExecution')
                if not te_data:
                    print(" no data")
                    break
                
                test_runs = te_data.get('testRuns', {})
                exec_data['tests'] = test_runs.get('total', 0)
                
                for run in test_runs.get('results', []):
                    status = run.get('status', {}).get('name', 'Unknown')
                    test = run.get('test', {})
                    test_key = test.get('jira', {}).get('key') if test else None
                    
                    exec_data['statuses'][status] = exec_data['statuses'].get(status, 0) + 1
                    
                    # Count executed (not TO DO)
                    if status.upper() not in ['TO DO', 'TODO']:
                        exec_data['executed'] += 1
                    
                    if test_key:
                        exec_data['test_keys'].append(test_key)
                        all_test_keys.add(test_key)
                
                print(f" {exec_data['tests']} tests, {exec_data['executed']} executed")
                break  # Success
                
            except requests.exceptions.Timeout:
                print(" timeout", end='')
                time.sleep(1)
            except Exception as e:
                print(f" error: {str(e)[:30]}", end='')
                time.sleep(1)
        
        executions.append(exec_data)
        time.sleep(0.3)  # Brief pause
    
    # Get Rally Test Method from Jira for all unique tests
    print(f"   Getting Rally Test Method from Jira for {len(all_test_keys)} unique tests...")
    test_methods = {}
    
    for test_key in list(all_test_keys)[:200]:  # Limit to avoid too many API calls
        try:
            issue = jira.issue(test_key, fields='customfield_10154')
            method = getattr(issue.fields, 'customfield_10154', None)
            if method and hasattr(method, 'value'):
                test_methods[test_key] = method.value
            else:
                test_methods[test_key] = 'NA'
        except Exception:
            test_methods[test_key] = 'NA'
    
    # Update executions with methods
    all_methods = Counter()
    for exec_data in executions:
        exec_methods = Counter()
        for test_key in exec_data['test_keys']:
            method = test_methods.get(test_key, 'NA')
            exec_methods[method] += 1
        exec_data['methods'] = dict(exec_methods)
        all_methods.update(exec_methods)
    
    # Calculate summary with detailed automation metrics
    total_tests = sum(e['tests'] for e in executions)
    total_executed = sum(e['executed'] for e in executions)
    total_with_methods = sum(all_methods.values()) if all_methods else 0
    
    # Calculate total passed from all executions
    total_passed = 0
    for e in executions:
        statuses = e.get('statuses', {})
        total_passed += statuses.get('PASSED', 0) + statuses.get('Passed', 0) + statuses.get('PASS', 0)
    
    automated_count = all_methods.get('Automated', 0)
    candidate_count = all_methods.get('Automation Candidate', 0)
    manual_count = all_methods.get('Manual', 0)
    na_count = all_methods.get('NA', 0)
    
    # Calculate rates (excluding NA from automation potential calculation)
    tests_with_method = automated_count + candidate_count + manual_count
    
    summary = {
        'total_tests': total_tests,
        'total_executed': total_executed,
        'total_passed': total_passed,
        'pass_ratio': (total_passed / total_executed * 100) if total_executed > 0 else 0,
        'testing_coverage': (total_executed / total_tests * 100) if total_tests > 0 else 0,
        'methods': dict(all_methods),
        # Method counts
        'automated_count': automated_count,
        'candidate_count': candidate_count,
        'manual_count': manual_count,
        'na_count': na_count,
        # Method rates (as percentage of total tests with method info)
        'automated_rate': (automated_count / total_with_methods * 100) if total_with_methods > 0 else 0,
        'candidate_rate': (candidate_count / total_with_methods * 100) if total_with_methods > 0 else 0,
        'manual_rate': (manual_count / total_with_methods * 100) if total_with_methods > 0 else 0,
        'na_rate': (na_count / total_with_methods * 100) if total_with_methods > 0 else 0,
        # Automation metrics (coverage = automated / automatable; potential = automatable / total)
        'automation_coverage': (automated_count / (automated_count + candidate_count) * 100) if (automated_count + candidate_count) > 0 else 0,
        'automation_potential': ((automated_count + candidate_count) / total_tests * 100) if total_tests > 0 else 0,
        # Legacy field for compatibility
        'execution_rate': (total_executed / total_tests * 100) if total_tests > 0 else 0,
    }
    
    print(f"   ✓ Xray data: {total_tests} tests, {total_executed} executed ({summary['testing_coverage']:.1f}%)")
    print(f"   ✓ Automation: {automated_count} automated, {candidate_count} candidates, {manual_count} manual")
    
    return {'executions': executions, 'summary': summary}

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

def get_test_method_distribution(jira, version):
    """
    Get test method distribution for Tests related to sub test executions.
    Reads from pre-generated CSV file if available, otherwise queries Jira directly.
    
    Tests have a Method field (customfield_10154) with values:
    - Automated
    - Manual  
    - Automation Candidate
    - Not Specified (null/empty)
    """
    csv_file = f"test_method_distribution_sub_exec_topics_{version.replace('.', '_')}.csv"
    
    # Try to read from pre-generated CSV first
    if os.path.exists(csv_file):
        print(f"   Loading test method data from {csv_file}...")
        tests_data = []
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                tests_data = list(reader)
            
            # Count by method
            method_counts = Counter()
            executed_by_method = Counter()
            not_executed_by_method = Counter()
            
            for test in tests_data:
                method = test.get('Method', 'Not Specified') or 'Not Specified'
                status = test.get('Status', 'Unknown')
                ref_count = int(test.get('Referenced By Executions', 0) or 0)
                
                method_counts[method] += 1
                if ref_count > 0:
                    executed_by_method[method] += 1
                else:
                    not_executed_by_method[method] += 1
            
            return {
                'total_tests': len(tests_data),
                'by_method': dict(method_counts),
                'executed_by_method': dict(executed_by_method),
                'not_executed_by_method': dict(not_executed_by_method),
                'source': 'csv'
            }
        except Exception as e:
            print(f"   ⚠️ Error reading CSV: {e}")
    
    # Fallback: query Tests directly from Jira
    print(f"   Querying Tests from Jira...")
    try:
        # Get Tests that have been associated with this version's test executions
        # Note: Tests don't have fixVersion, so we query all Tests and count by method
        tests = jira.search_issues(
            'project = DP AND type = Test AND status != Trash',
            maxResults=500,
            fields='summary,status,customfield_10154'
        )
        
        method_counts = Counter()
        for test in tests:
            method = getattr(test.fields, 'customfield_10154', None)
            method_val = method.value if method and hasattr(method, 'value') else 'Not Specified'
            method_counts[method_val] += 1
        
        return {
            'total_tests': len(tests),
            'by_method': dict(method_counts),
            'executed_by_method': {},  # Not available from direct query
            'not_executed_by_method': {},
            'source': 'jira'
        }
    except Exception as e:
        print(f"   ⚠️ Error querying Jira: {e}")
        return {
            'total_tests': 0,
            'by_method': {},
            'executed_by_method': {},
            'not_executed_by_method': {},
            'source': 'error'
        }

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

def get_builds_for_version(conn, version, sprint_start, sprint_end):
    """Auto-detect builds for a version within the sprint date range.
    Falls back to the most recent builds for the version if none are found in the sprint window."""
    query = f"""
        SELECT DISTINCT build
        FROM test_execution
        WHERE version = '{version}'
          AND mode = 'regression'
          AND start_time BETWEEN '{sprint_start}' AND '{sprint_end}'
        ORDER BY build
    """
    df = pd.read_sql(query, conn)
    if not df.empty:
        builds = df['build'].tolist()
        return ','.join([str(b) for b in builds])

    # Fallback: no builds in the sprint window — return the most recent builds for this version
    print(f"   ⚠️  No builds found for {version} in sprint window; falling back to most recent builds for this version...")
    fallback_query = f"""
        SELECT DISTINCT build
        FROM test_execution
        WHERE version = '{version}'
          AND mode = 'regression'
        ORDER BY build DESC
        LIMIT 10
    """
    fb_df = pd.read_sql(fallback_query, conn)
    if fb_df.empty:
        return None
    builds = fb_df['build'].tolist()
    print(f"   Fallback builds: {builds}")
    return ','.join([str(b) for b in builds])


def get_sprint_list(jira, n_closed=4):
    """
    Return the last n_closed closed sprints for the DP board plus the current
    active sprint.  Each entry is a dict with keys: name, startDate, endDate, state.
    Sorted chronologically (oldest first). Returns [] on any error.
    """
    try:
        boards = jira.boards()
        board_id = None
        # Prefer board whose active sprint name starts with 'DP-'
        for board in boards:
            try:
                active = jira.sprints(board.id, state='active')
                if active and active[0].name.startswith('DP-'):
                    board_id = board.id
                    break
            except Exception:
                continue
        # Fallback: match board name
        if not board_id:
            for board in boards:
                if 'DP' in board.name or 'DefensePro' in board.name:
                    board_id = board.id
                    break
        if not board_id:
            return []

        closed_sprints = jira.sprints(board_id, state='closed')
        # Sort closed sprints by end date descending, take last n_closed
        def _end(s):
            return getattr(s, 'endDate', '') or ''

        closed_sorted = sorted(closed_sprints, key=_end, reverse=True)[:n_closed]
        closed_sorted = sorted(closed_sorted, key=_end)  # oldest first

        active_sprints = jira.sprints(board_id, state='active')
        all_sprints = closed_sorted + (active_sprints[:1] if active_sprints else [])

        result = []
        for s in all_sprints:
            result.append({
                'name': s.name,
                'startDate': getattr(s, 'startDate', '') or '',
                'endDate': getattr(s, 'endDate', '') or '',
                'state': getattr(s, 'state', 'unknown'),
            })
        return result
    except Exception as e:
        print(f"   ⚠️ Could not fetch sprint list: {e}")
        return []


def get_ci_sprint_history(conn, version, sprint_list, prev_version=None):
    """
    For each sprint in sprint_list compute CI metrics from the postgres DB.
    Returns a list of dicts (one per sprint):
        {sprint_name, start_date, end_date, coverage, pass_ratio,
         tests_executed, passed, failed}
    Sprints with no DB data are skipped.
    """
    if prev_version is None:
        prev_version = get_previous_version(version)

    # Baseline test count per platform_type_mode from previous release
    baseline_query = f"""
        SELECT COUNT(DISTINCT te.test_id) AS baseline_count
        FROM test_execution te
        WHERE te.version = '{prev_version}'
          AND te.mode = 'regression'
    """
    try:
        baseline_df = pd.read_sql(baseline_query, conn)
        baseline_total = int(baseline_df['baseline_count'].iloc[0]) if not baseline_df.empty else 0
    except Exception:
        baseline_total = 0

    history = []
    for sprint in sprint_list:
        s_start = sprint.get('startDate', '')[:19]
        s_end   = sprint.get('endDate', '')[:19]
        if not s_start or not s_end:
            continue
        try:
            metrics_query = f"""
                SELECT
                    COUNT(DISTINCT te.test_id) AS tests_executed,
                    SUM(CASE WHEN LOWER(te.status) = 'passed' THEN 1 ELSE 0 END) AS passed,
                    SUM(CASE WHEN LOWER(te.status) IN ('failed','error','fail') THEN 1 ELSE 0 END) AS failed
                FROM test_execution te
                WHERE te.version = '{version}'
                  AND te.mode = 'regression'
                  AND te.start_time BETWEEN '{s_start}' AND '{s_end}'
            """
            df = pd.read_sql(metrics_query, conn)
            if df.empty or df['tests_executed'].iloc[0] == 0:
                continue
            tests_executed = int(df['tests_executed'].iloc[0])
            passed = int(df['passed'].iloc[0] or 0)
            failed = int(df['failed'].iloc[0] or 0)
            total_executions = passed + failed
            coverage = min(tests_executed / max(baseline_total, 1) * 100, 100.0)
            pass_ratio = passed / max(total_executions, 1) * 100
            history.append({
                'sprint_name':     sprint['name'],
                'start_date':      s_start[:10],
                'end_date':        s_end[:10],
                'state':           sprint.get('state', ''),
                'tests_executed':  tests_executed,
                'passed':          passed,
                'failed':          failed,
                'coverage':        round(coverage, 1),
                'pass_ratio':      round(pass_ratio, 1),
            })
        except Exception as e:
            print(f"   ⚠️ CI history query failed for sprint '{sprint['name']}': {e}")
            continue
    return history


def get_sub_exec_sprint_history(jira, version, sprint_list):
    """
    For each sprint in sprint_list query Jira to get sub test execution
    completion snapshot at the sprint end date.
    Strategy: count sub execs resolved (Done/Accepted/Complete) on or before
    sprint_end, and all sub execs created on or before sprint_end, to derive
    a completion % snapshot per sprint.
    Returns a list of dicts (one per sprint):
        {sprint_name, start_date, end_date, total, completed, in_progress,
         not_started, completion_pct}
    """
    history = []
    base_jql = (
        f'project = DP AND fixVersion = "{version}" '
        f'AND type = "sub test execution" '
        f'AND status != Trash'
    )
    for sprint in sprint_list:
        s_end = sprint.get('endDate', '')[:10]
        s_start = sprint.get('startDate', '')[:10]
        if not s_end:
            continue
        try:
            # Total sub execs created by sprint end
            total_jql = base_jql + f' AND created <= "{s_end}"'
            total_issues = jira.search_issues(total_jql, maxResults=False,
                                              fields='status', json_result=True)
            total = total_issues.get('total', 0)
            if total == 0:
                continue

            completed_jql = base_jql + (
                f' AND status in (Done, Accepted, Complete) AND resolved <= "{s_end}"'
            )
            completed_issues = jira.search_issues(completed_jql, maxResults=False,
                                                  fields='status', json_result=True)
            completed = completed_issues.get('total', 0)

            in_progress_jql = base_jql + (
                f' AND status = "In Progress" AND created <= "{s_end}"'
            )
            in_progress_issues = jira.search_issues(in_progress_jql, maxResults=False,
                                                    fields='status', json_result=True)
            in_progress = in_progress_issues.get('total', 0)

            not_started = max(total - completed - in_progress, 0)
            completion_pct = round(completed / max(total, 1) * 100, 1)

            history.append({
                'sprint_name':    sprint['name'],
                'start_date':     s_start,
                'end_date':       s_end,
                'state':          sprint.get('state', ''),
                'total':          total,
                'completed':      completed,
                'in_progress':    in_progress,
                'not_started':    not_started,
                'completion_pct': completion_pct,
            })
        except Exception as e:
            print(f"   ⚠️ Sub exec history query failed for sprint '{sprint['name']}': {e}")
            continue
    return history


def get_previous_version(version):
    """Derive the previous release version by decrementing the minor number (e.g., 10.13.0.0 → 10.12.0.0)"""
    parts = version.split('.')
    parts[1] = str(int(parts[1]) - 1)
    return '.'.join(parts)


def _version_tuple(version):
    """Convert version string like '10.14.0.0' to a tuple of ints for comparison."""
    return tuple(int(x) for x in version.split('.'))


def get_coverage_progress(conn, version, ci_run_start):
    """
    Calculate daily cumulative coverage progress since CI run start date.
    Returns a dict with daily breakdown, pass ratio, and completion estimation.
    """
    if not conn or not ci_run_start:
        return None

    prev_version = get_previous_version(version)
    qdos_filter = "AND LOWER(t.name) NOT LIKE '%qdos%'" if _version_tuple(version) >= (10, 14, 0, 0) else ""

    try:
        baseline_query = f"""
            SELECT 
                CASE WHEN d.platform IN ('UHT','MRQP','MR2') THEN 'FPGA'
                     WHEN d.platform IN ('ESXI','KVM','VL3','HT2') THEN 'Software'
                     WHEN d.platform IN ('MRQ_X','MRQX') THEN 'EZchip' ELSE 'Other' END as platform_type,
                CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END as mode,
                COUNT(DISTINCT te.test_id) as available_tests
            FROM test_execution te
            JOIN device d ON te.device_id = d.id
            JOIN profile p ON te.profile_id = p.id
            JOIN test t ON te.test_id = t.id
            WHERE te.version = '{prev_version}' AND te.mode = 'regression'
              AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
              {qdos_filter}
            GROUP BY 1, 2
        """
        baseline_df = pd.read_sql(baseline_query, conn)
        baseline_total = baseline_df[baseline_df['platform_type'] != 'Other']['available_tests'].sum()

        if baseline_total == 0:
            return None

        daily_query = f"""
            SELECT te.start_time::date as run_date,
                   COUNT(DISTINCT te.test_id) as unique_tests,
                   COUNT(*) as total_executions,
                   SUM(CASE WHEN LOWER(te.status) = 'passed' THEN 1 ELSE 0 END) as passed,
                   SUM(CASE WHEN LOWER(te.status) IN ('failed','error','fail') THEN 1 ELSE 0 END) as failed
            FROM test_execution te
            JOIN test t ON te.test_id = t.id
            WHERE te.version = '{version}' AND te.mode = 'regression'
              AND te.start_time >= '{ci_run_start}'
              {qdos_filter}
            GROUP BY te.start_time::date
            ORDER BY run_date
        """
        daily_df = pd.read_sql(daily_query, conn)

        if daily_df.empty:
            return None

        cumulative_query = f"""
            SELECT d.run_date, COUNT(DISTINCT sub.test_id || '-' || sub.platform_type || '-' || sub.mode) as cumulative_pt_tests
            FROM (SELECT DISTINCT start_time::date as run_date FROM test_execution
                  WHERE version = '{version}' AND mode = 'regression'
                  AND start_time >= '{ci_run_start}') d
            CROSS JOIN LATERAL (
                SELECT DISTINCT te.test_id,
                    CASE WHEN dev.platform IN ('UHT','MRQP','MR2') THEN 'FPGA'
                         WHEN dev.platform IN ('ESXI','KVM','VL3','HT2') THEN 'Software'
                         WHEN dev.platform IN ('MRQ_X','MRQX') THEN 'EZchip' ELSE 'Other' END as platform_type,
                    CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END as mode
                FROM test_execution te
                JOIN device dev ON te.device_id = dev.id
                JOIN profile p ON te.profile_id = p.id
                JOIN test t ON te.test_id = t.id
                WHERE te.version = '{version}' AND te.mode = 'regression'
                  AND te.start_time >= '{ci_run_start}'
                  AND te.start_time < (d.run_date + interval '1 day')
                  AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
                  {qdos_filter}
                  AND dev.platform IN ('UHT','MRQP','MR2','ESXI','KVM','VL3','HT2','MRQ_X','MRQX')
            ) sub
            GROUP BY d.run_date ORDER BY d.run_date
        """
        cumulative_df = pd.read_sql(cumulative_query, conn)

        if cumulative_df.empty:
            return None

        days = []
        prev_cum = 0
        cumulative_passed = 0
        cumulative_failed = 0
        for i, row in cumulative_df.iterrows():
            cum = int(row['cumulative_pt_tests'])
            delta = cum - prev_cum
            coverage_pct = cum / baseline_total * 100
            daily_add_pct = delta / baseline_total * 100

            date_str = str(row['run_date'])
            day_row = daily_df[daily_df['run_date'].astype(str) == date_str]
            if not day_row.empty:
                day_passed = int(day_row['passed'].iloc[0] or 0)
                day_failed = int(day_row['failed'].iloc[0] or 0)
            else:
                day_passed = 0
                day_failed = 0

            cumulative_passed += day_passed
            cumulative_failed += day_failed
            cumulative_total = cumulative_passed + cumulative_failed
            cum_pass_ratio = (cumulative_passed / cumulative_total * 100) if cumulative_total > 0 else 0

            days.append({
                'date': date_str,
                'cumulative_tests': cum,
                'new_tests': delta,
                'coverage_pct': round(coverage_pct, 1),
                'daily_add_pct': round(daily_add_pct, 1),
                'day_passed': day_passed,
                'day_failed': day_failed,
                'cumulative_pass_ratio': round(cum_pass_ratio, 1),
            })
            prev_cum = cum

        current_coverage = days[-1]['coverage_pct'] if days else 0
        current_pass_ratio = days[-1]['cumulative_pass_ratio'] if days else 0
        remaining = 100.0 - current_coverage

        full_days = days[:-1] if len(days) > 1 else days
        if full_days:
            avg_daily_rate = sum(d['daily_add_pct'] for d in full_days) / len(full_days)
        else:
            avg_daily_rate = days[0]['daily_add_pct'] if days else 0

        if avg_daily_rate > 0:
            days_to_complete = remaining / avg_daily_rate
            estimated_date = datetime.now() + timedelta(days=int(days_to_complete) + 1)
        else:
            days_to_complete = None
            estimated_date = None

        return {
            'ci_run_start': ci_run_start,
            'baseline_total': int(baseline_total),
            'prev_version': prev_version,
            'days': days,
            'current_coverage': current_coverage,
            'current_pass_ratio': current_pass_ratio,
            'remaining': round(remaining, 1),
            'avg_daily_rate': round(avg_daily_rate, 1),
            'days_to_complete': int(days_to_complete) + 1 if days_to_complete else None,
            'estimated_date': estimated_date.strftime('%Y-%m-%d') if estimated_date else None,
            'total_days_elapsed': len(days),
        }
    except Exception as e:
        print(f"   ⚠️ Coverage progress query failed: {e}")
        return None


def get_build_changelogs(builds_str):
    """
    Fetch changelogs (commit messages) from Jenkins for each build number.
    Requires JENKINS_BUILD_URL, JENKINS_BUILD_JOB, JENKINS_BUILD_USER, JENKINS_BUILD_TOKEN in .env.
    Returns a list of dicts: [{build, changes: [{msg, author, date, commitId}]}]
    """
    jenkins_url = os.getenv('JENKINS_BUILD_URL', '').strip().rstrip('/')
    jenkins_job = os.getenv('JENKINS_BUILD_JOB', '').strip()
    jenkins_user = os.getenv('JENKINS_BUILD_USER', '').strip()
    jenkins_token = os.getenv('JENKINS_BUILD_TOKEN', '').strip()

    if not jenkins_url or not jenkins_job:
        return None

    if not builds_str:
        return None

    build_numbers = [b.strip() for b in builds_str.split(',') if b.strip()]
    auth = (jenkins_user, jenkins_token) if jenkins_user and jenkins_token else None

    results = []
    for build_num in build_numbers:
        try:
            url = f"{jenkins_url}/job/{jenkins_job}/{build_num}/api/json"
            params = {'tree': 'changeSets[items[msg,author[fullName],commitId]],changeSet[items[msg,author[fullName],commitId]],timestamp,result,displayName'}
            resp = requests.get(url, params=params, auth=auth, timeout=15, verify=False)
            if resp.status_code != 200:
                continue
            data = resp.json()
            changes = []
            # Pipeline jobs use changeSets (plural), freestyle uses changeSet (singular)
            change_sets = data.get('changeSets', [])
            if not change_sets:
                cs = data.get('changeSet')
                if cs:
                    change_sets = [cs]
            for cs in change_sets:
                for item in cs.get('items', []):
                    changes.append({
                        'msg': item.get('msg', '').split('\n')[0][:120],
                        'author': item.get('author', {}).get('fullName', 'Unknown'),
                        'commitId': item.get('commitId', '')[:8],
                    })
            build_info = {
                'build': build_num,
                'displayName': data.get('displayName', f'#{build_num}'),
                'result': data.get('result', 'N/A'),
                'timestamp': data.get('timestamp'),
                'changes': changes,
            }
            results.append(build_info)
        except Exception as e:
            print(f"   ⚠️ Failed to fetch changelog for build {build_num}: {e}")
            continue

    return results if results else None


def generate_build_changelog_html(build_changelogs):
    """Generate HTML section for build changelogs."""
    if not build_changelogs:
        return ""

    total_changes = sum(len(b['changes']) for b in build_changelogs)
    if total_changes == 0:
        return ""

    html = '''
    <div style="background: #f3e5f5; border-left: 5px solid #7b1fa2; padding: 20px; margin: 20px 0; border-radius: 5px;">
        <h3 style="margin-top: 0; color: #7b1fa2;">🔧 Build Changes in CI Cycle</h3>
        <p style="font-size: 13px; color: #555;">'''
    html += f'{total_changes} change(s) across {len(build_changelogs)} build(s)</p>'

    for build in build_changelogs:
        ts = ''
        if build.get('timestamp'):
            ts = datetime.fromtimestamp(build['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M')
        result_color = '#4caf50' if build['result'] == 'SUCCESS' else '#f44336' if build['result'] == 'FAILURE' else '#ff9800'
        html += f'<details style="margin: 8px 0;"><summary style="cursor: pointer; font-weight: bold;">'
        html += f'Build {build["displayName"]} <span style="color: {result_color};">({build["result"]})</span>'
        if ts:
            html += f' - {ts}'
        html += f' — {len(build["changes"])} change(s)</summary>'
        if build['changes']:
            html += '<ul style="margin: 5px 0; font-size: 13px;">'
            for c in build['changes']:
                commit_msg = c["msg"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                author_name = c["author"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html += f'<li><code>{c["commitId"]}</code> {commit_msg} <em>({author_name})</em></li>'
            html += '</ul>'
        else:
            html += '<p style="font-size: 13px; color: #888; margin: 5px 0 5px 20px;">No changes recorded</p>'
        html += '</details>'
    html += '</div>'
    return html


def get_automation_data(conn, jira, version, builds, sprint_start, sprint_end):
    """Get automation test data for the sprint period"""
    # builds are integers in the database, don't quote them
    builds_str = ','.join([b.strip() for b in builds.split(',')]) if builds else ''
    prev_version = get_previous_version(version)

    # QDoS feature removed from DP starting 10.14.0.0 - exclude from all queries
    qdos_filter = "AND LOWER(t.name) NOT LIKE '%qdos%'" if _version_tuple(version) >= (10, 14, 0, 0) else ""
    qdos_filter_no_t = "AND LOWER(t2.name) NOT LIKE '%qdos%'" if _version_tuple(version) >= (10, 14, 0, 0) else ""

    # Get tests executed: prefer filtering by build number (more reliable across sprint boundaries),
    # fall back to sprint date range when no builds are known.
    if builds_str:
        tests_query = f"""
            SELECT DISTINCT te.test_id
            FROM test_execution te
            JOIN test t2 ON te.test_id = t2.id
            WHERE te.version = '{version}'
              AND te.build IN ({builds_str})
              AND te.mode = 'regression'
              {qdos_filter_no_t}
        """
    else:
        tests_query = f"""
            SELECT DISTINCT te.test_id
            FROM test_execution te
            JOIN test t2 ON te.test_id = t2.id
            WHERE te.version = '{version}'
              AND te.start_time BETWEEN '{sprint_start}' AND '{sprint_end}'
              AND te.mode = 'regression'
              {qdos_filter_no_t}
        """
    tests_df = pd.read_sql(tests_query, conn)
    test_ids = tests_df['test_id'].tolist()
    
    if not test_ids:
        # Return structure with all 6 platform type combinations showing zero data
        all_platform_types = ['EZchip', 'FPGA', 'Software']
        all_modes = ['Routing', 'Transparent']
        all_combinations = [f"{pt} - {mode}" for pt in all_platform_types for mode in all_modes]
        
        empty_platform_type_data = [{
            'platform_type_mode': combo,
            'tests': 0,
            'available_tests': 0,
            'coverage': 0,
            'executions': 0,
            'passed': 0,
            'failed': 0,
            'pass_ratio': 0,
            'new_tests': 0,
            'new_tests_passed': 0,
            'new_tests_failed': 0
        } for combo in all_combinations]
        
        return {
            'total_tests': 0,
            'total_executions': 0,
            'passed': 0,
            'failed': 0,
            'pass_ratio': 0,
            'overall_coverage': 0,
            'new_tests_total': 0,
            'prev_version': prev_version,
            'platform_data': [],
            'platform_type_data': empty_platform_type_data,
            'critical_failures': 0,
            'failed_tests': [],
            'automation_bugs': [],
            'automation_bugs_count': 0
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
              AND te.version = '{version}'
              AND te.build IN ({builds_str})
              AND te.mode = 'regression'
              AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
              {qdos_filter}
        )
        SELECT test_id, test_name, platform, status, build, mode
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
        'MRQ_X': 'EZchip', 'MRQX': 'EZchip'
    }
    executions_df['platform_type'] = executions_df['platform'].map(platform_type_map)
    executions_df['platform_type_mode'] = executions_df['platform_type'] + ' - ' + executions_df['mode']

    # Deduplicate per (test_id, platform_type, mode) for platform-type breakdown.
    # When the same test ran on multiple devices of the same type (e.g. ESXI + KVM = Software),
    # keep only the most recent build's result to avoid double-counting.
    pt_dedup_df = (
        executions_df
        .sort_values('build', ascending=False)
        .drop_duplicates(subset=['test_id', 'platform_type', 'mode'])
    )

    # Identify new tests: test_ids that did NOT exist in the previous release
    baseline_ids_query = f"""
        SELECT DISTINCT te.test_id
        FROM test_execution te
        WHERE te.version = '{prev_version}'
          AND te.mode = 'regression'
    """
    baseline_ids_df = pd.read_sql(baseline_ids_query, conn)
    baseline_test_ids = set(baseline_ids_df['test_id'].tolist())

    # Split deduplicated results into legacy tests (in baseline) and new tests (not in baseline)
    pt_dedup_df['is_new_test'] = ~pt_dedup_df['test_id'].isin(baseline_test_ids)
    legacy_pt_dedup_df = pt_dedup_df[~pt_dedup_df['is_new_test']]
    new_pt_dedup_df = pt_dedup_df[pt_dedup_df['is_new_test']]

    # Calculate statistics
    stats = {
        'total_tests': len(test_ids),
        'total_executions': len(executions_df),
        'passed': len(executions_df[executions_df['status_lower'] == 'passed']),
        'failed': len(executions_df[executions_df['status_lower'].isin(['failed', 'error', 'fail'])]),
        'pass_ratio': len(executions_df[executions_df['status_lower'] == 'passed']) / max(len(executions_df), 1) * 100
    }
    
    # Get available tests for coverage calculation (from 10.12.0.0 and 10.11.0.0)
    # Count unique test cases per platform_type and mode (not per platform)
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
        WHERE te.version = '{prev_version}'
          AND te.mode = 'regression'
          AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
          {qdos_filter}
        GROUP BY 
               CASE 
                   WHEN d.platform IN ('UHT', 'MRQP', 'MR2') THEN 'FPGA'
                   WHEN d.platform IN ('ESXI', 'KVM', 'VL3', 'HT2') THEN 'Software'
                   WHEN d.platform IN ('MRQ_X', 'MRQX') THEN 'EZchip'
                   ELSE 'Other'
               END,
               CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END
    """
    available_df = pd.read_sql(available_tests_query, conn)
    available_df['platform_type_mode'] = available_df['platform_type'] + ' - ' + available_df['mode']
    
    # Platform Type + Mode breakdown (aggregated) with coverage
    # Define all possible combinations to ensure table always shows all rows
    all_platform_types = ['EZchip', 'FPGA', 'Software']
    all_modes = ['Routing', 'Transparent']
    all_combinations = [f"{pt} - {mode}" for pt in all_platform_types for mode in all_modes]
    
    platform_type_stats = []
    for pt_mode in all_combinations:
        # Legacy tests: those present in the previous release baseline (used for coverage)
        if len(legacy_pt_dedup_df) > 0 and pt_mode in legacy_pt_dedup_df['platform_type_mode'].values:
            pt_df = legacy_pt_dedup_df[legacy_pt_dedup_df['platform_type_mode'] == pt_mode]
            passed_count = len(pt_df[pt_df['status_lower'] == 'passed'])
            failed_count = len(pt_df[pt_df['status_lower'].isin(['failed', 'error', 'fail'])])
            unique_tests = len(pt_df)
            executions_count = unique_tests
        else:
            passed_count = 0
            failed_count = 0
            unique_tests = 0
            executions_count = 0

        # New tests: added in this release, not present in previous release
        if len(new_pt_dedup_df) > 0 and pt_mode in new_pt_dedup_df['platform_type_mode'].values:
            pt_new_df = new_pt_dedup_df[new_pt_dedup_df['platform_type_mode'] == pt_mode]
            new_tests_count = len(pt_new_df)
            new_tests_passed = len(pt_new_df[pt_new_df['status_lower'] == 'passed'])
            new_tests_failed = len(pt_new_df[pt_new_df['status_lower'].isin(['failed', 'error', 'fail'])])
        else:
            new_tests_count = 0
            new_tests_passed = 0
            new_tests_failed = 0
        
        # Calculate coverage against previous release baseline only
        available_tests = available_df[available_df['platform_type_mode'] == pt_mode]['available_tests'].sum()
        coverage = min((unique_tests / max(available_tests, 1)) * 100, 100.0) if available_tests > 0 else 0
        
        platform_type_stats.append({
            'platform_type_mode': pt_mode,
            'tests': unique_tests,
            'available_tests': int(available_tests),
            'coverage': coverage,
            'executions': executions_count,
            'passed': passed_count,
            'failed': failed_count,
            'pass_ratio': passed_count / max(unique_tests, 1) * 100 if unique_tests > 0 else 0,
            'new_tests': new_tests_count,
            'new_tests_passed': new_tests_passed,
            'new_tests_failed': new_tests_failed,
        })
    
    stats['platform_type_data'] = platform_type_stats
    
    # Calculate overall coverage
    if platform_type_stats:
        total_executed = sum(p['tests'] for p in platform_type_stats)
        total_available = sum(p['available_tests'] for p in platform_type_stats)
        stats['overall_coverage'] = min((total_executed / max(total_available, 1)) * 100, 100.0)
    else:
        stats['overall_coverage'] = 0

    stats['new_tests_total'] = sum(p['new_tests'] for p in platform_type_stats)
    stats['prev_version'] = prev_version
    
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
              AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
              {qdos_filter}
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
        AND status != Trash
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

def get_bug_status_at_date(issue, target_date):
    """
    Determine bug status category at a specific date by examining changelog
    Returns: 'dev', 'qa', 'closed', or 'not_created'
    """
    from datetime import datetime
    
    # Ensure target_date is a date object
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    
    # Check if bug was created before target date
    created_date = datetime.strptime(issue.fields.created[:10], '%Y-%m-%d').date()
    if created_date > target_date:
        return 'not_created'
    
    # Replay changelog to find status at target_date
    status_at_date = 'None'  # Default initial status
    
    changelog = issue.changelog
    if hasattr(changelog, 'histories'):
        # Sort chronologically (critical for accuracy)
        sorted_histories = sorted(changelog.histories, key=lambda h: h.created)
        
        for history in sorted_histories:
            change_date = datetime.strptime(history.created[:19], '%Y-%m-%dT%H:%M:%S').date()
            
            if change_date > target_date:
                break
            
            for item in history.items:
                if item.field == 'status':
                    status_at_date = item.toString
    
    # Categorize
    status_lower = status_at_date.lower()
    if 'accepted' in status_lower:
        return 'closed'
    elif 'completed' in status_lower:
        return 'qa'
    elif any(s in status_lower for s in ['in progress', 'to do', 'to-do', 'none', 'open']):
        return 'dev'
    else:
        return 'dev'

def get_cross_release_distribution(jira):
    """
    Fetch all currently open bugs (Dev + QA) across every active (unreleased,
    non-archived) DP fix version and return a distribution dict:
        { version_name: {'High': int, 'Medium': int, 'Low': int} }
    This gives the full picture for the 'Open Bugs Distribution Across Releases'
    chart, regardless of which single version the weekly report is generated for.
    """
    print("Fetching open bugs across all active releases for distribution chart...")
    try:
        # Single query: open bugs on any unreleased version, excluding DP Runners
        jql = (
            "project = DP AND issuetype = Bug "
            "AND status NOT IN (Accepted, Closed, Trash) "
            "AND fixVersion in unreleasedVersions() "
            'AND fixVersion != "10.100.0.0" '
            "ORDER BY fixVersion ASC, priority DESC"
        )
        all_open_bugs = jira.search_issues(
            jql, maxResults=False,
            fields="key,priority,status,fixVersions,customfield_10129"
        )

        dist = {}
        skipped = 0
        for bug in all_open_bugs:
            # Skip DP Runners team
            team = getattr(bug.fields, 'customfield_10129', None)
            if team:
                team_name = team.value if hasattr(team, 'value') else str(team)
                if team_name == 'DP Runners':
                    skipped += 1
                    continue

            priority = (
                bug.fields.priority.name
                if hasattr(bug.fields, 'priority') and bug.fields.priority
                else 'None'
            )

            status_name = bug.fields.status.name.lower() if hasattr(bug.fields, 'status') else ''
            phase = 'qa' if 'completed' in status_name else 'dev'

            fix_versions = bug.fields.fixVersions
            version_names = [v.name for v in fix_versions] if fix_versions else ['Unassigned']

            for ver in version_names:
                if ver not in dist:
                    dist[ver] = {'High': 0, 'Medium': 0, 'Low': 0, 'dev': 0, 'qa': 0}
                if priority in ('High', 'Highest', 'Critical', 'Blocker'):
                    dist[ver]['High'] += 1
                elif priority == 'Medium':
                    dist[ver]['Medium'] += 1
                else:
                    dist[ver]['Low'] += 1
                dist[ver][phase] += 1

        total = sum(v['High'] + v['Medium'] + v['Low'] for v in dist.values())
        print(f"✓ Cross-release distribution: {len(dist)} releases, {total} open bugs"
              f" (skipped {skipped} DP Runners bugs)")
        return dist

    except Exception as exc:
        print(f"⚠️  Could not fetch cross-release distribution: {exc}")
        return {}


def calculate_historical_trends(bugs, weeks=8):
    """Calculate historical bug trends over the specified number of weeks"""
    from datetime import datetime, timedelta
    from collections import Counter
    
    if not bugs:
        return {
            'dates': [],
            'total': [],
            'dev': [],
            'qa': [],
            'high_sev_dates': [],
            'high_sev_total': [],
            'high_sev_dev': [],
            'high_sev_qa': [],
            'priority_breakdown': {},
            'release_distribution': {}
        }
    
    # Find earliest bug creation date
    earliest_date = min([datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').date() for bug in bugs])
    end_date = datetime.now().date()
    
    # Generate weekly data points
    dates = []
    total_counts = []
    dev_counts = []
    qa_counts = []
    
    current_date = earliest_date
    while current_date <= end_date:
        dates.append(current_date.strftime('%Y-%m-%d'))
        
        dev = sum(1 for bug in bugs if datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').date() <= current_date and get_bug_status_at_date(bug, current_date) == 'dev')
        qa = sum(1 for bug in bugs if datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').date() <= current_date and get_bug_status_at_date(bug, current_date) == 'qa')
        # Total = open bugs only (Dev + QA), excluding closed/accepted bugs
        total = dev + qa
        
        total_counts.append(total)
        dev_counts.append(dev)
        qa_counts.append(qa)
        
        current_date += timedelta(days=7)

    # Ensure the current week (today) is always the last data point
    today_str = end_date.strftime('%Y-%m-%d')
    if not dates or dates[-1] != today_str:
        dev = sum(1 for bug in bugs if datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').date() <= end_date and get_bug_status_at_date(bug, end_date) == 'dev')
        qa  = sum(1 for bug in bugs if datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').date() <= end_date and get_bug_status_at_date(bug, end_date) == 'qa')
        dates.append(today_str)
        total_counts.append(dev + qa)
        dev_counts.append(dev)
        qa_counts.append(qa)

    # High/Critical priority trend
    high_sev_bugs = [b for b in bugs if hasattr(b.fields, 'priority') and b.fields.priority and b.fields.priority.name in ['High', 'Highest', 'Critical']]
    
    high_sev_dates = []
    high_sev_total = []
    high_sev_dev = []
    high_sev_qa = []
    
    current_date = earliest_date
    while current_date <= end_date:
        high_sev_dates.append(current_date.strftime('%Y-%m-%d'))
        
        dev = sum(1 for bug in high_sev_bugs if datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').date() <= current_date and get_bug_status_at_date(bug, current_date) == 'dev')
        qa = sum(1 for bug in high_sev_bugs if datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').date() <= current_date and get_bug_status_at_date(bug, current_date) == 'qa')
        # Total = open bugs only (Dev + QA), excluding closed/accepted bugs
        total = dev + qa
        
        high_sev_total.append(total)
        high_sev_dev.append(dev)
        high_sev_qa.append(qa)
        
        current_date += timedelta(days=7)

    # Ensure the current week (today) is always the last data point
    if not high_sev_dates or high_sev_dates[-1] != today_str:
        dev = sum(1 for bug in high_sev_bugs if datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').date() <= end_date and get_bug_status_at_date(bug, end_date) == 'dev')
        qa  = sum(1 for bug in high_sev_bugs if datetime.strptime(bug.fields.created[:10], '%Y-%m-%d').date() <= end_date and get_bug_status_at_date(bug, end_date) == 'qa')
        high_sev_dates.append(today_str)
        high_sev_total.append(dev + qa)
        high_sev_dev.append(dev)
        high_sev_qa.append(qa)

    # Priority breakdown
    priority_counts = Counter([b.fields.priority.name if hasattr(b.fields, 'priority') and b.fields.priority else 'None' for b in bugs])
    
    # Release distribution (bugs across releases currently open - both Dev and QA)
    release_dist = {}
    for bug in bugs:
        bug_status = get_bug_status_at_date(bug, end_date)
        if bug_status in ['dev', 'qa']:
            priority = bug.fields.priority.name if hasattr(bug.fields, 'priority') and bug.fields.priority else 'None'
            
            if hasattr(bug.fields, 'fixVersions') and bug.fields.fixVersions:
                for version in bug.fields.fixVersions:
                    if version.name not in release_dist:
                        release_dist[version.name] = {'High': 0, 'Medium': 0, 'Low': 0}
                    
                    if priority in ['High', 'Highest', 'Critical']:
                        release_dist[version.name]['High'] += 1
                    elif priority == 'Medium':
                        release_dist[version.name]['Medium'] += 1
                    else:
                        release_dist[version.name]['Low'] += 1
            else:
                # Bugs without fixVersion go to "Unassigned" bucket
                if 'Unassigned' not in release_dist:
                    release_dist['Unassigned'] = {'High': 0, 'Medium': 0, 'Low': 0}
                
                if priority in ['High', 'Highest', 'Critical']:
                    release_dist['Unassigned']['High'] += 1
                elif priority == 'Medium':
                    release_dist['Unassigned']['Medium'] += 1
                else:
                    release_dist['Unassigned']['Low'] += 1
    
    return {
        'dates': dates,
        'total': total_counts,
        'dev': dev_counts,
        'qa': qa_counts,
        'high_sev_dates': high_sev_dates,
        'high_sev_total': high_sev_total,
        'high_sev_dev': high_sev_dev,
        'high_sev_qa': high_sev_qa,
        'priority_breakdown': dict(priority_counts),
        'release_distribution': release_dist
    }


def generate_xray_detail_table(executions):
    """Generate HTML table for Xray execution details"""
    if not executions:
        return ''
    
    method_colors = {
        'Automated': '#17a2b8',
        'Manual': '#6c757d',
        'Automation Candidate': '#fd7e14',
        'NA': '#dc3545'
    }
    
    # Sort by execution rate descending
    sorted_execs = sorted(
        [e for e in executions if e['tests'] > 0],
        key=lambda e: (e['executed'] / e['tests'] * 100) if e['tests'] > 0 else 0,
        reverse=True
    )

    rows = []
    for e in sorted_execs:
        # Calculate rate color
        rate = (e['executed'] / e['tests'] * 100) if e['tests'] > 0 else 0
        if rate == 100:
            rate_color = '#4caf50'
        elif rate > 0:
            rate_color = '#ff9800'
        else:
            rate_color = '#9e9e9e'
        
        # Build method badges
        method_badges = []
        methods = e.get('methods', {})
        for m, c in methods.items():
            color = method_colors.get(m, '#999999')
            method_badges.append(
                f'<span style="background-color:{color}; color:white; '
                f'padding:1px 6px; border-radius:3px; font-size:11px; margin-right:3px;">'
                f'{m}: {c}</span>'
            )
        methods_html = ''.join(method_badges) if method_badges else '-'
        
        # Calculate Automation Coverage: automated / (automated + candidates)
        automated_count = methods.get('Automated', 0)
        candidate_count = methods.get('Automation Candidate', 0)
        total_tests = e['tests']
        potential = automated_count + candidate_count
        
        if potential > 0:
            auto_coverage = (automated_count / potential) * 100
            auto_coverage_html = f'<span style="color:#17a2b8; font-weight:bold;">{auto_coverage:.0f}%</span>'
        else:
            auto_coverage_html = '<span style="color:#999;">N/A</span>'
        
        # Calculate Automation Potential: (automated + candidates) / total tests
        if total_tests > 0:
            auto_potential = (potential / total_tests) * 100
            if auto_potential > 50:
                potential_color = '#17a2b8'  # cyan - good potential
            elif auto_potential > 0:
                potential_color = '#fd7e14'  # orange - some potential
            else:
                potential_color = '#999'  # gray - no potential
            auto_potential_html = f'<span style="color:{potential_color}; font-weight:bold;">{auto_potential:.0f}%</span>'
        else:
            auto_potential_html = '-'
        
        # Calculate Pass Ratio from statuses
        statuses = e.get('statuses', {})
        passed_count = statuses.get('PASSED', 0) + statuses.get('Passed', 0) + statuses.get('PASS', 0)
        total_executed = e['executed']
        
        if total_executed > 0:
            pass_ratio = (passed_count / total_executed) * 100
            if pass_ratio >= 90:
                pass_color = '#4caf50'  # green
            elif pass_ratio >= 70:
                pass_color = '#ff9800'  # orange
            else:
                pass_color = '#dc3545'  # red
            pass_ratio_html = f'<span style="color:{pass_color}; font-weight:bold;">{pass_ratio:.0f}%</span>'
        else:
            pass_ratio_html = '-'
        
        rows.append(
            f'<tr>'
            f'<td><a href="https://rwrnd.atlassian.net/browse/{e["key"]}">{e["key"]}</a></td>'
            f'<td>{html.escape(e["summary"])}</td>'
            f'<td>{html.escape(e["jira_status"])}</td>'
            f'<td style="text-align:center;">{e["tests"]}</td>'
            f'<td style="text-align:center;">{e["executed"]}</td>'
            f'<td style="text-align:center; color:{rate_color}; font-weight:bold;">{rate:.0f}%</td>'
            f'<td style="text-align:center;">{pass_ratio_html}</td>'
            f'<td>{methods_html}</td>'
            f'<td style="text-align:center;">{auto_coverage_html}</td>'
            f'<td style="text-align:center;">{auto_potential_html}</td>'
            f'</tr>'
        )
    
    if not rows:
        return ''
    
    table_html = (
        '<table>'
        '<thead><tr><th>Key</th><th>Summary</th><th>Jira Status</th>'
        '<th>Tests</th><th>Executed</th><th>Exec Rate</th><th>Pass Ratio</th><th>Methods</th>'
        '<th>Auto Coverage</th><th>Auto Potential</th></tr></thead>'
        '<tbody>' + ''.join(rows) + '</tbody>'
        '</table>'
    )
    
    return table_html


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


def generate_ai_insights(stats, bug_data, platform_data, critical_failures, sprint_name,
                          historical_trends=None, sub_exec_stats=None, xray_summary=None,
                          ci_sprint_history=None, sub_exec_sprint_history=None):
    """
    Generate AI-powered insights using GitHub Models API.
    Includes trend analysis for coverage, bugs, CI status, and sub test execution progress
    across previous sprints so the AI can reason about overall release trajectory.
    Falls back gracefully if API fails or token not available.
    """
    from openai import OpenAI

    github_token = os.getenv('GITHUB_TOKEN')
    if not github_token:
        print("   ⓘ GitHub token not found, skipping AI insights")
        return None

    try:
        # Initialize OpenAI client with GitHub Models endpoint
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=github_token
        )

        # ── Current snapshot ────────────────────────────────────────────────
        context = f"""
Analyze this DefensePro weekly test report for {sprint_name}:

CURRENT CI SNAPSHOT:
- Test Coverage: {stats.get('overall_coverage', 0):.1f}%
- Pass Ratio: {stats.get('pass_ratio', 0):.1f}%
- Tests Executed: {stats.get('total_executed', 0):,}
- Failed Tests: {stats.get('total_failed', 0):,}
- Critical Failures (all platforms): {critical_failures if isinstance(critical_failures, int) else len(critical_failures)}
- Bugs in Dev: {bug_data.get('on_dev', 0)}
- Bugs in QA: {bug_data.get('on_qa', 0)}

PLATFORM PERFORMANCE (current sprint):
"""
        for p in platform_data[:8]:
            context += f"- {p['platform_type_mode']}: {p['coverage']:.1f}% coverage, {p['pass_ratio']:.1f}% pass rate\n"

        # ── CI per-sprint history ────────────────────────────────────────────
        if ci_sprint_history:
            context += "\nCI ITERATION TREND (per sprint, oldest→newest):\n"
            context += "  Sprint                      | Coverage | Pass Ratio | Tests | Passed | Failed\n"
            context += "  ----------------------------|----------|------------|-------|--------|-------\n"
            for s in ci_sprint_history:
                marker = " ◄ CURRENT" if s.get('state', '').lower() == 'active' else ""
                context += (
                    f"  {s['sprint_name']:<28} | {s['coverage']:>6.1f}%  | {s['pass_ratio']:>8.1f}%  |"
                    f" {s['tests_executed']:>5} | {s['passed']:>6} | {s['failed']:>5}{marker}\n"
                )
            # Trend summary
            if len(ci_sprint_history) >= 2:
                first = ci_sprint_history[0]
                last_closed = next((s for s in reversed(ci_sprint_history) if s.get('state', '') != 'active'), None)
                if last_closed and first != last_closed:
                    cov_delta = last_closed['coverage'] - first['coverage']
                    pr_delta  = last_closed['pass_ratio'] - first['pass_ratio']
                    context += (
                        f"  Coverage change over tracked sprints: {cov_delta:+.1f}%\n"
                        f"  Pass ratio change over tracked sprints: {pr_delta:+.1f}%\n"
                    )

        # ── Bug trend (last 6 weekly data points) ───────────────────────────
        if historical_trends and historical_trends.get('dates'):
            dates = historical_trends['dates'][-6:]
            dev_counts = historical_trends['dev'][-6:]
            qa_counts = historical_trends['qa'][-6:]
            total_counts = historical_trends['total'][-6:]
            high_dev = historical_trends.get('high_sev_dev', [])[-6:]
            high_qa = historical_trends.get('high_sev_qa', [])[-6:]

            context += "\nBUG TREND (last 6 weeks, open bugs only):\n"
            context += "  Date        | Total | Dev | QA | High/Crit Dev | High/Crit QA\n"
            context += "  ------------|-------|-----|----|---------------|-------------\n"
            for i, date in enumerate(dates):
                hd = high_dev[i] if i < len(high_dev) else '-'
                hq = high_qa[i] if i < len(high_qa) else '-'
                context += f"  {date} |  {total_counts[i]:3d}  | {dev_counts[i]:3d} | {qa_counts[i]:2d} |     {hd}           |     {hq}\n"

            if len(total_counts) >= 2:
                delta = total_counts[-1] - total_counts[-2]
                direction = f"+{delta}" if delta > 0 else str(delta)
                context += f"  Week-over-week change in total open bugs: {direction}\n"

        # ── Sub test execution current progress ─────────────────────────────
        if sub_exec_stats:
            total_se = sub_exec_stats.get('total', 0)
            done_se = sub_exec_stats.get('completed', 0)
            progress_se = sub_exec_stats.get('in_progress', 0)
            not_started_se = sub_exec_stats.get('not_started', 0)
            pct_done = (done_se / total_se * 100) if total_se > 0 else 0
            context += f"""
SUB TEST EXECUTION PROGRESS (current sprint):
- Total Sub Test Executions: {total_se}
- Completed (Done/Accepted): {done_se} ({pct_done:.1f}%)
- In Progress: {progress_se}
- Not Started: {not_started_se}
"""
            team_breakdown = sub_exec_stats.get('team_breakdown', {})
            if team_breakdown:
                context += "  Team breakdown (Done / In-Progress / Not-Started):\n"
                for team, ts in sorted(team_breakdown.items()):
                    context += f"    {team}: {ts.get('Done',0)} / {ts.get('In Progress',0)} / {ts.get('Not Started',0)}\n"

        # ── Sub test execution per-sprint history ────────────────────────────
        if sub_exec_sprint_history:
            context += "\nSUB TEST EXECUTION TREND (per sprint, oldest→newest):\n"
            context += "  Sprint                      | Total | Done | In-Prog | Not-Started | Done%\n"
            context += "  ----------------------------|-------|------|---------|-------------|------\n"
            for s in sub_exec_sprint_history:
                marker = " ◄ CURRENT" if s.get('state', '').lower() == 'active' else ""
                context += (
                    f"  {s['sprint_name']:<28} | {s['total']:>5} | {s['completed']:>4} |"
                    f" {s['in_progress']:>7} | {s['not_started']:>11} | {s['completion_pct']:>4.1f}%{marker}\n"
                )
            if len(sub_exec_sprint_history) >= 2:
                first_pct = sub_exec_sprint_history[0]['completion_pct']
                last_closed_se = next(
                    (s for s in reversed(sub_exec_sprint_history) if s.get('state', '') != 'active'), None
                )
                if last_closed_se and last_closed_se['completion_pct'] != first_pct:
                    delta_pct = last_closed_se['completion_pct'] - first_pct
                    context += f"  Completion rate change over tracked sprints: {delta_pct:+.1f}%\n"

        # ── Xray sub test execution metrics ─────────────────────────────────
        if xray_summary and xray_summary.get('total_tests', 0) > 0:
            context += f"""
XRAY SUB EXECUTION METRICS (current):
- Total Tests Linked: {xray_summary.get('total_tests', 0):,}
- Executed: {xray_summary.get('total_executed', 0):,} ({xray_summary.get('execution_rate', 0):.1f}%)
- Passed: {xray_summary.get('total_passed', 0):,}
- Pass Ratio: {xray_summary.get('pass_ratio', 0):.1f}%
- Automation Coverage: {xray_summary.get('automation_coverage', 0):.1f}%
- Testing Coverage: {xray_summary.get('testing_coverage', 0):.1f}%
"""

        # ── AI instructions ──────────────────────────────────────────────────
        context += """

Provide exactly 5 insight sections as HTML:
1. <h4>Coverage Trend Analysis</h4> – Compare coverage across sprints. Is the velocity sufficient to reach 90%+ before release? Identify the gap.
2. <h4>Bug Trend Analysis</h4> – Interpret weekly open-bug trajectory, highlight rising high/critical counts, assess burn-down health vs. release timeline.
3. <h4>CI Iteration Progress</h4> – Evaluate sprint-over-sprint pass ratio and failure trends. Flag regressions or quality improvements. Assess current sprint risk.
4. <h4>Sub Test Execution Progress</h4> – Compare per-sprint completion rates. Identify stalled teams or cycles, flag risk of incomplete coverage before release.
5. <h4>Prioritized Action Plan</h4> – Numbered list (max 6 items) of concrete recommendations ordered by urgency, referencing specific sprints or teams.

Use <ul>/<ol> and <strong> for emphasis. Be concise, technical, and data-driven. Limit total response to ~1100 tokens.
"""

        print("   🤖 Generating AI trend insights using GitHub Models...")

        response = client.chat.completions.create(
            model="o3-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior QA automation expert analyzing DefensePro release test reports. "
                        "Focus on sprint-over-sprint trend direction, risk signals, and actionable recommendations. "
                        "Output valid HTML only — no markdown, no code fences."
                    )
                },
                {
                    "role": "user",
                    "content": context
                }
            ],
            max_completion_tokens=8000
        )

        ai_insights = response.choices[0].message.content.strip()
        if not ai_insights:
            print("   ⚠️ AI insights: model returned empty response (token budget exhausted?)")
            return None
        print("   ✓ AI trend insights generated successfully\n")
        return ai_insights

    except Exception as e:
        print(f"   ⚠️ AI insights generation failed: {e}")
        print("   Continuing with rule-based insights only...\n")
        return None


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


def get_bugs_closed_during_period(bugs, start_date, end_date):
    """
    Find bugs that transitioned to closed/accepted status during the specified period.
    Uses changelog to determine when status changed to closed.
    
    Returns: list of bugs that were closed during the period
    """
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date[:10], '%Y-%m-%d').date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date[:10], '%Y-%m-%d').date()
    
    closed_bugs = []
    
    for bug in bugs:
        changelog = bug.changelog
        if not hasattr(changelog, 'histories'):
            continue
            
        # Sort histories chronologically
        sorted_histories = sorted(changelog.histories, key=lambda h: h.created)
        
        for history in sorted_histories:
            change_date = datetime.strptime(history.created[:19], '%Y-%m-%dT%H:%M:%S').date()
            
            # Skip changes outside our period
            if change_date < start_date or change_date > end_date:
                continue
            
            for item in history.items:
                if item.field == 'status':
                    new_status = item.toString.lower()
                    # Check if transitioned to a closed state
                    if 'accepted' in new_status or 'done' in new_status or 'closed' in new_status:
                        closed_bugs.append(bug)
                        break
            else:
                continue
            break  # Found closure, move to next bug
    
    return closed_bugs


def main():
    version = os.getenv('VERSION')
    builds_override = os.getenv('BUILDS', '').strip()
    sprint_start_override = os.getenv('SPRINT_START', '').strip()
    sprint_end_override = os.getenv('SPRINT_END', '').strip()
    ci_run_start = os.getenv('CI_RUN_START', '').strip()
    skip_ai_insights = os.getenv('SKIP_AI_INSIGHTS', '').strip().lower() in ('1', 'true', 'yes')

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
    sprint_start = sprint_start_override if sprint_start_override else sprint.startDate
    sprint_end = sprint_end_override if sprint_end_override else sprint.endDate
    if sprint_start_override or sprint_end_override:
        print(f"Using overridden sprint period: {sprint_start[:10]} to {sprint_end[:10]}")

    # When CI_RUN_START is set, use it as the effective start for CI metrics
    ci_start = ci_run_start if ci_run_start else sprint_start
    if ci_run_start:
        print(f"CI_RUN_START override: using {ci_run_start} as CI metrics start date")

    # Auto-detect builds from database unless overridden
    if builds_override:
        builds = builds_override
        print(f"Using overridden builds: {builds}")
    else:
        print("Auto-detecting builds from database...")
        builds = get_builds_for_version(conn, version, ci_start, sprint_end)
        if builds:
            print(f"✓ Auto-detected builds: {builds}")
        else:
            print("⚠️  No builds found for this version in sprint period")
            builds = ''  # Will result in 0 test executions
    print(f"Sprint: {sprint.name}")
    print(f"Period: {ci_start[:10]} to {sprint_end[:10]}\n")
    
    # Get version info to check if it's active
    version_info = get_version_info(jira, version)
    
    if version_info['released']:
        print(f"⚠️  WARNING: Version {version} is marked as RELEASED in Jira")
        print(f"   All bugs for this version should be closed.")
        print(f"   Consider using an active/unreleased version for meaningful reports.\n")
    
    if version_info['archived']:
        print(f"⚠️  WARNING: Version {version} is ARCHIVED in Jira")
        print(f"   This is a historical version with no active work.\n")
    
    # Get bug data - all active bugs across unreleased DP releases
    print("Fetching bug data (all active releases)...")
    jql = (
        'project = DP AND type = Bug '
        'AND status NOT IN (Accepted, Closed, Trash) '
        'AND fixVersion in unreleasedVersions() '
        'AND fixVersion != "10.100.0.0" '
        'AND cf[10129] != "DP Runners"'
    )
    bugs = jira.search_issues(jql, maxResults=False, expand='changelog')
    print(f"✓ Found {len(bugs)} active bugs across all unreleased DP versions (Accepted/Closed/Trash/DP Runners excluded)\n")
    
    # Get automation data
    print("Fetching automation data...")
    automation_data = get_automation_data(conn, jira, version, builds, ci_start, sprint_end)
    print(f"✓ Found {automation_data['total_tests']} tests with {automation_data['total_executions']} executions\n")

    # Get coverage progress and velocity (only when CI_RUN_START is set)
    coverage_progress = None
    if ci_run_start:
        print(f"Fetching CI coverage progress from {ci_run_start}...")
        coverage_progress = get_coverage_progress(conn, version, ci_run_start)
        if coverage_progress:
            print(f"✓ Coverage progress: {coverage_progress['current_coverage']}% coverage, "
                  f"{coverage_progress['current_pass_ratio']}% pass ratio, "
                  f"avg {coverage_progress['avg_daily_rate']}%/day\n")
        else:
            print("⚠️  No coverage progress data available\n")

    # Fetch build changelogs from Jenkins (if configured)
    build_changelogs = None
    if builds and ci_run_start:
        print("Fetching build changelogs from Jenkins...")
        build_changelogs = get_build_changelogs(builds)
        if build_changelogs:
            total_changes = sum(len(b['changes']) for b in build_changelogs)
            print(f"✓ Found {total_changes} change(s) across {len(build_changelogs)} builds\n")
        else:
            print("⚠️  Build changelogs not available (JENKINS_BUILD_URL/JOB not configured)\n")

    # Fetch previous sprints for trend analysis
    print("Fetching sprint list for trend history...")
    sprint_list = get_sprint_list(jira, n_closed=4)
    if sprint_list:
        print(f"✓ Found {len(sprint_list)} sprints for trend analysis\n")
    else:
        print("⚠️  Could not retrieve sprint list; trend history will be skipped\n")
    
    # Categorize bugs based on status category and name
    bugs_on_dev = []
    bugs_on_qa = []
    
    for bug in bugs:
        status_name = bug.fields.status.name.lower() if hasattr(bug.fields, 'status') else 'unknown'
        status_category = bug.fields.status.statusCategory.name.lower() if hasattr(bug.fields, 'status') and hasattr(bug.fields.status, 'statusCategory') else 'unknown'
        
        # Skip trashed bugs (safety net in case JQL filter missed any)
        if 'trash' in status_name:
            continue

        # On QA status (Completed but not Accepted) - must be checked BEFORE 'done' category
        # because 'Completed' status has statusCategory='Done' in Jira
        if 'completed' in status_name and 'accepted' not in status_name:
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
            # Default to dev with warning
            print(f"  ⚠️  Warning: Unknown status for {bug.key}: {status_name} (category: {status_category}). Assigning to Dev.")
            bugs_on_dev.append(bug)
    
    # Fetch bugs closed/accepted during this sprint period (separate query, scoped to active releases)
    print("Calculating bugs closed this week...")
    closed_this_week_jql = (
        f'project = DP AND type = Bug '
        f'AND fixVersion in unreleasedVersions() '
        f'AND fixVersion != "10.100.0.0" '
        f'AND cf[10129] != "DP Runners" '
        f'AND status IN (Accepted, Closed, Done) '
        f'AND status CHANGED TO (Accepted, Closed, Done) '
        f'AFTER "{sprint_start[:10]}" '
        f'BEFORE "{sprint_end[:10]}"'
    )
    try:
        bugs_closed_candidates = jira.search_issues(closed_this_week_jql, maxResults=False, expand='changelog')
        bugs_closed_this_week = get_bugs_closed_during_period(bugs_closed_candidates, sprint_start, sprint_end)
    except Exception as e:
        print(f"  ⚠️  Could not fetch closed bugs: {e}")
        bugs_closed_candidates = []
        bugs_closed_this_week = []
    
    # Calculate historical trends
    print("Calculating historical bug trends...")
    historical_trends = calculate_historical_trends(bugs)

    # Override release distribution with cross-release data (all active versions)
    cross_release_dist = get_cross_release_distribution(jira)
    if cross_release_dist:
        historical_trends['release_distribution'] = cross_release_dist

    # Debug output
    print(f"\nBug categorization:")
    print(f"  On Dev: {len(bugs_on_dev)}")
    print(f"  On QA: {len(bugs_on_qa)}")
    bugs_closed_total = len(bugs_closed_candidates)
    print(f"  Closed (total, this sprint): {bugs_closed_total}")
    print(f"  Closed this week: {len(bugs_closed_this_week)}")
    if bugs_on_dev:
        print(f"  Sample Dev bug status: {bugs_on_dev[0].fields.status.name}")
    if bugs_on_qa:
        print(f"  Sample QA bug status: {bugs_on_qa[0].fields.status.name}")
    
    # Get sub test executions
    print("Fetching sub test executions...")
    sub_exec_jql = (
        f'project = DP AND fixVersion = "{version}" '
        f'AND type = "sub test execution" '
        f'AND status != Trash'
    )
    
    sub_execs = jira.search_issues(sub_exec_jql, maxResults=False, fields='summary,status,assignee,customfield_10001')
    print(f"✓ Found {len(sub_execs)} sub test executions (Trash excluded)\n")
    
    # Get Xray data for sub test executions (execution rate, automation coverage)
    print("Fetching Xray data for Sub Test Executions...")
    try:
        sub_exec_xray_data = get_sub_test_execution_xray_data(jira, sub_execs, version)
    except Exception as e:
        print(f"⚠️ Failed to fetch Xray data: {e}")
        sub_exec_xray_data = {
            'executions': [],
            'summary': {
                'total_tests': 0,
                'total_executed': 0,
                'execution_rate': 0,
                'methods': {},
                'automation_coverage': 0
            }
        }
    
    # Get test method distribution
    print("Fetching test method distribution...")
    test_method_data = get_test_method_distribution(jira, version)
    print(f"✓ Found {test_method_data['total_tests']} tests with method data\n")
    
    # Helper to check if status indicates completion (Done, Accepted, or Complete)
    def is_completed_status(status_name):
        status_lower = status_name.lower()
        return 'done' in status_lower or 'accepted' in status_lower or 'complete' in status_lower
    
    sub_exec_completed = sum(1 for se in sub_execs if hasattr(se.fields, 'status') and is_completed_status(se.fields.status.name))
    sub_exec_in_progress = sum(1 for se in sub_execs if hasattr(se.fields, 'status') and 'in progress' in se.fields.status.name.lower())
    sub_exec_not_started = len(sub_execs) - sub_exec_completed - sub_exec_in_progress
    
    # Helper function to extract team name safely
    def get_team_name(issue):
        scrum_team = getattr(issue.fields, 'customfield_10001', None)
        if scrum_team:
            return scrum_team.name if hasattr(scrum_team, 'name') else str(scrum_team)
        return 'Unassigned'
    
    # Group sub test executions by scrum team
    from collections import defaultdict
    team_stats = defaultdict(lambda: {'Done': 0, 'In Progress': 0, 'Not Started': 0, 'total': 0})
    
    for se in sub_execs:
        # Get scrum team name from customfield_10001
        team = get_team_name(se)
        
        # Determine status category
        status_lower = se.fields.status.name.lower() if hasattr(se.fields, 'status') else 'unknown'
        if 'done' in status_lower or 'accepted' in status_lower or 'complete' in status_lower:
            team_stats[team]['Done'] += 1
        elif 'progress' in status_lower:
            team_stats[team]['In Progress'] += 1
        else:
            team_stats[team]['Not Started'] += 1
        
        team_stats[team]['total'] += 1
    
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
    
    # Calculate max value for proper y-axis range
    max_value = max(len(bugs_on_dev), len(bugs_on_qa), len(bugs_closed_this_week))
    y_range = [0, max_value * 1.25]  # Add 25% padding at the top for text labels
    
    fig_bugs.add_trace(go.Bar(
        x=['Bugs on Dev', 'Bugs on QA', 'Closed This Week'],
        y=[len(bugs_on_dev), len(bugs_on_qa), len(bugs_closed_this_week)],
        marker_color=['#ff9800', '#2196f3', '#4caf50'],
        text=[len(bugs_on_dev), len(bugs_on_qa), len(bugs_closed_this_week)],
        textposition='outside',
        textfont=dict(size=14)
    ))
    fig_bugs.update_layout(
        title=f'Bug Status Distribution - {version}',
        xaxis_title='Status',
        yaxis_title='Count',
        yaxis=dict(range=y_range),
        height=450,
        margin=dict(t=100, b=60, l=60, r=40)
    )
    
    # Create sub test execution status chart (pie chart)
    fig_sub_exec = go.Figure()
    if len(sub_execs) > 0:
        labels = ['Completed', 'In Progress', 'Not Started']
        values = [sub_exec_completed, sub_exec_in_progress, sub_exec_not_started]
        colors = ['#4caf50', '#2196f3', '#ff9800']
        
        fig_sub_exec.add_trace(go.Pie(
            labels=labels,
            values=values,
            marker=dict(colors=colors),
            textinfo='label+value+percent',
            textfont=dict(size=14),
            hole=0.4  # Donut chart style
        ))
        fig_sub_exec.update_layout(
            title=f'Sub Test Execution Status - {version}',
            height=400,
            margin=dict(t=80, b=40, l=40, r=40)
        )
    
    # Generate HTML
    automation_chart_html = fig_automation.to_html(include_plotlyjs='inline', div_id='automation-chart', full_html=False) if automation_data['platform_data'] else ""
    bugs_chart_html = fig_bugs.to_html(include_plotlyjs='inline' if not automation_data['platform_data'] else False, div_id='bugs-chart', full_html=False)
    sub_exec_chart_html = fig_sub_exec.to_html(include_plotlyjs=False, div_id='sub-exec-chart', full_html=False) if len(sub_execs) > 0 else ""
    
    # Create Xray execution rate charts
    xray_exec_rate_chart_html = ""
    xray_method_chart_html = ""
    
    if sub_exec_xray_data['summary']['total_tests'] > 0:
        summary = sub_exec_xray_data['summary']
        
        # Execution Rate Pie Chart
        fig_xray_exec = go.Figure()
        executed = summary['total_executed']
        not_executed = summary['total_tests'] - executed
        
        fig_xray_exec.add_trace(go.Pie(
            labels=['Executed', 'Not Executed'],
            values=[executed, not_executed],
            marker=dict(colors=['#4caf50', '#9e9e9e']),
            textinfo='label+value+percent',
            textfont=dict(size=14),
            hole=0.4
        ))
        fig_xray_exec.update_layout(
            title=f'Test Execution Rate (Xray) - {version}',
            height=350,
            margin=dict(t=80, b=40, l=40, r=40)
        )
        xray_exec_rate_chart_html = fig_xray_exec.to_html(include_plotlyjs=False, div_id='xray-exec-chart', full_html=False)
        
        # Method Distribution Pie Chart
        methods = summary['methods']
        if methods:
            fig_xray_method = go.Figure()
            method_labels = list(methods.keys())
            method_values = list(methods.values())
            method_colors = {
                'Automated': '#17a2b8',
                'Manual': '#6c757d', 
                'Automation Candidate': '#fd7e14',
                'NA': '#dc3545'
            }
            colors = [method_colors.get(m, '#999999') for m in method_labels]
            
            fig_xray_method.add_trace(go.Pie(
                labels=method_labels,
                values=method_values,
                marker=dict(colors=colors),
                textinfo='label+value+percent',
                textfont=dict(size=14),
                hole=0.4
            ))
            fig_xray_method.update_layout(
                title=f'Rally Test Method Distribution (Xray) - {version}',
                height=350,
                margin=dict(t=80, b=40, l=40, r=40)
            )
            xray_method_chart_html = fig_xray_method.to_html(include_plotlyjs=False, div_id='xray-method-chart', full_html=False)
    
    # Create test method distribution chart
    fig_test_method = go.Figure()
    test_method_chart_html = ""
    if test_method_data['total_tests'] > 0:
        methods = ['Automated', 'Manual', 'Automation Candidate', 'Not Specified']
        method_values = [test_method_data['by_method'].get(m, 0) for m in methods]
        method_colors = ['#4caf50', '#2196f3', '#ff9800', '#9e9e9e']  # Green, Blue, Orange, Gray
        
        fig_test_method.add_trace(go.Pie(
            labels=methods,
            values=method_values,
            marker=dict(colors=method_colors),
            textinfo='label+value+percent',
            textfont=dict(size=14),
            hole=0.4
        ))
        fig_test_method.update_layout(
            title=f'Test Method Distribution - {version}',
            height=400,
            margin=dict(t=80, b=40, l=40, r=40)
        )
        test_method_chart_html = fig_test_method.to_html(include_plotlyjs=False, div_id='test-method-chart', full_html=False)
    
    # Create historical bug trend charts
    fig_historical = go.Figure()
    fig_historical.add_trace(go.Scatter(
        x=historical_trends['dates'],
        y=historical_trends['total'],
        mode='lines+markers',
        name='Total Open Bugs',
        line=dict(color='#003366', width=4),
        marker=dict(size=8)
    ))
    fig_historical.add_trace(go.Scatter(
        x=historical_trends['dates'],
        y=historical_trends['dev'],
        mode='lines+markers',
        name='On Dev',
        line=dict(color='#ff6600', width=3),
        marker=dict(size=7)
    ))
    fig_historical.add_trace(go.Scatter(
        x=historical_trends['dates'],
        y=historical_trends['qa'],
        mode='lines+markers',
        name='On QA',
        line=dict(color='#0070c0', width=3),
        marker=dict(size=7)
    ))
    fig_historical.update_layout(
        title=f'Bug Trend from Release Start - {version}',
        xaxis_title='Week',
        yaxis_title='Bug Count',
        height=450,
        legend=dict(x=0.02, y=0.98),
        hovermode='x unified'
    )
    historical_chart_html = fig_historical.to_html(include_plotlyjs=False, div_id='historical-chart', full_html=False)
    
    # Create high/critical priority trend chart
    fig_high_sev = go.Figure()
    fig_high_sev.add_trace(go.Scatter(
        x=historical_trends['high_sev_dates'],
        y=historical_trends['high_sev_total'],
        mode='lines+markers',
        name='Total High/Critical',
        line=dict(color='#d32f2f', width=4),
        marker=dict(size=8)
    ))
    fig_high_sev.add_trace(go.Scatter(
        x=historical_trends['high_sev_dates'],
        y=historical_trends['high_sev_dev'],
        mode='lines+markers',
        name='On Dev',
        line=dict(color='#ff6600', width=3),
        marker=dict(size=7)
    ))
    fig_high_sev.add_trace(go.Scatter(
        x=historical_trends['high_sev_dates'],
        y=historical_trends['high_sev_qa'],
        mode='lines+markers',
        name='On QA',
        line=dict(color='#0070c0', width=3),
        marker=dict(size=7)
    ))
    fig_high_sev.update_layout(
        title=f'HIGH/CRITICAL Priority Bug Trend - {version}',
        xaxis_title='Week',
        yaxis_title='Bug Count',
        height=450,
        legend=dict(x=0.02, y=0.98),
        hovermode='x unified'
    )
    high_sev_chart_html = fig_high_sev.to_html(include_plotlyjs=False, div_id='high-sev-chart', full_html=False)
    
    # Create release distribution charts
    release_dist_chart_html = ""
    if historical_trends['release_distribution']:
        releases = list(historical_trends['release_distribution'].keys())
        high_counts   = [historical_trends['release_distribution'][r].get('High', 0) for r in releases]
        medium_counts = [historical_trends['release_distribution'][r].get('Medium', 0) for r in releases]
        low_counts    = [historical_trends['release_distribution'][r].get('Low', 0) for r in releases]
        dev_counts    = [historical_trends['release_distribution'][r].get('dev', 0) for r in releases]
        qa_counts     = [historical_trends['release_distribution'][r].get('qa', 0) for r in releases]
        total_counts  = [d + q for d, q in zip(dev_counts, qa_counts)]

        # Chart 1: Priority breakdown per release
        print(f"  release_distribution keys: {releases}")
        fig_prio = go.Figure()
        fig_prio.add_trace(go.Bar(
            name='High/Critical',
            x=releases, y=high_counts,
            marker_color='#d32f2f',
            text=[str(c) if c > 0 else '' for c in high_counts],
            textposition='inside', textfont=dict(color='white', size=12)
        ))
        fig_prio.add_trace(go.Bar(
            name='Medium',
            x=releases, y=medium_counts,
            marker_color='#f57c00',
            text=[str(c) if c > 0 else '' for c in medium_counts],
            textposition='inside', textfont=dict(color='white', size=12)
        ))
        fig_prio.add_trace(go.Bar(
            name='Low',
            x=releases, y=low_counts,
            marker_color='#0288d1',
            text=[str(c) if c > 0 else '' for c in low_counts],
            textposition='inside', textfont=dict(color='white', size=12)
        ))
        fig_prio.update_layout(
            title='Open Bugs by Priority per Release',
            xaxis_title='Release Version', yaxis_title='Bug Count',
            barmode='stack', height=380,
            margin=dict(l=50, r=20, t=60, b=80),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
            hovermode='x unified',
            bargap=0.4, bargroupgap=0.1
        )

        # Chart 2: Dev vs QA per release
        fig_phase = go.Figure()
        fig_phase.add_trace(go.Bar(
            name='On Dev',
            x=releases, y=dev_counts,
            marker_color='#7b1fa2',
            text=[str(c) if c > 0 else '' for c in dev_counts],
            textposition='inside', textfont=dict(color='white', size=12)
        ))
        fig_phase.add_trace(go.Bar(
            name='On QA',
            x=releases, y=qa_counts,
            marker_color='#388e3c',
            text=[str(c) if c > 0 else '' for c in qa_counts],
            textposition='inside', textfont=dict(color='white', size=12)
        ))
        fig_phase.update_layout(
            title='Open Bugs by Phase (Dev vs QA) per Release',
            xaxis_title='Release Version', yaxis_title='Bug Count',
            barmode='stack', height=380,
            margin=dict(l=50, r=20, t=60, b=80),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
            hovermode='x unified',
            bargap=0.4, bargroupgap=0.1
        )

        prio_html_chart  = fig_prio.to_html(include_plotlyjs=False, div_id='release-dist-prio-chart', full_html=False)
        phase_html_chart = fig_phase.to_html(include_plotlyjs=False, div_id='release-dist-phase-chart', full_html=False)

        # Summary table
        table_rows = ''
        for r in releases:
            d = historical_trends['release_distribution'][r]
            h, m, lo, dv, qa = d.get('High', 0), d.get('Medium', 0), d.get('Low', 0), d.get('dev', 0), d.get('qa', 0)
            total = dv + qa
            table_rows += (
                f'<tr><td><strong>{r}</strong></td>'
                f'<td style="color:#d32f2f;font-weight:bold">{h}</td>'
                f'<td style="color:#f57c00">{m}</td>'
                f'<td style="color:#0288d1">{lo}</td>'
                f'<td style="color:#7b1fa2">{dv}</td>'
                f'<td style="color:#388e3c">{qa}</td>'
                f'<td><strong>{total}</strong></td></tr>'
            )
        summary_table = (
            '<table style="width:auto;margin-bottom:16px">'
            '<thead><tr>'
            '<th>Release</th><th>High/Critical</th><th>Medium</th><th>Low</th>'
            '<th>On Dev</th><th>On QA</th><th>Total Open</th>'
            '</tr></thead><tbody>' + table_rows + '</tbody></table>'
        )

        release_dist_chart_html = (
            summary_table +
            '<div style="display:flex;flex-direction:column;gap:20px">')
        release_dist_chart_html += (
            f'<div style="width:100%">{prio_html_chart}</div>'
            f'<div style="width:100%">{phase_html_chart}</div>'
            '</div>'
        )
    
    # Generate priority breakdown HTML
    priority_html = ""
    if historical_trends['priority_breakdown']:
        priority_html = '<h3>Priority Breakdown</h3><table><thead><tr><th>Priority</th><th>Count</th><th>Percentage</th></tr></thead><tbody>'
        total_bugs = sum(historical_trends['priority_breakdown'].values())
        for priority, count in sorted(historical_trends['priority_breakdown'].items(), key=lambda x: -x[1]):
            pct = (count / total_bugs * 100) if total_bugs > 0 else 0
            priority_class = 'priority-high' if priority in ['High', 'Highest', 'Critical'] else 'priority-medium' if priority == 'Medium' else 'priority-low'
            priority_html += f'<tr><td><span class="{priority_class}">{priority}</span></td><td>{count}</td><td>{pct:.1f}%</td></tr>'
        priority_html += '</tbody></table>'
    
    # Generate rule-based insights
    insights = generate_insights(automation_data.get('platform_type_data', []), automation_data, sprint.name) if automation_data['total_tests'] > 0 else []    
    
    # Generate AI-powered insights
    ai_insights = None
    if automation_data['total_tests'] > 0 and not skip_ai_insights:
        # Build sub test execution stats for the AI prompt
        sub_exec_stats_for_ai = {
            'total': len(sub_execs),
            'completed': sub_exec_completed,
            'in_progress': sub_exec_in_progress,
            'not_started': sub_exec_not_started,
            'team_breakdown': dict(team_stats),
        }

        # Gather per-sprint CI and sub test execution history for trend context
        ci_history = []
        sub_exec_history = []
        if sprint_list:
            print("   Fetching CI sprint history for AI insights...")
            ci_history = get_ci_sprint_history(
                conn, version, sprint_list,
                prev_version=automation_data.get('prev_version')
            )
            print(f"   ✓ CI history: {len(ci_history)} sprints\n")

            print("   Fetching sub test execution sprint history for AI insights...")
            sub_exec_history = get_sub_exec_sprint_history(jira, version, sprint_list)
            print(f"   ✓ Sub exec history: {len(sub_exec_history)} sprints\n")

        ai_insights = generate_ai_insights(
            automation_data,
            {'on_dev': len(bugs_on_dev), 'on_qa': len(bugs_on_qa)},
            automation_data.get('platform_type_data', []),
            automation_data.get('critical_failures', []),
            sprint.name,
            historical_trends=historical_trends,
            sub_exec_stats=sub_exec_stats_for_ai,
            xray_summary=sub_exec_xray_data.get('summary'),
            ci_sprint_history=ci_history,
            sub_exec_sprint_history=sub_exec_history,
        )

    
    # Build platform type stats HTML - always show table even with no data
    platform_html = ""
    prev_ver = automation_data.get('prev_version', get_previous_version(version))
    # Always show the table if we have platform_type_data
    if automation_data.get('platform_type_data'):
        platform_html = f'<h3>Platform Type & Mode Summary (Coverage vs. {prev_ver})</h3>'
        platform_html += '<table><thead><tr><th>Platform Type & Mode</th><th>Tests Executed</th><th>Baseline Tests</th><th>Coverage</th><th>Executions</th><th>Passed</th><th>Failed</th><th>Pass Ratio</th></tr></thead><tbody>'
        sorted_pt_data = sorted(automation_data['platform_type_data'], key=lambda x: x['platform_type_mode'])
        for p in sorted_pt_data:
            coverage_class = 'priority-high' if p['coverage'] < 70 else 'priority-medium' if p['coverage'] < 90 else ''
            platform_html += f'<tr><td><strong>{p["platform_type_mode"]}</strong></td><td>{p["tests"]}</td><td>{p["available_tests"]}</td><td class="{coverage_class}">{p["coverage"]:.1f}%</td><td>{p["executions"]}</td><td>{p["passed"]}</td><td>{p["failed"]}</td><td>{p["pass_ratio"]:.1f}%</td></tr>'
        platform_html += '</tbody></table>'

        # New Tests section: tests added in this release not present in previous release
        new_tests_total = automation_data.get('new_tests_total', 0)
        if new_tests_total > 0:
            platform_html += f'<h3 style="margin-top:24px;">New Tests in {version} (not in {prev_ver})</h3>'
            platform_html += '<table><thead><tr><th>Platform Type & Mode</th><th>New Tests</th><th>Passed</th><th>Failed</th><th>Pass Ratio</th></tr></thead><tbody>'
            for p in sorted_pt_data:
                if p.get('new_tests', 0) > 0:
                    new_pass_ratio = p['new_tests_passed'] / max(p['new_tests'], 1) * 100
                    platform_html += f'<tr><td><strong>{p["platform_type_mode"]}</strong></td><td>{p["new_tests"]}</td><td>{p["new_tests_passed"]}</td><td>{p["new_tests_failed"]}</td><td>{new_pass_ratio:.1f}%</td></tr>'
            platform_html += f'<tr style="font-weight:bold; background:#f5f5f5;"><td>Total New Tests</td><td>{new_tests_total}</td><td>{sum(p.get("new_tests_passed",0) for p in sorted_pt_data)}</td><td>{sum(p.get("new_tests_failed",0) for p in sorted_pt_data)}</td><td></td></tr>'
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

    # Build CI coverage progress HTML
    coverage_progress_html = ""
    if coverage_progress:
        cp = coverage_progress
        # Estimation banner
        est_text = f"Estimated full coverage by <strong>{cp['estimated_date']}</strong> ({cp['days_to_complete']} days remaining)" if cp['estimated_date'] else "Insufficient data to estimate completion"
        # Sprint end correlation
        sprint_end_date = datetime.strptime(sprint_end[:10], '%Y-%m-%d')
        days_to_sprint_end = (sprint_end_date - datetime.now()).days
        if days_to_sprint_end < 0:
            sprint_end_note = f'Sprint ended {abs(days_to_sprint_end)} day(s) ago'
            projected_at_sprint_end = cp['current_coverage']
        else:
            projected_at_sprint_end = min(cp['current_coverage'] + cp['avg_daily_rate'] * days_to_sprint_end, 100.0)
            sprint_end_note = f'{days_to_sprint_end} day(s) remaining in sprint'
        projected_at_sprint_end = round(projected_at_sprint_end, 1)
        sprint_coverage_color = '#4caf50' if projected_at_sprint_end >= 90 else '#ff9800' if projected_at_sprint_end >= 60 else '#f44336'
        # Progress bar color for pass ratio
        pr_color = '#4caf50' if cp['current_pass_ratio'] >= 90 else '#ff9800' if cp['current_pass_ratio'] >= 75 else '#f44336'
        coverage_progress_html = f'''
        <div style="background: #e3f2fd; border-left: 5px solid #1565c0; padding: 20px; margin: 20px 0; border-radius: 5px;">
            <h3 style="margin-top: 0; color: #1565c0;">📈 CI Coverage Progress & Velocity</h3>
            <p><strong>CI Start Date:</strong> {cp["ci_run_start"]} | <strong>Days Elapsed:</strong> {cp["total_days_elapsed"]} | <strong>Baseline:</strong> {cp["baseline_total"]:,} tests (from {cp["prev_version"]})</p>
            <p style="margin: 8px 0; font-size: 14px;">🏁 <strong>Sprint End:</strong> {sprint_end[:10]} ({sprint_end_note}) | <strong>Projected coverage at sprint end:</strong> <span style="color: {sprint_coverage_color}; font-weight: bold;">{projected_at_sprint_end}%</span></p>
            <div style="display: flex; gap: 30px; margin: 15px 0;">
                <div style="flex: 1;">
                    <p style="margin: 5px 0; font-size: 13px;"><strong>Coverage:</strong> {cp["current_coverage"]}%</p>
                    <div style="background: #e0e0e0; border-radius: 10px; height: 20px; overflow: hidden;">
                        <div style="background: #1976d2; height: 100%; width: {min(cp["current_coverage"], 100)}%; border-radius: 10px;"></div>
                    </div>
                </div>
                <div style="flex: 1;">
                    <p style="margin: 5px 0; font-size: 13px;"><strong>Pass Ratio:</strong> {cp["current_pass_ratio"]}%</p>
                    <div style="background: #e0e0e0; border-radius: 10px; height: 20px; overflow: hidden;">
                        <div style="background: {pr_color}; height: 100%; width: {min(cp["current_pass_ratio"], 100)}%; border-radius: 10px;"></div>
                    </div>
                </div>
            </div>
            <p style="margin: 10px 0; font-size: 14px;">⚡ <strong>Avg Velocity:</strong> {cp["avg_daily_rate"]}%/day | {est_text}</p>
            <table style="font-size: 13px; margin-top: 10px;">
                <thead><tr><th>Date</th><th>Cumulative Tests</th><th>New Today</th><th>Coverage</th><th>Daily Add</th><th>Passed</th><th>Failed</th><th>Cum. Pass Ratio</th></tr></thead>
                <tbody>''' + ''.join([f'<tr><td>{d["date"]}</td><td>{d["cumulative_tests"]:,}</td><td>+{d["new_tests"]:,}</td><td>{d["coverage_pct"]}%</td><td>+{d["daily_add_pct"]}%</td><td>{d["day_passed"]:,}</td><td>{d["day_failed"]:,}</td><td>{d["cumulative_pass_ratio"]}%</td></tr>' for d in cp['days']]) + f'''</tbody>
            </table>
        </div>'''

    # Build changelog HTML
    build_changelog_html = generate_build_changelog_html(build_changelogs)
    
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
            {'<strong>CI Run Start:</strong> ' + ci_run_start + '<br>' if ci_run_start else ''}
            <strong>Version Status:</strong> {'✓ Active (Unreleased)' if version_info['is_active'] else '⚠️ Released/Archived'}<br>
            <strong>Report Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>

        {version_warning_html}

        <div class="summary-box">
            <div class="metric-card bugs">
                <div class="metric-label">Bug Status</div>
                <div class="metric-number">{len(bugs_on_dev) + len(bugs_on_qa)}</div>
                <div class="metric-detail">Open: Dev {len(bugs_on_dev)} | QA {len(bugs_on_qa)}<br>Closed this week: {len(bugs_closed_this_week)} | Total closed (sprint): {bugs_closed_total}</div>
            </div>
            <div class="metric-card automation">
                <div class="metric-label">Automation Tests</div>
                <div class="metric-number">{automation_data['total_tests']}</div>
                <div class="metric-detail">Executions: {automation_data['total_executions']}<br>Pass Ratio: {automation_data['pass_ratio']:.1f}%</div>
            </div>
            <div class="metric-card sub-exec">
                <div class="metric-label">Sub Test Executions</div>
                <div class="metric-number">{len(sub_execs)}</div>
                <div class="metric-detail">Testing: {sub_exec_xray_data['summary']['testing_coverage']:.0f}% | Auto: {sub_exec_xray_data['summary']['automation_coverage']:.0f}%<br>{sub_exec_xray_data['summary']['total_executed']}/{sub_exec_xray_data['summary']['total_tests']} tests executed</div>
            </div>
        </div>

        {'<div class="alert-box danger"><strong>⚠️ Critical Automation Failures:</strong> ' + str(automation_data["critical_failures"]) + ' tests failed on ALL platforms. Immediate investigation required.</div>' if automation_data.get('critical_failures', 0) > 0 else ''}
        {'<div class="alert-box" style="background-color: #fff3cd; border-left-color: #ffc107;"><strong>⚠️ Automation Bugs:</strong> ' + str(automation_data.get("automation_bugs_count", 0)) + ' bugs with automation origin opened during sprint - requires review.</div>' if automation_data.get("automation_bugs_count", 0) > 0 else ''}

        <div class="section-title">🤖 CI Iteration - Automation Status</div>
        <p><strong>Tests executed during {'current CI cycle (from ' + ci_run_start + ')' if ci_run_start else 'sprint'}:</strong> {automation_data['total_tests']} unique tests, {automation_data['total_executions']} total executions</p>
        <p><strong>Overall results:</strong> Passed: {automation_data['passed']} | Failed: {automation_data['failed']} | Pass Ratio: {automation_data['pass_ratio']:.1f}%</p>
        {'<p><strong>Test Coverage:</strong> Overall: ' + f"{automation_data.get('overall_coverage', 0):.1f}%" + '</p>' if automation_data.get('overall_coverage', 0) > 0 else ''}
        
        {coverage_progress_html}
        
        {build_changelog_html}
        
        {automation_chart_html}
        
        {('<div style="background: #fff3cd; border-left: 5px solid #ffc107; padding: 20px; margin: 20px 0; border-radius: 5px;"><h3 style="margin-top: 0; color: #856404;">📊 Rule-Based Insights <span style="font-size: 12px; background: #ffc107; color: #333; padding: 3px 8px; border-radius: 10px; margin-left: 8px;">DETERMINISTIC</span></h3><ul style="line-height: 1.8;">' + ''.join([f"<li>{insight}</li>" for insight in insights]) + '</ul></div>') if insights else ''}
        
        {('<div style="background: linear-gradient(135deg, #e0f7fa 0%, #e1f5fe 100%); border-left: 5px solid #0288d1; padding: 25px; margin: 20px 0; border-radius: 5px; box-shadow: 0 2px 8px rgba(2, 136, 209, 0.1);"><h3 style="margin-top: 0; color: #01579b;">🤖 AI-Generated Insights <span style="font-size: 12px; background: #0288d1; color: white; padding: 3px 8px; border-radius: 10px; margin-left: 8px;">O3-MINI</span></h3><div style="line-height: 1.8; color: #263238;">' + ai_insights + '</div></div>') if ai_insights else ''}
        
        {platform_html}
        
        {('<h3>🐛 Automation Bugs During Sprint</h3><p>' + str(len(automation_data.get("automation_bugs", []))) + ' bugs with automation origin found during sprint period</p><table><thead><tr><th>Key</th><th>Summary</th><th>Status</th><th>Priority</th><th>Created</th></tr></thead><tbody>' + ''.join([f'<tr><td><a href="https://rwrnd.atlassian.net/browse/{bug["key"]}">{bug["key"]}</a></td><td>{html.escape(bug["summary"])}</td><td>{html.escape(bug["status"])}</td><td>{html.escape(bug["priority"])}</td><td>{bug["created"]}</td></tr>' for bug in automation_data.get("automation_bugs", [])]) + '</tbody></table>') if automation_data.get("automation_bugs") else ''}

        <div class="section-title">🐛 Bug Status</div>
        {bugs_chart_html}
        
        <h2>Historical Bug Trend from Release Start</h2>
        <p>Weekly tracking from {historical_trends['dates'][0] if historical_trends['dates'] else 'N/A'} to present ({len(historical_trends['dates'])} weeks) - Current: Total: {len(bugs)}, On Dev: {len(bugs_on_dev)}, On QA: {len(bugs_on_qa)}</p>
        {historical_chart_html}
        
        <h2>High/Critical Priority Bug Trend</h2>
        <p>Tracking only HIGH, HIGHEST, and CRITICAL priority bugs from {historical_trends['high_sev_dates'][0] if historical_trends['high_sev_dates'] else 'N/A'} to present - Current: Total: {historical_trends['high_sev_total'][-1] if historical_trends['high_sev_total'] else 0}, On Dev: {historical_trends['high_sev_dev'][-1] if historical_trends['high_sev_dev'] else 0}, On QA: {historical_trends['high_sev_qa'][-1] if historical_trends['high_sev_qa'] else 0}</p>
        {high_sev_chart_html}
        
        {f'<h2>Open Bugs Distribution Across Releases</h2><p>All open bugs (Dev + QA) across releases - Total releases with open bugs: {len(historical_trends["release_distribution"])}</p>{release_dist_chart_html}' if release_dist_chart_html else ''}
        
        {priority_html}

        <h2>Bugs on Dev ({len(bugs_on_dev)} bugs)</h2>
        <p>Status: In Progress, To-Do, or None (assigned but not started)</p>
        <table>
            <thead><tr><th>Key</th><th>Priority</th><th>Summary</th><th>Status</th><th>Resolution</th><th>Assignee</th></tr></thead>
            <tbody>
                {''.join([f'<tr><td><a href="https://rwrnd.atlassian.net/browse/{bug.key}" class="bug-key">{bug.key}</a></td><td>{html.escape(bug.fields.priority.name) if hasattr(bug.fields, "priority") and bug.fields.priority else "N/A"}</td><td>{html.escape(bug.fields.summary)}</td><td>{html.escape(bug.fields.status.name)}</td><td>{html.escape(bug.fields.resolution.name) if hasattr(bug.fields, "resolution") and bug.fields.resolution else "Unresolved"}</td><td>{html.escape(bug.fields.assignee.displayName) if hasattr(bug.fields, "assignee") and bug.fields.assignee else "Unassigned"}</td></tr>' for bug in bugs_on_dev[:20]]) if bugs_on_dev else '<tr><td colspan="6" style="text-align: center;">No bugs on Dev</td></tr>'}
            </tbody>
        </table>

        <h2>Bugs on QA ({len(bugs_on_qa)} bugs)</h2>
        <p>Status: Completed - awaiting QA verification</p>
        <table>
            <thead><tr><th>Key</th><th>Priority</th><th>Summary</th><th>Status</th><th>Resolution</th><th>Assignee</th></tr></thead>
            <tbody>
                {''.join([f'<tr><td><a href="https://rwrnd.atlassian.net/browse/{bug.key}" class="bug-key">{bug.key}</a></td><td>{html.escape(bug.fields.priority.name) if hasattr(bug.fields, "priority") and bug.fields.priority else "N/A"}</td><td>{html.escape(bug.fields.summary)}</td><td>{html.escape(bug.fields.status.name)}</td><td>{html.escape(bug.fields.resolution.name) if hasattr(bug.fields, "resolution") and bug.fields.resolution else "Unresolved"}</td><td>{html.escape(bug.fields.assignee.displayName) if hasattr(bug.fields, "assignee") and bug.fields.assignee else "Unassigned"}</td></tr>' for bug in bugs_on_qa[:20]]) if bugs_on_qa else '<tr><td colspan="6" style="text-align: center;">No bugs on QA</td></tr>'}
            </tbody>
        </table>

        <div class="section-title">🧪 Sub Test Execution Status</div>
        <p><strong>Total:</strong> {len(sub_execs)} | <strong>Completed:</strong> {sub_exec_completed} ({sub_exec_completed/max(len(sub_execs),1)*100:.1f}%) | <strong>In Progress:</strong> {sub_exec_in_progress} | <strong>Not Started:</strong> {sub_exec_not_started}</p>
        
        {sub_exec_chart_html}
        
        {'<div class="alert-box info"><strong>Status:</strong> All test executions completed ✓</div>' if len(sub_execs) > 0 and sub_exec_completed == len(sub_execs) else ''}
        {'<div class="alert-box"><strong>Status:</strong> ' + str(sub_exec_not_started) + ' test executions not started</div>' if sub_exec_not_started > 0 else ''}
        
        <h3>📊 Xray Execution Metrics</h3>
        {'<div class="summary-box"><div class="metric-card" style="background: linear-gradient(135deg, #00b894 0%, #00cec9 100%); color: white;"><div class="metric-label">Total Test Runs</div><div class="metric-number">' + str(sub_exec_xray_data["summary"]["total_tests"]) + '</div><div class="metric-detail">Across ' + str(len([e for e in sub_exec_xray_data["executions"] if e["tests"] > 0])) + ' sub test executions</div></div><div class="metric-card" style="background: linear-gradient(135deg, #6c5ce7 0%, #a29bfe 100%); color: white;"><div class="metric-label">Testing Coverage</div><div class="metric-number">' + f'{sub_exec_xray_data["summary"]["testing_coverage"]:.1f}%' + '</div><div class="metric-detail">' + str(sub_exec_xray_data["summary"]["total_executed"]) + ' / ' + str(sub_exec_xray_data["summary"]["total_tests"]) + ' tests have results</div></div><div class="metric-card" style="background: linear-gradient(135deg, ' + ('#27ae60 0%, #2ecc71' if sub_exec_xray_data["summary"]["pass_ratio"] >= 90 else '#f39c12 0%, #f1c40f' if sub_exec_xray_data["summary"]["pass_ratio"] >= 70 else '#e74c3c 0%, #c0392b') + ' 100%); color: white;"><div class="metric-label">Pass Ratio</div><div class="metric-number">' + f'{sub_exec_xray_data["summary"]["pass_ratio"]:.1f}%' + '</div><div class="metric-detail">' + str(sub_exec_xray_data["summary"]["total_passed"]) + ' / ' + str(sub_exec_xray_data["summary"]["total_executed"]) + ' tests passed</div></div><div class="metric-card" style="background: linear-gradient(135deg, #e17055 0%, #fdcb6e 100%); color: white;"><div class="metric-label">Automation Coverage</div><div class="metric-number">' + f'{sub_exec_xray_data["summary"]["automation_coverage"]:.1f}%' + '</div><div class="metric-detail">' + str(sub_exec_xray_data["summary"]["automated_count"]) + ' automated of ' + str(sub_exec_xray_data["summary"]["automated_count"] + sub_exec_xray_data["summary"]["candidate_count"] + sub_exec_xray_data["summary"]["manual_count"]) + ' tests</div></div><div class="metric-card" style="background: linear-gradient(135deg, #00cec9 0%, #81ecec 100%); color: white;"><div class="metric-label">Automation Potential</div><div class="metric-number">' + f'{sub_exec_xray_data["summary"]["automation_potential"]:.1f}%' + '</div><div class="metric-detail">Automated + Candidates</div></div></div>' if sub_exec_xray_data["summary"]["total_tests"] > 0 else '<div class="alert-box info"><strong>Note:</strong> No Xray data available for these Sub Test Executions.</div>'}
        
        {'<h4>Rally Test Method Breakdown</h4><table style="max-width: 600px;"><thead><tr><th>Method</th><th>Count</th><th>Rate</th><th>Bar</th></tr></thead><tbody><tr><td><span style="background-color:#17a2b8; color:white; padding:2px 8px; border-radius:4px;">Automated</span></td><td style="text-align:center;">' + str(sub_exec_xray_data["summary"]["automated_count"]) + '</td><td style="text-align:center;">' + f'{sub_exec_xray_data["summary"]["automated_rate"]:.1f}%' + '</td><td><div style="background:#e0e0e0; border-radius:4px; overflow:hidden;"><div style="background:#17a2b8; height:20px; width:' + f'{min(sub_exec_xray_data["summary"]["automated_rate"], 100):.0f}%' + ';"></div></div></td></tr><tr><td><span style="background-color:#fd7e14; color:white; padding:2px 8px; border-radius:4px;">Automation Candidate</span></td><td style="text-align:center;">' + str(sub_exec_xray_data["summary"]["candidate_count"]) + '</td><td style="text-align:center;">' + f'{sub_exec_xray_data["summary"]["candidate_rate"]:.1f}%' + '</td><td><div style="background:#e0e0e0; border-radius:4px; overflow:hidden;"><div style="background:#fd7e14; height:20px; width:' + f'{min(sub_exec_xray_data["summary"]["candidate_rate"], 100):.0f}%' + ';"></div></div></td></tr><tr><td><span style="background-color:#6c757d; color:white; padding:2px 8px; border-radius:4px;">Manual</span></td><td style="text-align:center;">' + str(sub_exec_xray_data["summary"]["manual_count"]) + '</td><td style="text-align:center;">' + f'{sub_exec_xray_data["summary"]["manual_rate"]:.1f}%' + '</td><td><div style="background:#e0e0e0; border-radius:4px; overflow:hidden;"><div style="background:#6c757d; height:20px; width:' + f'{min(sub_exec_xray_data["summary"]["manual_rate"], 100):.0f}%' + ';"></div></div></td></tr><tr><td><span style="background-color:#dc3545; color:white; padding:2px 8px; border-radius:4px;">NA / Not Set</span></td><td style="text-align:center;">' + str(sub_exec_xray_data["summary"]["na_count"]) + '</td><td style="text-align:center;">' + f'{sub_exec_xray_data["summary"]["na_rate"]:.1f}%' + '</td><td><div style="background:#e0e0e0; border-radius:4px; overflow:hidden;"><div style="background:#dc3545; height:20px; width:' + f'{min(sub_exec_xray_data["summary"]["na_rate"], 100):.0f}%' + ';"></div></div></td></tr></tbody></table>' if sub_exec_xray_data["summary"]["total_tests"] > 0 else ''}
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0;">
            {f'<div class="chart-container">{xray_exec_rate_chart_html}</div>' if xray_exec_rate_chart_html else ''}
            {f'<div class="chart-container">{xray_method_chart_html}</div>' if xray_method_chart_html else ''}
        </div>
        
        {'<h3>Detailed Execution Data by Sub Test Execution</h3>' + generate_xray_detail_table(sub_exec_xray_data["executions"]) if sub_exec_xray_data["executions"] and any(e["tests"] > 0 for e in sub_exec_xray_data["executions"]) else ''}
        
        <h3>Sub Test Executions by Team</h3>
        <table>
            <thead>
                <tr>
                    <th>Scrum Team</th>
                    <th>Total</th>
                    <th>Done</th>
                    <th>In Progress</th>
                    <th>Not Started</th>
                    <th>Completion %</th>
                </tr>
            </thead>
            <tbody>
                {''.join([f'<tr><td><strong>{team}</strong></td><td>{stats["total"]}</td><td>{stats["Done"]}</td><td>{stats["In Progress"]}</td><td>{stats["Not Started"]}</td><td>{(stats["Done"]/stats["total"]*100):.1f}%</td></tr>' for team, stats in sorted(team_stats.items(), key=lambda x: (-x[1]["total"], x[0]))]) if team_stats else '<tr><td colspan="6" style="text-align: center;">No sub test executions found</td></tr>'}
            </tbody>
        </table>

        <h3>All Sub Test Executions</h3>
        <table>
            <thead>
                <tr>
                    <th>Key</th>
                    <th>Summary</th>
                    <th>Scrum Team</th>
                    <th>Assignee</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {''.join([f'<tr><td><a href="https://rwrnd.atlassian.net/browse/{se.key}">{se.key}</a></td><td>{html.escape(se.fields.summary)}</td><td>{html.escape(get_team_name(se))}</td><td>{html.escape(se.fields.assignee.displayName if hasattr(se.fields, "assignee") and se.fields.assignee else "Unassigned")}</td><td>{html.escape(se.fields.status.name)}</td></tr>' for se in sorted(sub_execs, key=lambda x: (get_team_name(x), x.fields.summary))]) if sub_execs else '<tr><td colspan="5" style="text-align: center;">No sub test executions found</td></tr>'}
            </tbody>
        </table>

        <h3>Sub Test Execution Analysis</h3>
        {'<div class="alert-box info"><strong>Status:</strong> No sub test executions found for this version. Test execution tracking may not have started yet, or tests are being tracked in a different manner.</div>' if len(sub_execs) == 0 else ''}
        <div class="observation-list">
            <ul>
                <li><strong>Total Test Executions:</strong> {len(sub_execs)}</li>
                <li><strong>Completion Status:</strong> 
                    {'All test executions completed ✓' if len(sub_execs) > 0 and sub_exec_completed == len(sub_execs) else 
                     f"{sub_exec_completed}/{len(sub_execs)} completed ({sub_exec_completed/max(len(sub_execs),1)*100:.1f}%)" if len(sub_execs) > 0 else
                     'No active test executions (0/0 completed)'}
                </li>
                <li><strong>In Progress:</strong> {sub_exec_in_progress} test execution{'s' if sub_exec_in_progress != 1 else ''} currently being executed</li>
                <li><strong>Not Started:</strong> {sub_exec_not_started} test execution{'s' if sub_exec_not_started != 1 else ''} pending</li>
                <li><strong>Recommendation:</strong> 
                    {'⚠️ Sub test execution tracking should be initiated for this release version to ensure proper test coverage validation' if len(sub_execs) == 0 else
                     '✓ Test execution in progress - continue monitoring' if sub_exec_in_progress > 0 and sub_exec_not_started == 0 else
                     '✓ All test executions completed successfully!' if sub_exec_completed == len(sub_execs) and len(sub_execs) > 0 else
                     f'⚠️ {sub_exec_not_started} test execution{"s" if sub_exec_not_started != 1 else ""} not started - review test execution plan'}
                </li>
            </ul>
        </div>

        <div class="section-title">📊 Test Method Distribution</div>
        <p><strong>Total Tests:</strong> {test_method_data['total_tests']} | <strong>Data Source:</strong> {test_method_data.get('source', 'unknown').upper()}</p>
        
        {test_method_chart_html if test_method_data['total_tests'] > 0 else '<div class="alert-box info"><strong>Note:</strong> No test method data available. Generate test_method_distribution_sub_exec_topics_{version.replace(".", "_")}.csv to enable this section.</div>'}
        
        {'<h3>Test Method Breakdown</h3><table><thead><tr><th>Method</th><th>Count</th><th>Percentage</th></tr></thead><tbody>' + ''.join([f"<tr><td><span style='color: {'#4caf50' if m == 'Automated' else '#2196f3' if m == 'Manual' else '#ff9800' if m == 'Automation Candidate' else '#9e9e9e'}; font-weight: bold;'>{m}</span></td><td>{test_method_data['by_method'].get(m, 0)}</td><td>{(test_method_data['by_method'].get(m, 0) / max(test_method_data['total_tests'], 1) * 100):.1f}%</td></tr>" for m in ['Automated', 'Manual', 'Automation Candidate', 'Not Specified']]) + '</tbody></table>' if test_method_data['total_tests'] > 0 else ''}
        
        {'<div class="observation-list"><h4>Automation Coverage Analysis</h4><ul><li><strong>Automation Rate:</strong> ' + f"{((test_method_data['by_method'].get('Automated', 0)) / max(test_method_data['total_tests'], 1) * 100):.1f}%" + ' of tests are automated</li><li><strong>Automation Candidates:</strong> ' + f"{test_method_data['by_method'].get('Automation Candidate', 0)}" + ' tests identified for future automation</li><li><strong>Manual Tests:</strong> ' + f"{test_method_data['by_method'].get('Manual', 0)}" + ' tests require manual execution</li></ul></div>' if test_method_data['total_tests'] > 0 else ''}

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
    print(f"Bugs: {len(bugs_on_dev)} on Dev | {len(bugs_on_qa)} on QA | {len(bugs_closed_this_week)} closed this week | {bugs_closed_total} total closed (sprint)")
    print(f"Automation: {automation_data['total_tests']} tests | {automation_data['pass_ratio']:.1f}% pass ratio")
    print(f"Critical Failures: {automation_data.get('critical_failures', 0)} tests failing on all platforms")
    print(f"Sub Test Executions: {sub_exec_completed}/{len(sub_execs)} completed")
    if test_method_data['total_tests'] > 0:
        automated = test_method_data['by_method'].get('Automated', 0)
        manual = test_method_data['by_method'].get('Manual', 0)
        candidates = test_method_data['by_method'].get('Automation Candidate', 0)
        print(f"Test Methods: {automated} Automated | {manual} Manual | {candidates} Candidates")
    print("=" * 70)
    
    conn.close()

if __name__ == "__main__":
    main()
