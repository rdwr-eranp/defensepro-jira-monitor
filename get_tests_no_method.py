#!/usr/bin/env python3
"""Get tests from Sub Test Executions that have no Rally Test Method set."""

import requests
import os
import urllib3
from dotenv import load_dotenv
from jira import JIRA

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

# Xray auth
XRAY_CLIENT_ID = '7DC37640C3B6422D91E978570801CCF8'
XRAY_CLIENT_SECRET = '757b92c3039c706606ee29fe74e7c9d28c0a9c80bc013f6999f5910f20d347d8'

# Get Xray token
auth_response = requests.post(
    'https://xray.cloud.getxray.app/api/v2/authenticate',
    json={'client_id': XRAY_CLIENT_ID, 'client_secret': XRAY_CLIENT_SECRET},
    verify=False
)
xray_token = auth_response.json()

# Connect to Jira
options = {'server': os.getenv('JIRA_URL'), 'verify': False}
jira = JIRA(options=options, basic_auth=(os.getenv('JIRA_EMAIL'), os.getenv('JIRA_API_TOKEN')))

# Get Sub Test Executions for 10.13.0.0
sub_execs = jira.search_issues('project = DP AND type = "sub test execution" AND fixVersion = "10.13.0.0"', maxResults=False)
print(f'Found {len(sub_execs)} Sub Test Executions')

# Get Xray IDs
headers = {'Authorization': f'Bearer {xray_token}', 'Content-Type': 'application/json'}
graphql_url = 'https://xray.cloud.getxray.app/api/v2/graphql'

# Map Jira keys to Xray IDs
jira_keys = [issue.key for issue in sub_execs]
query = 'query { getTestExecutions(jql: "key in (%s)", limit: 100) { results { issueId jira(fields: ["key"]) } } }' % ','.join(jira_keys)
response = requests.post(graphql_url, headers=headers, json={'query': query}, verify=False)
data = response.json()

xray_map = {}
for result in data.get('data', {}).get('getTestExecutions', {}).get('results', []):
    jira_data = result.get('jira', {})
    key = jira_data.get('key') if isinstance(jira_data, dict) else None
    if key:
        xray_map[key] = result['issueId']

print(f'Mapped {len(xray_map)} Xray IDs')

# Collect all tests with no method
tests_no_method = []
for exec_key in jira_keys:
    xray_id = xray_map.get(exec_key)
    if not xray_id:
        continue
    
    query = 'query { getTestExecution(issueId: "%s") { testRuns(limit: 100) { results { test { issueId jira(fields: ["key", "summary", "customfield_10154"]) } } } } }' % xray_id
    response = requests.post(graphql_url, headers=headers, json={'query': query}, verify=False)
    data = response.json()
    
    test_runs = data.get('data', {}).get('getTestExecution', {}).get('testRuns', {}).get('results', [])
    for run in test_runs:
        test = run.get('test', {})
        jira_data = test.get('jira', {})
        if isinstance(jira_data, dict):
            key = jira_data.get('key')
            summary = jira_data.get('summary', '')
            method = jira_data.get('customfield_10154')
            method_value = method.get('value') if isinstance(method, dict) else None
            if not method_value or method_value == 'NA':
                tests_no_method.append((key, summary[:60], method_value or 'Not Set'))

# Deduplicate
seen = set()
unique_tests = []
for t in tests_no_method:
    if t[0] not in seen:
        seen.add(t[0])
        unique_tests.append(t)

print(f'\nFound {len(unique_tests)} tests with no Rally Test Method:\n')
for key, summary, method in sorted(unique_tests):
    print(f'{key}: {summary}... [{method}]')

print(f'\n--- JQL Query ---')
keys = [t[0] for t in unique_tests]
print(f'key in ({",".join(keys)})')
