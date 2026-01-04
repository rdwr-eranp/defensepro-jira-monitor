import os
from dotenv import load_dotenv
from jira import JIRA
from datetime import datetime

load_dotenv()

# Connect to Jira
jira_url = os.getenv('JIRA_URL')
jira_email = os.getenv('JIRA_EMAIL')
jira_api_token = os.getenv('JIRA_API_TOKEN')

options = {'server': jira_url, 'verify': False}
jira = JIRA(options=options, basic_auth=(jira_email, jira_api_token))

# Get all open bugs (not Accepted, Closed, or Trash)
jql = 'project = DP AND type = Bug AND status NOT IN (Accepted, Closed, Trash) ORDER BY fixVersion DESC, priority DESC'
bugs = jira.search_issues(jql, maxResults=False, fields='key,fixVersions,status,priority,customfield_10129,summary,assignee')

# Filter out DP Runners team and 10.100.0.0 release
filtered_bugs = []
for bug in bugs:
    # Skip bugs assigned to DP Runners team
    scrum_team = getattr(bug.fields, 'customfield_10129', None)
    if scrum_team:
        team_name = scrum_team.value if hasattr(scrum_team, 'value') else str(scrum_team)
        if team_name == 'DP Runners':
            continue
    
    # Skip bugs on 10.100.0.0 release
    if bug.fields.fixVersions:
        version = bug.fields.fixVersions[0].name
        if version == '10.100.0.0':
            continue
    
    filtered_bugs.append(bug)

print(f"\nGenerating HTML report for {len(filtered_bugs)} open bugs...\n")

# Group by release
from collections import defaultdict
releases = defaultdict(list)

for bug in filtered_bugs:
    if bug.fields.fixVersions:
        version = bug.fields.fixVersions[0].name
    else:
        version = 'Unassigned'
    releases[version].append(bug)

# Generate HTML
html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Open Bugs Report - {datetime.now().strftime('%Y-%m-%d')}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            margin: 0;
            font-size: 32px;
        }}
        .header p {{
            margin: 10px 0 0 0;
            font-size: 18px;
            opacity: 0.9;
        }}
        .release-section {{
            background: white;
            margin-bottom: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .release-header {{
            background: #4a5568;
            color: white;
            padding: 15px 20px;
            font-size: 20px;
            font-weight: bold;
        }}
        .bug-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .bug-table th {{
            background-color: #f7fafc;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #2d3748;
            border-bottom: 2px solid #e2e8f0;
        }}
        .bug-table td {{
            padding: 12px;
            border-bottom: 1px solid #e2e8f0;
        }}
        .bug-table tr:hover {{
            background-color: #f7fafc;
        }}
        .bug-key {{
            font-weight: 600;
            color: #3182ce;
            text-decoration: none;
        }}
        .bug-key:hover {{
            text-decoration: underline;
        }}
        .priority {{
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            display: inline-block;
        }}
        .priority-blocker {{ background-color: #feb2b2; color: #742a2a; }}
        .priority-critical {{ background-color: #fc8181; color: #742a2a; }}
        .priority-high {{ background-color: #f6ad55; color: #7c2d12; }}
        .priority-medium {{ background-color: #fbd38d; color: #7c2d12; }}
        .priority-low {{ background-color: #9ae6b4; color: #22543d; }}
        .status {{
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            display: inline-block;
        }}
        .status-completed {{ background-color: #bee3f8; color: #2c5282; }}
        .status-none {{ background-color: #e2e8f0; color: #2d3748; }}
        .status-trash {{ background-color: #fed7d7; color: #742a2a; }}
        .summary {{
            color: #4a5568;
            max-width: 500px;
        }}
        .team {{
            color: #718096;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Open Bugs on Active Releases</h1>
        <p>Total: {len(filtered_bugs)} bugs (Excluding DP Runners Team) | Generated: {datetime.now().strftime('%B %d, %Y %H:%M')}</p>
    </div>
"""

# Generate table for each release
for version in sorted(releases.keys(), reverse=True):
    bugs_in_release = releases[version]
    html_content += f"""
    <div class="release-section">
        <div class="release-header">{version} ({len(bugs_in_release)} bugs)</div>
        <table class="bug-table">
            <thead>
                <tr>
                    <th>Bug Key</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Team</th>
                    <th>Summary</th>
                </tr>
            </thead>
            <tbody>
"""
    
    for bug in bugs_in_release:
        priority = bug.fields.priority.name if hasattr(bug.fields, 'priority') and bug.fields.priority else 'None'
        priority_class = priority.lower().replace(' ', '-')
        
        status = bug.fields.status.name
        status_class = status.lower().replace(' ', '-')
        
        scrum_team = getattr(bug.fields, 'customfield_10129', None)
        team = scrum_team.value if scrum_team and hasattr(scrum_team, 'value') else 'None'
        
        summary = bug.fields.summary
        jira_link = f"https://rwrnd.atlassian.net/browse/{bug.key}"
        
        html_content += f"""
                <tr>
                    <td><a href="{jira_link}" class="bug-key" target="_blank">{bug.key}</a></td>
                    <td><span class="priority priority-{priority_class}">{priority}</span></td>
                    <td><span class="status status-{status_class}">{status}</span></td>
                    <td class="team">{team}</td>
                    <td class="summary">{summary}</td>
                </tr>
"""
    
    html_content += """
            </tbody>
        </table>
    </div>
"""

html_content += """
</body>
</html>
"""

# Save to file
output_file = 'open_bugs_report.html'
with open(output_file, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"✓ Report saved to {output_file}")
print(f"  Total bugs: {len(filtered_bugs)}")
print(f"  Releases: {len(releases)}")

