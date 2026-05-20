import csv
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests
import urllib3
from dotenv import load_dotenv
from jira import JIRA


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

VERSION = os.getenv("MAP_VERSION", "10.14.0.0")
PROJECT = os.getenv("JIRA_PROJECT", "DP")
METHOD_FIELD = "customfield_10154"
XRAY_AUTH_URL = "https://xray.cloud.getxray.app/api/v2/authenticate"
XRAY_GRAPHQL_URL = "https://xray.cloud.getxray.app/api/v2/graphql"
XRAY_CLIENT_ID = os.getenv("XRAY_CLIENT_ID", "7DC37640C3B6422D91E978570801CCF8")
XRAY_CLIENT_SECRET = os.getenv("XRAY_CLIENT_SECRET", "757b92c3039c706606ee29fe74e7c9d28c0a9c80bc013f6999f5910f20d347d8")


def connect_to_jira():
    options = {
        "server": os.getenv("JIRA_URL"),
        "verify": os.getenv("JIRA_VERIFY_SSL", "true").lower() in ("1", "true", "yes"),
    }
    return JIRA(options=options, basic_auth=(os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN")))


def get_xray_token():
    response = requests.post(
        XRAY_AUTH_URL,
        json={"client_id": XRAY_CLIENT_ID, "client_secret": XRAY_CLIENT_SECRET},
        headers={"Content-Type": "application/json"},
        verify=False,
        timeout=30,
    )
    response.raise_for_status()
    return response.text.strip('"')


def xray_graphql(query, variables):
    token = get_xray_token()
    response = requests.post(
        XRAY_GRAPHQL_URL,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        verify=False,
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def fetch_sub_test_executions(jira):
    jql = f'project = {PROJECT} AND type = "sub test execution" AND fixVersion = "{VERSION}"'
    return jira.search_issues(jql, maxResults=False, fields="summary,status")


def fetch_xray_execution_ids(jira_keys):
    query = """
    query($limit: Int!, $start: Int!) {
      getTestExecutions(limit: $limit, start: $start) {
        total
        results {
          issueId
          jira(fields: ["key"])
        }
      }
    }
    """
    target_keys = set(jira_keys)
    mapping = {}
    start = 0
    limit = 100

    while len(mapping) < len(target_keys):
        data = xray_graphql(query, {"limit": limit, "start": start})
        page = data["getTestExecutions"]
        for execution in page.get("results", []):
            key = execution.get("jira", {}).get("key")
            if key in target_keys:
                mapping[key] = execution.get("issueId")

        start += limit
        if start >= page.get("total", 0) or not page.get("results"):
            break
        time.sleep(0.2)

    return mapping


def fetch_test_runs_for_execution(issue_id):
    query = """
    query($issueId: String!, $limit: Int!, $start: Int!) {
      getTestExecution(issueId: $issueId) {
        testRuns(limit: $limit, start: $start) {
          total
          results {
            status { name }
            test {
              issueId
              jira(fields: ["key"])
            }
          }
        }
      }
    }
    """
    runs = []
    start = 0
    limit = 100

    while True:
        data = xray_graphql(query, {"issueId": issue_id, "limit": limit, "start": start})
        test_runs = data.get("getTestExecution", {}).get("testRuns", {})
        page_runs = test_runs.get("results", [])
        runs.extend(page_runs)
        start += limit
        if start >= test_runs.get("total", 0) or not page_runs:
            break
        time.sleep(0.2)

    return runs


def jira_chunks(values, size=100):
    values = sorted(values)
    for index in range(0, len(values), size):
        yield values[index:index + size]


def fetch_test_metadata(jira, test_keys):
    metadata = {}
    for chunk in jira_chunks(test_keys):
        quoted_keys = ", ".join(chunk)
        issues = jira.search_issues(
            f"key in ({quoted_keys})",
            maxResults=False,
            fields=f"summary,status,{METHOD_FIELD}",
        )
        for issue in issues:
            method = getattr(issue.fields, METHOD_FIELD, None)
            method_value = method.value if method and hasattr(method, "value") else "NA"
            metadata[issue.key] = {
                "summary": issue.fields.summary,
                "status": issue.fields.status.name,
                "method": method_value or "NA",
            }
    return metadata


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path, summary_rows, detail_rows, totals):
    lines = [
        f"# Test Cases With NA Method - {VERSION}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary",
        "",
        f"- Sub Test Executions: {totals['sub_executions']}",
        f"- Sub Test Executions mapped in Xray: {totals['mapped_executions']}",
        f"- Unique test cases in mapped executions: {totals['unique_tests']}",
        f"- Unique test cases with NA method: {totals['na_tests']}",
        f"- NA method test/execution associations: {totals['na_associations']}",
        "",
        "## Unique NA Test Cases",
        "",
        "| Test Key | Status | Referenced By | Test Run Statuses | Summary | Sub Test Executions |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['test_key']} | {row['test_status']} | {row['referenced_by_execution_count']} | "
            f"{row['test_run_statuses']} | {row['test_summary']} | {row['sub_test_executions']} |"
        )

    lines.extend([
        "",
        "## Execution Mapping",
        "",
        "| Sub Test Execution | Execution Status | Test Key | Test Status | Test Run Status | Summary |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for row in detail_rows:
        lines.append(
            f"| {row['sub_test_execution_key']} | {row['sub_test_execution_status']} | {row['test_key']} | "
            f"{row['test_status']} | {row['test_run_status']} | {row['test_summary']} |"
        )

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    output_dir = Path("sub_test_execution_na_method_map")
    output_dir.mkdir(exist_ok=True)
    csv_summary_path = output_dir / f"sub_test_execution_na_method_map_{VERSION.replace('.', '_')}.csv"
    csv_detail_path = output_dir / f"sub_test_execution_na_method_map_{VERSION.replace('.', '_')}_details.csv"
    md_path = output_dir / f"sub_test_execution_na_method_map_{VERSION.replace('.', '_')}.md"

    jira = connect_to_jira()
    sub_execs = fetch_sub_test_executions(jira)
    sub_exec_by_key = {
        issue.key: {
            "summary": issue.fields.summary,
            "status": issue.fields.status.name,
        }
        for issue in sub_execs
    }

    print(f"Found {len(sub_exec_by_key)} Sub Test Executions for {VERSION}")
    execution_ids = fetch_xray_execution_ids(sub_exec_by_key)
    print(f"Mapped {len(execution_ids)} Sub Test Executions to Xray")

    associations = []
    all_test_keys = set()
    for index, (execution_key, issue_id) in enumerate(sorted(execution_ids.items()), start=1):
        runs = fetch_test_runs_for_execution(issue_id)
        print(f"[{index}/{len(execution_ids)}] {execution_key}: {len(runs)} test runs")
        for run in runs:
            test_key = run.get("test", {}).get("jira", {}).get("key")
            if not test_key:
                continue
            all_test_keys.add(test_key)
            associations.append({
                "sub_test_execution_key": execution_key,
                "sub_test_execution_summary": sub_exec_by_key[execution_key]["summary"],
                "sub_test_execution_status": sub_exec_by_key[execution_key]["status"],
                "test_key": test_key,
                "test_run_status": run.get("status", {}).get("name", "Unknown"),
            })

    print(f"Found {len(all_test_keys)} unique test cases in mapped executions")
    test_metadata = fetch_test_metadata(jira, all_test_keys)

    detail_rows = []
    grouped = defaultdict(list)
    for association in associations:
        meta = test_metadata.get(association["test_key"], {"summary": "", "status": "", "method": "NA"})
        if meta["method"] != "NA":
            continue
        row = {
            **association,
            "test_summary": meta["summary"],
            "test_status": meta["status"],
            "method": meta["method"],
        }
        detail_rows.append(row)
        grouped[association["test_key"]].append(row)

    summary_rows = []
    for test_key, rows in sorted(grouped.items()):
        first = rows[0]
        executions = sorted({f"{row['sub_test_execution_key']} - {row['sub_test_execution_summary']}" for row in rows})
        run_statuses = sorted({row["test_run_status"] for row in rows})
        summary_rows.append({
            "test_key": test_key,
            "test_summary": first["test_summary"],
            "test_status": first["test_status"],
            "method": "NA",
            "referenced_by_execution_count": len(executions),
            "test_run_statuses": "; ".join(run_statuses),
            "sub_test_executions": "; ".join(executions),
        })

    summary_fields = [
        "test_key",
        "test_summary",
        "test_status",
        "method",
        "referenced_by_execution_count",
        "test_run_statuses",
        "sub_test_executions",
    ]
    detail_fields = [
        "sub_test_execution_key",
        "sub_test_execution_summary",
        "sub_test_execution_status",
        "test_key",
        "test_summary",
        "test_status",
        "method",
        "test_run_status",
    ]

    write_csv(csv_summary_path, summary_rows, summary_fields)
    write_csv(csv_detail_path, sorted(detail_rows, key=lambda row: (row["sub_test_execution_key"], row["test_key"])), detail_fields)
    write_markdown(md_path, summary_rows, sorted(detail_rows, key=lambda row: (row["sub_test_execution_key"], row["test_key"])), {
        "sub_executions": len(sub_exec_by_key),
        "mapped_executions": len(execution_ids),
        "unique_tests": len(all_test_keys),
        "na_tests": len(summary_rows),
        "na_associations": len(detail_rows),
    })

    print(f"NA method unique test cases: {len(summary_rows)}")
    print(f"NA method test/execution associations: {len(detail_rows)}")
    print(f"Wrote {csv_summary_path}")
    print(f"Wrote {csv_detail_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()