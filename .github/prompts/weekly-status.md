# Weekly Status Report

## Report Information
**Week:** {WEEK_NUMBER} (e.g., Week 51, 2025)
**Date Range:** {START_DATE} to {END_DATE}
**Project:** DP (DefensePro)
**Version:** {VERSION} (e.g., 10.12.0.0)
**Report Date:** {DATE}

---

## 1. Sprint Progress

### Active Sprint Status
Track current sprint progress and completion rate.

**Query:** Show me the active sprint status for project DP

**Metrics to Track:**
- Sprint name and dates
- Total story points committed vs completed
- Sprint progress percentage
- Burndown trend
- Stories by status (To Do, In Progress, Done)

---

## 2. Issues Activity

### Issues Created This Week
All new issues reported during the week.

**Query:** Show me all issues created in the last 7 days for project DP

**Breakdown by:**
- Issue type (Bug, Story, Task, Epic)
- Priority (Blocker, Critical, High, Medium, Low)
- Component/Feature area
- Assignee distribution

### Issues Closed This Week
All issues resolved during the week.

**Query:** Show me all issues closed in the last 7 days for project DP

**Metrics:**
- Total closed count
- Closure by priority
- Average time to close
- Top closers (team members)

---

## 3. Bug Health

### Open Bugs Snapshot
Current state of all open bugs.

**Query:** Show me all open bugs for project DP

**Analysis:**
- Total open bugs
- Bugs by priority
- Bugs by age (0-7 days, 8-30 days, 31-90 days, 90+ days)
- Oldest bugs requiring attention
- Blocker/Critical bugs count

### Bug Trend Analysis
Week-over-week bug trend.

**Metrics to Compare:**
- Bugs opened this week vs last week
- Bugs closed this week vs last week
- Net change in bug count
- Bug closure rate

---

## 4. Test Automation Status

### Test Execution Summary
Test runs executed during the week.

**PostgreSQL Query:**
```sql
SELECT 
    COUNT(DISTINCT test_name) as unique_tests,
    COUNT(*) as total_executions,
    SUM(CASE WHEN status = 'PASSED' THEN 1 ELSE 0 END) as passed,
    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed,
    ROUND(100.0 * SUM(CASE WHEN status = 'PASSED' THEN 1 ELSE 0 END) / COUNT(*), 2) as pass_rate
FROM test_execution
WHERE start_time >= CURRENT_DATE - INTERVAL '7 days'
```

**Metrics:**
- Total test executions
- Unique tests run
- Pass rate percentage
- Failed test count
- Top 10 failing tests

### Build Quality
Quality metrics for builds executed this week.

**Query:**
```sql
SELECT 
    version,
    COUNT(*) as executions,
    ROUND(AVG(CASE WHEN status = 'PASSED' THEN 100.0 ELSE 0.0 END), 2) as avg_pass_rate
FROM test_execution
WHERE start_time >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY version
ORDER BY version DESC
```

**Analysis:**
- Builds tested this week
- Pass rate per build
- Build quality trend
- Regression identification

---

## 5. Team Productivity

### Work Completed
Stories and tasks completed by the team.

**Query:** Show me all stories completed in the last 7 days for project DP

**Metrics:**
- Story points completed
- Stories completed by assignee
- Task completion rate
- Average story cycle time

### Work In Progress
Current workload status.

**Query:** Show me all issues in progress for project DP

**Analysis:**
- Total WIP items
- WIP by assignee
- WIP age (how long in progress)
- Potential blockers

---

## 6. Blocker & Critical Issues

### High Priority Items
All blocker and critical issues requiring immediate attention.

**Query:** Show me all blocker and critical issues for project DP

**Details to Include:**
- Issue key and summary
- Assignee
- Status
- Age
- Comments/updates this week

---

## 7. Upcoming Milestones

### Release Schedule
Upcoming releases and their readiness.

**Metrics:**
- Next release version and date
- Days until release
- Open issues for release
- Critical/Blocker issues for release
- Test coverage for release
- Release readiness score

---

## 8. Risk Assessment

### Risks Identified This Week
New or ongoing risks impacting the project.

**Categories:**
- **Technical Risks:** Architecture, performance, compatibility issues
- **Schedule Risks:** Delays, dependencies, resource constraints
- **Quality Risks:** Test coverage gaps, high defect rates, failing tests
- **Resource Risks:** Team availability, skill gaps, turnover

**For Each Risk:**
- Description
- Impact (High/Medium/Low)
- Probability (High/Medium/Low)
- Mitigation plan
- Owner

---

## 9. Action Items

### Follow-up Actions from Previous Week
Track completion of last week's action items.

**Status Update:**
- ✅ Completed actions
- 🔄 In-progress actions
- ⏸️ Blocked actions
- ❌ Cancelled actions

### New Action Items
Action items identified this week.

**For Each Action:**
- Description
- Owner
- Due date
- Priority

---

## 10. Key Achievements

### Wins This Week
Highlight significant accomplishments.

**Examples:**
- Major features completed
- Critical bugs fixed
- Performance improvements
- Process improvements
- Team milestones

---

## 11. Next Week Focus

### Priorities for Coming Week
Key objectives and goals.

**Focus Areas:**
- Sprint goals
- Critical issues to resolve
- Testing priorities
- Deployment plans
- Team events/meetings

---

## Report Generation Instructions

### Data Sources
- **Jira:** Bug tracking, sprint management, issue lifecycle
- **PostgreSQL (automationDB):** Test execution data, build quality metrics
- **MCP Atlassian Server:** Unified search and reporting

### Query Execution Order
1. **Jira Sprint Status** → Get active sprint information
2. **Jira Issues Activity** → Count created/closed issues this week
3. **Jira Open Bugs** → Current bug health snapshot
4. **PostgreSQL Test Execution** → Automation test metrics
5. **PostgreSQL Build Quality** → Build-level pass rates
6. **Jira Work Completed** → Team productivity metrics
7. **Jira Blockers** → High-priority issues
8. **Jira Release Schedule** → Upcoming milestones

### Report Format Options
- **Markdown:** Detailed text report with tables and metrics
- **PowerPoint:** Executive summary presentation (10-15 slides)
- **Excel:** Data-heavy report with charts and pivot tables
- **Streamlit Dashboard:** Interactive weekly status dashboard

---

## Example Queries

### Jira Queries

**Issues created this week:**
```
project = DP AND created >= -7d
```

**Issues closed this week:**
```
project = DP AND resolved >= -7d
```

**Open bugs by priority:**
```
project = DP AND type = Bug AND status != Closed ORDER BY priority DESC
```

**Blocker/Critical issues:**
```
project = DP AND priority in (Blocker, Critical) AND status not in (Closed, Done)
```

**Active sprint:**
```
project = DP AND sprint in openSprints()
```

### PostgreSQL Queries

**Weekly test summary:**
```sql
SELECT 
    DATE(start_time) as test_date,
    COUNT(*) as executions,
    SUM(CASE WHEN status = 'PASSED' THEN 1 ELSE 0 END) as passed,
    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed
FROM test_execution
WHERE start_time >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY DATE(start_time)
ORDER BY test_date;
```

**Top failing tests:**
```sql
SELECT 
    test_name,
    COUNT(*) as fail_count,
    MAX(start_time) as last_failure
FROM test_execution
WHERE status = 'FAILED'
    AND start_time >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY test_name
ORDER BY fail_count DESC
LIMIT 10;
```

**Build quality comparison:**
```sql
SELECT 
    version,
    COUNT(*) as total_tests,
    ROUND(100.0 * SUM(CASE WHEN status = 'PASSED' THEN 1 ELSE 0 END) / COUNT(*), 2) as pass_rate,
    MIN(start_time) as first_run,
    MAX(start_time) as last_run
FROM test_execution
WHERE start_time >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY version
ORDER BY version DESC;
```

---

## Automation Tips

### Schedule Weekly Report Generation
- **Frequency:** Every Friday at 4 PM
- **Recipients:** Engineering team, management, QA leads
- **Format:** Email with embedded dashboard link + attached PDF

### Key Performance Indicators (KPIs)
1. **Sprint Velocity:** Story points completed per sprint
2. **Bug Closure Rate:** Bugs closed / Bugs opened
3. **Test Pass Rate:** % tests passing across all builds
4. **Cycle Time:** Average time from issue creation to closure
5. **WIP Age:** Average time issues spend in progress
6. **Release Readiness:** % completion toward next release

### Alert Thresholds
- 🔴 **Critical:** Pass rate < 85%, Blocker bugs > 0, Sprint behind by 20%+
- 🟠 **Warning:** Pass rate 85-90%, Critical bugs > 3, Sprint behind by 10-20%
- 🟢 **Good:** Pass rate > 90%, No blockers/criticals, Sprint on track

---

## Template Variables

Replace these placeholders when generating the report:

- `{WEEK_NUMBER}`: Week number of the year (e.g., 51)
- `{START_DATE}`: Monday of the week (e.g., December 18, 2025)
- `{END_DATE}`: Sunday of the week (e.g., December 24, 2025)
- `{DATE}`: Report generation date (e.g., December 23, 2025)
- `{PROJECT}`: Project key (e.g., DP)
- `{VERSION}`: Version number (e.g., 10.12.0.0)
- `{SPRINT_NAME}`: Current sprint name
- `{NEXT_RELEASE}`: Next release version (e.g., 10.12.0.0)
- `{RELEASE_DATE}`: Next release date (e.g., December 31, 2025)
