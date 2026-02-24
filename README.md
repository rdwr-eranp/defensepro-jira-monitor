# DefensePro Release Analysis System

Automated release readiness and gate analysis system for DefensePro releases, integrating PostgreSQL test execution data with Jira bug tracking, and Xray Cloud API for test management.

## Overview

This system generates comprehensive release readiness reports and gate analysis for DefensePro releases by analyzing automated test coverage across multiple platforms, tracking bug status through Jira, and monitoring manual test execution via Xray.

## Jenkins Automation

The system runs automatically via Jenkins every Wednesday at 9:00 AM. See [JENKINS_SETUP.md](JENKINS_SETUP.md) for setup instructions.

## Main Components

### 1. Unified Weekly Report (`unified_weekly_report.py`)
Comprehensive weekly status report combining all metrics:
- **Bug Status**: Bugs on Dev, QA, and Closed with trend analysis
- **Automation Test Results**: Pass/Fail metrics from PostgreSQL
- **Critical Failures**: Tests failing on all platforms
- **Sub Test Executions**: Status from Jira with Xray integration
- **Rally Test Method Distribution**: Automated vs Manual test breakdown

**Usage:**
```powershell
python unified_weekly_report.py
# Enter version: 10.13.0.0
```

**Output:**
- HTML report: `unified_weekly_report_10_13_0_0.html`

### 2. Release Readiness Report (`generate_release_readiness.py`)
Comprehensive test coverage analysis with platform-specific metrics:
- **Overall Coverage Summary**: Total available tests, tests executed, coverage %, pass ratio
- **Platform Coverage by Run Mode**: Detailed breakdown by platform and mode (Transparent/Routing)
- **Platform Type Coverage**: Aggregated by platform type (Software, FPGA, EZchip)
- **Build Coverage**: Per-build execution statistics
- **Bug Trend Analysis**: Open bugs tracking from Jira
- **Sub Test Executions**: Manual test execution status from Jira

**Usage:**
```powershell
python generate_release_readiness.py
# Enter version: 10.12.0.0
# Enter builds: 83-106 (or specific: 95,96,97,98)
```

**Output:**
- HTML report with interactive charts
- CSV files for detailed analysis
- Platform-specific available test calculations

### 2. Gate Analysis Report (`generate_gate_analysis.py`)
Evaluates release against 5 defined gates with READY/PENDING status:
- **Gate 1**: Platform Type Coverage >90% per Run Mode (FPGA, EZchip, Software)
- **Gate 2**: Each Platform >50% Coverage (UHT, ESXI, KVM, VL3, etc.)
- **Gate 3**: No Open Bugs (0 bugs in Dev or QA status)
- **Gate 4**: All Sub Test Executions Accepted (with 5% completion threshold)
- **Gate 5**: Overall Coverage and Pass Ratio >90% (both metrics must exceed 90%)

**Usage:**
```powershell
python generate_gate_analysis.py
# Enter version: 10.12.0.0
# Enter builds: 83-106
```

**Output:**
- HTML report with gate status cards
- Action items with time estimates for pending gates
- Test execution rate analysis (~77.5 tests/hour)

### 3. CI Iteration Status Report (`ci_iteration_status.py`)
Report for automation test results introduced during the current sprint:
- **New Tests**: Tests introduced in current sprint
- **Test Execution Results**: Pass/fail metrics
- **Coverage by Platform**: Platform and mode breakdown
- **Build-level Analysis**: Test status per build

**Usage:**
```powershell
python ci_iteration_status.py
# Enter version: 10.13.0.0
```

### 4. Additional Scripts
- `weekly_work_summary.py`: Weekly work summary report
- `weekly_high_severity_bug_trend.py`: High severity bug tracking
- `list_open_bugs.py`: List open bugs utility
- `send_bug_notification.py`: Bug notification via email
- `send_via_outlook.py`: Outlook email sender utility

## Setup

### Prerequisites
- Python 3.13+
- Access to PostgreSQL database (10.185.20.124)
- Jira Cloud API access

### Installation

1. **Create virtual environment:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

3. **Configure credentials:**
   - Copy `.env.example` to `.env`
   - Update with your credentials:
     ```
     JIRA_URL=https://rwrnd.atlassian.net
     JIRA_EMAIL=your.email@example.com
     JIRA_API_TOKEN=your_api_token
     ```

## Database Schema

### PostgreSQL (10.185.20.124/results)
- **test_execution**: Test run records with status, timestamps, versions, builds
- **device**: Platform information (UHT, ESXI, KVM, VL3, MRQ_X, etc.)
- **profile**: Test profiles defining Transparent/Routing modes
- **test**: Test metadata including class information

### Platform-Specific Baselines
Each platform has its own available test set calculated from tests executed on the current or previous release:
- **UHT**: 7,415 tests
- **VL3**: 7,339 tests
- **MRQ_X**: 7,304 tests
- **ESXI**: 7,270 tests
- **MRQP**: 7,217 tests
- **KVM**: 7,165 tests
- **HT2**: 7,062 tests
- **MR2**: 7,021 tests

**Excluded Platforms**: MRQ, MR, VL2 (not applicable to 10.x.x.x versions)

## Key Features

### Platform-Specific Analysis
- Available tests calculated per platform (tests on 10.12.0.0 OR 10.11.0.0)
- Separate coverage metrics for Transparent vs Routing modes
- Platform type aggregation (Software, FPGA, EZchip)

### Baseline Methodology
- **Adjusted Baseline**: 7,872 tests (8,647 total minus 775 consistently skipped)
- **Platform-Specific**: Each platform has unique available test set
- **Mode-Specific**: Separate baselines for Transparent and Routing modes

### Test Execution Rate
- Calculated from last 5 builds
- Average: 77.5 tests/hour
- Average build duration: 68 hours
- Used to estimate time for coverage gaps

### Jira Integration
- Bug tracking by fixVersion and status
- Sub test execution monitoring
- Automated JQL queries for bug trends

## Project Structure

```
Jira/
├── unified_weekly_report.py       # Main weekly status report (runs from Jenkins)
├── generate_release_readiness.py  # Main release readiness report
├── generate_gate_analysis.py      # Gate evaluation report
├── run_gate_analysis.py           # Gate analysis runner
├── ci_iteration_status.py         # CI iteration status report
├── jira_helper.py                 # Jira API helper class
├── weekly_work_summary.py         # Weekly work summary
├── weekly_high_severity_bug_trend.py  # High severity bug tracking
├── list_open_bugs.py              # List open bugs utility
├── send_bug_notification.py       # Bug notification via email
├── send_via_outlook.py            # Outlook email sender
├── requirements.txt               # Python dependencies
├── Jenkinsfile                    # Jenkins pipeline definition
├── JENKINS_SETUP.md               # Jenkins setup instructions
├── .env                          # Credentials (not committed)
├── .env.example                  # Example credentials file
├── .gitignore                    # Git ignore rules
├── push-to-github.ps1            # Git push automation script
└── README.md                     # This file
```

## Output Files

### Latest Reports
- `Release_10_12_0_0_Builds_83-106_Report.html` - Release readiness report
- `Release_10_12_0_0_Builds_83-106_Gate_Analysis.html` - Gate analysis report

### CSV Exports
- `*_overall.csv` - Overall coverage summary
- `*_platform_mode.csv` - Platform + mode combinations
- `*_platform_summary.csv` - Platform aggregates
- `*_platform_type_mode.csv` - Platform type + mode
- `*_platform_type_summary.csv` - Platform type aggregates
- `*_build.csv` - Build-level coverage
- `*_bug_trend.csv` - Bug tracking data
- `*_sub_test_executions.csv` - Manual test status
- `Release_10_12_0_0_New_Tests.csv` - Tests not in previous release

## Troubleshooting

### Common Issues
1. **Database Connection**: Verify PostgreSQL server accessibility (10.185.20.124:5432)
2. **Jira Authentication**: Regenerate API token if expired
3. **pandas Warnings**: SQLAlchemy warnings are informational, not errors
4. **HTTPS Warnings**: Certificate verification warnings are expected for internal Jira

### Debug Output
Both scripts provide detailed console output:
- Connection status
- Query execution progress
- Data validation messages
- Gate evaluation results

## Resources

- [Jira Python SDK Documentation](https://jira.readthedocs.io/)
- [PostgreSQL psycopg2 Documentation](https://www.psycopg.org/docs/)
- [pandas Documentation](https://pandas.pydata.org/docs/)
- [Chart.js Documentation](https://www.chartjs.org/docs/)
