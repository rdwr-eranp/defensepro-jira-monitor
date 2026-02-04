"""Quick test to verify team_stats table generation"""
from collections import defaultdict

# Simulate team_stats data
team_stats = defaultdict(lambda: {'Done': 0, 'In Progress': 0, 'Not Started': 0, 'total': 0})
team_stats['Abhishek'] = {'Done': 5, 'In Progress': 1, 'Not Started': 2, 'total': 8}
team_stats['John'] = {'Done': 3, 'In Progress': 2, 'Not Started': 1, 'total': 6}
team_stats['Unassigned'] = {'Done': 0, 'In Progress': 0, 'Not Started': 3, 'total': 3}

# Generate table HTML
table_html = f"""
<h3>Sub Test Executions by Team</h3>
<table>
    <thead>
        <tr>
            <th>Team/Assignee</th>
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
"""

print("Generated Table HTML:")
print(table_html)
