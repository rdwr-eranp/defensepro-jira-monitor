"""
One-time script: Change test case method from Automated to Manual
for a specific list of test case IDs.

Field: customfield_10154 (Rally Test Method) - select field
Target value: "Manual"

Usage: python one_time_set_manual.py [--dry-run]
"""

import sys
import os
from jira import JIRA
from dotenv import load_dotenv

load_dotenv()

DRY_RUN = '--dry-run' in sys.argv
LOG_FILE = 'one_time_set_manual_log.txt'

def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')

# Test case IDs (commas removed, prefixed with DP-)
RAW_IDS = """
121,875 121,876 121,877 121,879 121,881 121,882 121,893 121,905 121,906 121,907
121,908 121,909 121,910 121,915 121,917 121,929 121,932 121,950 121,953 121,969
121,979 122,025 122,026 122,027 122,152 122,154 122,155 122,294 122,295 122,327
122,352 122,353 122,355 122,361 122,371 122,375 122,376 122,377 122,378 122,379
122,402 122,403 122,404 122,405 122,427 122,437 122,439 122,440 122,441 122,453
122,454 122,455 122,456 122,458 122,464 122,513 122,525 122,526 122,548 122,551
122,554 122,556 122,557 122,572 122,573 122,574 122,582 122,583 122,585 122,587
122,602 122,935 122,939 122,966 122,968 122,976 122,982 122,983 122,996 122,997
123,215 123,216 123,263 123,394 123,400 123,411 123,415 123,416 123,417 123,418
123,419 123,420 123,421 123,431 123,432 123,433 123,434 123,436 123,437 123,469
123,470 123,471 123,472 123,475 123,480 123,482 123,489 123,490 123,504 123,505
123,507 123,508 123,509 123,510 123,512 123,513 123,514 123,515 123,517 123,518
123,519 123,523 123,530 123,531 123,532 123,533 123,535 123,536 123,537 123,557
123,558 123,559 123,560 123,561 123,562 123,563 123,608
""".strip()

# Parse: remove commas from numbers, prefix with DP-
test_keys = []
for token in RAW_IDS.split():
    num = token.replace(',', '')
    test_keys.append(f"DP-{num}")

print(f"{'DRY RUN - ' if DRY_RUN else ''}Changing {len(test_keys)} test cases from Automated → Manual")
log(f"Field: customfield_10154 (Rally Test Method)\n")

# Connect to Jira
jira = JIRA(
    options={'server': os.getenv('JIRA_URL'), 'verify': True},
    basic_auth=(os.getenv('JIRA_EMAIL'), os.getenv('JIRA_API_TOKEN'))
)
log("✓ Connected to Jira\n")

updated = 0
skipped = 0
errors = 0
already_manual = 0

for i, key in enumerate(test_keys, 1):
    try:
        issue = jira.issue(key, fields='customfield_10154,summary')
        method = getattr(issue.fields, 'customfield_10154', None)
        current = method.value if method and hasattr(method, 'value') else 'N/A'

        if current == 'Manual':
            log(f"  [{i}/{len(test_keys)}] {key}: already Manual — skipping")
            already_manual += 1
            continue

        if DRY_RUN:
            log(f"  [{i}/{len(test_keys)}] {key}: {current} → Manual (dry run)")
            updated += 1
        else:
            issue.update(fields={'customfield_10154': {'value': 'Manual'}})
            log(f"  [{i}/{len(test_keys)}] {key}: {current} → Manual ✓")
            updated += 1

    except Exception as e:
        err_msg = str(e)[:80]
        log(f"  [{i}/{len(test_keys)}] {key}: ERROR — {err_msg}")
        errors += 1

log(f"\n{'='*50}")
log(f"{'DRY RUN ' if DRY_RUN else ''}SUMMARY:")
log(f"  Updated:       {updated}")
log(f"  Already Manual: {already_manual}")
log(f"  Errors:        {errors}")
log(f"  Total:         {len(test_keys)}")
