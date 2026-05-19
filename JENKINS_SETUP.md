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

### GitHub Token (Optional - for AI-powered insights)
4. **ID:** `dp_qa_copilot`
   - **Type:** Secret text
   - **Value:** GitHub Personal Access Token
   - **Purpose:** Enables AI-generated insights in weekly reports via GitHub Models API
   - **Get token:** https://github.com/settings/tokens
   - **Note:** If not provided, reports will use rule-based insights only

### PostgreSQL Credentials (Optional - for release readiness reports)
5. **ID:** `postgres-host`
   - **Type:** Secret text
   - **Value:** `10.185.20.124`

6. **ID:** `postgres-db`
   - **Type:** Secret text
   - **Value:** `results`

7. **ID:** `postgres-user`
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

## Dedicated Device Tag Tracking Job

Use this job when you want to track changes to device labels stored in PostgreSQL `public.device.tag` independently from the weekly release report.

1. **New Item:**
   - Name: `DefensePro-Device-Tag-Tracker`
   - Type: Pipeline

2. **Pipeline Configuration:**
   - **Definition:** Pipeline script from SCM
   - **SCM:** Git
   - **Repository URL:** `https://github.com/rdwr-eranp/defensepro-jira-monitor.git`
   - **Branch:** `*/main`
   - **Script Path:** `Jenkinsfile.device-tag-tracker`

3. **Schedule:**
   - The dedicated Jenkinsfile runs every hour using `cron('H * * * *')`.

4. **Credentials:**
   - Preferred: Jenkins secret text credential `pg-password` for the PostgreSQL password.
   - Also supported: Jenkins username/password credential `pg-password` with username `postgres` and the PostgreSQL password.
   - Also supported: Jenkins username/password credential `postgres-user` with username `postgres` and the PostgreSQL password.
   - The job uses these database defaults unless overridden in the environment: `PG_HOST=10.185.20.124`, `PG_PORT=5432`, `PG_DATABASE=results`, `PG_USER=postgres`.

5. **How tracking works:**
   - `device_tag_tracker.py` reads the current `public.device` map.
   - The job stores the previous snapshot in `device_tag_tracking_state/latest_device_tags.csv` inside the Jenkins workspace.
   - Every detected change is appended to `device_tag_tracking_state/device_tag_change_history.csv` with the run timestamp, Jenkins job name, build number, build URL, device ID/IP, old tag, and new tag.
   - A single cumulative HTML trace is updated every run at `device_tag_tracking_state/device_tag_change_history.html`.
   - Each run compares the current snapshot to the previous one and archives `device_tag_tracking/device_tag_report.html`, `device_tag_tracking/device_tag_tracking_history.html`, `device_tag_tracking/device_tag_report.md`, `device_tag_tracking/device_tag_changes.csv`, and JSON/CSV snapshots.
   - The Jenkinsfile fingerprints archived artifacts and keeps the last 365 builds/artifact sets by default, so the Jenkins build history becomes the trace timeline.
   - If the Jenkins workspace is deleted, the next run creates a fresh baseline and reports changes from the following run onward.

6. **Parameters:**
   - `EMAIL_RECIPIENTS`: Recipients for change notifications.
   - `STATE_DIR`: Persistent snapshot directory. Keep the default unless the workspace is routinely cleaned.
   - `SEND_EMAIL_ON_NO_CHANGE`: Send a status email even when no changes are detected.
   - `FAIL_ON_CHANGE`: Mark the build as failed after artifacts/email are produced when tag changes are detected.

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
