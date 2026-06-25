# Release Readiness Report: 10.14.0.0

Date: 2026-06-22
Scope: DP project, version 10.14.0.0
Data sources: Jira + PostgreSQL via generate_release_readiness.py
Build set analyzed: 95, 96, 97, 98, 101, 102, 103, 104, 106

## Executive Recommendation

**CONDITIONAL GO**

Rationale:
- Bug risk is low on active development statuses (0 open/in-progress bugs), with 1 High-priority bug in Completed/QA.
- Automated regression quality is strong overall (94.15% coverage of available baseline tests, 97.16% pass ratio).
- Main gating concern is sub test execution completion: 79.2% complete (10 of 48 still not completed).

## 1) Jira Health (Open Bug Analysis)

- Active Dev/Open/Reopened bugs: **0**
- Bugs in QA (Completed): **1**
- Total unresolved by broad status filter (includes Trash): **4**

Open QA bug:
- DP-112430 (High): Cloud Assist AX traffic drop issue, status Completed

Interpretation:
- No active engineering queue for this release version.
- One high-priority item remains in QA verification and should be dispositioned before final release sign-off.

## 2) Sub Test Execution Status

- Total sub test execution issues: **48**
- Completed: **38** (79.2%)
- In Progress: **5**
- Not Started: **5**

Pending examples (from latest snapshot):
- In Progress: DP-113606, DP-113602, DP-113601, DP-113544, DP-113479
- Not Started: DP-113605, DP-113604, DP-113603, DP-113600, DP-113599

Interpretation:
- Execution coverage from task workflow perspective is not yet fully complete.
- ATP-related items are a clear residual risk area.

## 3) Automation Test Coverage

Overall (regression, last execution logic):
- Available baseline tests: **7,898**
- Executed tests: **7,436**
- Coverage: **94.15%**

By platform type:
- FPGA: 85.49%
- Software: 82.84%
- EZchip: 60.62%

Interpretation:
- Overall coverage is high.
- EZchip coverage is notably lower than FPGA/Software and should be accepted explicitly as release risk or closed with additional runs.

## 4) Quality Metrics (Pass Ratio)

Overall pass ratio:
- **97.16%** (7,225 passed, 1,493 failed executions counted under the script's aggregation model)

Selected breakdown:
- FPGA overall pass ratio: 92.40%
- Software overall pass ratio: 94.82%
- EZchip overall pass ratio: 92.59%

Build-level signal:
- Build 102 has the largest execution volume (5,432 tests) with 87.65% pass ratio.
- Other builds have much smaller sample sizes and higher pass ratios.

Interpretation:
- Aggregate quality is strong.
- High-volume Build 102 pass rate indicates concentrated failures that merit a targeted review before final GA decision.

## Final Decision Matrix

- Jira bug backlog risk: **Green/Amber** (no active dev bugs, 1 High in QA)
- Sub-test execution completeness: **Amber** (79.2%)
- Coverage: **Green** (94.15%)
- Pass ratio: **Green/Amber** (97.16% overall, but heavy-failure concentration in Build 102)

## Recommendation

**CONDITIONAL GO** with these release gates:
1. Close or explicitly waive the remaining High-priority QA bug (DP-112430).
2. Complete or waive the 10 pending sub test execution issues (especially ATP stream).
3. Triage Build 102 failure concentration and confirm no critical/clustered regressions remain.

If all three conditions are satisfied, promote to **GO**.

## Generated Artifacts

- Release_10_14_0_0_Builds_95_96_97_98_101_102_103_104_106_Report.html
- Release_10_14_0_0_Builds_95_96_97_98_101_102_103_104_106_overall.csv
- Release_10_14_0_0_Builds_95_96_97_98_101_102_103_104_106_platform_type_summary.csv
- Release_10_14_0_0_Builds_95_96_97_98_101_102_103_104_106_build.csv
- Release_10_14_0_0_Builds_95_96_97_98_101_102_103_104_106_sub_test_executions.csv
