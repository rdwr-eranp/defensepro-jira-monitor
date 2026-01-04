# Jenkins Setup Guide for DefensePro Weekly Report

## Prerequisites

1. **Jenkins Plugins Required:**
   - Git Plugin
   - Pipeline Plugin
   - Email Extension Plugin
   - HTML Publisher Plugin
   - Credentials Plugin

2. **Python Environment:**
   - Python 3.8+ installed on Jenkins agent
   - pip package manager

## Step 1: Configure Jenkins Credentials

Add the following credentials in Jenkins (Manage Jenkins → Credentials → System → Global credentials):

### Jira Credentials
1. **ID:** `jira-url`
   - **Type:** Secret text
   - **Value:** `https://rwrnd.atlassian.net`

2. **ID:** `jira-email`
   - **Type:** Secret text
   - **Value:** Your Jira email address

3. **ID:** `jira-api-token`
   - **Type:** Secret text
   - **Value:** Your Jira API token (from .env file)

### PostgreSQL Credentials (Optional - for release readiness reports)
4. **ID:** `postgres-host`
   - **Type:** Secret text
   - **Value:** `10.185.20.124`

5. **ID:** `postgres-db`
   - **Type:** Secret text
   - **Value:** `results`

6. **ID:** `postgres-user`
   - **Type:** Username with password
   - **Username:** `postgres`
   - **Password:** `[password]`

## Step 2: Create Jenkins Pipeline Job

1. **New Item:**
   - Name: `DefensePro-Weekly-Report`
   - Type: Pipeline

2. **General Settings:**
   - Description: `Automated weekly bug report for DefensePro releases`
   - Discard old builds: Keep last 30 builds

3. **Pipeline Configuration:**
   - **Definition:** Pipeline script from SCM
   - **SCM:** Git
   - **Repository URL:** `https://github.com/rdwr-eranp/defensepro-jira-monitor.git`
   - **Branch:** `*/main`
   - **Script Path:** `Jenkinsfile`

4. **Build Triggers:**
   - Already configured in Jenkinsfile: Every Monday at 9:00 AM

## Step 3: Configure Email Notifications

1. **Manage Jenkins → Configure System → Extended E-mail Notification:**
   - SMTP server: Your mail server
   - Default recipients: Your team email list
   - Use SSL/TLS as needed

2. **Update Jenkinsfile email addresses:**
   - Edit line with `to: 'eranp@radware.com'`
   - Add team distribution list

## Step 4: First Run

1. **Manual Trigger:**
   - Open the job: `DefensePro-Weekly-Report`
   - Click "Build Now"
   - Monitor console output

2. **Verify Output:**
   - Check "Weekly Work Summary" link
   - Check "Open Bugs Report" link
   - Download artifacts (HTML/CSV files)

## Step 5: Customize for Different Versions

To track a different release version, edit the Jenkinsfile:

```groovy
environment {
    VERSION = '10.13.0.0'  // Change to desired version
}
```

Or create multiple jobs for parallel version tracking:
- `DefensePro-Weekly-Report-10.12`
- `DefensePro-Weekly-Report-10.13`

## Troubleshooting

### Issue: Python module not found
**Solution:** Ensure `requirements.txt` is installed in Setup stage

### Issue: Jira authentication failed
**Solution:** Verify credentials IDs match in Jenkinsfile and Jenkins credentials store

### Issue: Reports not archived
**Solution:** Check workspace permissions and artifact archiving patterns

### Issue: Email not sent
**Solution:** Verify SMTP configuration and recipient addresses

## Advanced: Multi-Version Reporting

Create a parametrized job to support multiple versions:

```groovy
parameters {
    choice(name: 'VERSION', choices: ['10.13.0.0', '10.12.0.0', '10.14.0.0'], description: 'Release version to track')
}
```

## Cron Schedule Examples

```groovy
// Every Monday at 9:00 AM
cron('0 9 * * 1')

// Every day at 8:00 AM
cron('0 8 * * *')

// Twice a week: Monday and Thursday at 9:00 AM
cron('0 9 * * 1,4')
```

## Support

For issues or questions, contact: eranp@radware.com
Repository: https://github.com/rdwr-eranp/defensepro-jira-monitor
