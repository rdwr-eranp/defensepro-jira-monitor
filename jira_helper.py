from jira import JIRA
import os
from dotenv import load_dotenv

load_dotenv()

class JiraHelper:
    def __init__(self):
        verify_ssl = os.getenv('JIRA_VERIFY_SSL', 'True').lower() in ('true', '1', 'yes')
        options = {'server': os.getenv('JIRA_URL'), 'verify': verify_ssl}
        self.jira = JIRA(
            options=options,
            basic_auth=(os.getenv('JIRA_EMAIL'), os.getenv('JIRA_API_TOKEN'))
        )
    
    def get_issue(self, issue_key):
        """Get a specific issue by key"""
        return self.jira.issue(issue_key)
    
    def create_issue(self, project_key, summary, description, issue_type="Task"):
        """Create a new issue"""
        issue_dict = {
            'project': {'key': project_key},
            'summary': summary,
            'description': description,
            'issuetype': {'name': issue_type},
        }
        return self.jira.create_issue(fields=issue_dict)
    
    def update_issue(self, issue_key, **fields):
        """Update an existing issue"""
        issue = self.jira.issue(issue_key)
        issue.update(fields=fields)
        return issue
    
    def add_comment(self, issue_key, comment):
        """Add a comment to an issue"""
        return self.jira.add_comment(issue_key, comment)
    
    def transition_issue(self, issue_key, transition_name):
        """Transition an issue to a different status"""
        transitions = self.jira.transitions(issue_key)
        for t in transitions:
            if t['name'].lower() == transition_name.lower():
                self.jira.transition_issue(issue_key, t['id'])
                return True
        return False
    
    def search_issues(self, jql_query, max_results=50):
        """Search for issues using JQL"""
        return self.jira.search_issues(jql_query, maxResults=max_results)
    
    def get_projects(self):
        """Get all projects"""
        return self.jira.projects()
