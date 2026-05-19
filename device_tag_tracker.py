"""
Device Tag Tracker

Captures the current device-to-tag mapping from PostgreSQL and compares it to
this job's previous snapshot. Intended for a dedicated Jenkins job.
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from html import escape

import psycopg2
from dotenv import load_dotenv

UNTAGGED = "<untagged>"
CSV_COLUMNS = ["id", "name", "ip", "host_ip", "console_ip", "platform", "tag", "remark"]
HISTORY_COLUMNS = [
    "run_timestamp",
    "jenkins_job",
    "jenkins_build",
    "jenkins_build_url",
    "change_type",
    "id",
    "name",
    "ip",
    "platform",
    "old_tag",
    "new_tag",
    "remark",
]


def clean_value(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_tag(value):
    tag = clean_value(value)
    return tag if tag else UNTAGGED


def markdown_cell(value):
    return clean_value(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def connect():
    load_dotenv()
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "10.185.20.124"),
        port=os.getenv("PG_PORT", "5432"),
        database=os.getenv("PG_DATABASE", "results"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
    )


def fetch_devices():
    sql = """
        SELECT id, name, ip, host_ip, console_ip, platform, tag, remark
        FROM public.device
        ORDER BY id
    """
    with connect() as conn:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()

    devices = []
    for row in rows:
        record = dict(zip(CSV_COLUMNS, row))
        normalized = {key: clean_value(value) for key, value in record.items()}
        normalized["id"] = clean_value(record["id"])
        normalized["tag"] = normalize_tag(record["tag"])
        devices.append(normalized)

    return sorted(devices, key=lambda item: (item["tag"], item["platform"], item["ip"], item["name"], item["id"]))


def read_snapshot(path):
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        devices = []
        for row in reader:
            record = {key: clean_value(row.get(key, "")) for key in CSV_COLUMNS}
            record["tag"] = normalize_tag(record.get("tag"))
            devices.append(record)
    return devices


def write_snapshot(path, devices):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(devices)


def compare_snapshots(previous, current):
    if previous is None:
        return {
            "baseline_created": True,
            "tag_changes": [],
            "added_devices": [],
            "removed_devices": [],
        }

    previous_by_id = {item["id"]: item for item in previous}
    current_by_id = {item["id"]: item for item in current}

    tag_changes = []
    for device_id in sorted(set(previous_by_id) & set(current_by_id), key=lambda value: int(value) if value.isdigit() else value):
        old = previous_by_id[device_id]
        new = current_by_id[device_id]
        if old["tag"] != new["tag"]:
            tag_changes.append({
                "id": device_id,
                "name": new["name"] or old["name"],
                "ip": new["ip"] or old["ip"],
                "platform": new["platform"] or old["platform"],
                "old_tag": old["tag"],
                "new_tag": new["tag"],
                "remark": new["remark"] or old["remark"],
            })

    added_devices = [current_by_id[device_id] for device_id in sorted(set(current_by_id) - set(previous_by_id), key=lambda value: int(value) if value.isdigit() else value)]
    removed_devices = [previous_by_id[device_id] for device_id in sorted(set(previous_by_id) - set(current_by_id), key=lambda value: int(value) if value.isdigit() else value)]

    return {
        "baseline_created": False,
        "tag_changes": tag_changes,
        "added_devices": added_devices,
        "removed_devices": removed_devices,
    }


def summarize(devices, comparison, generated_at):
    tag_counts = Counter(device["tag"] for device in devices)
    real_tags = {tag for tag in tag_counts if tag != UNTAGGED}
    changed_count = len(comparison["tag_changes"]) + len(comparison["added_devices"]) + len(comparison["removed_devices"])

    return {
        "generated_at": generated_at,
        "baseline_created": comparison["baseline_created"],
        "total_devices": len(devices),
        "tagged_devices": sum(1 for device in devices if device["tag"] != UNTAGGED),
        "untagged_devices": sum(1 for device in devices if device["tag"] == UNTAGGED),
        "distinct_tags": len(real_tags),
        "tag_counts": dict(sorted(tag_counts.items())),
        "tag_changed_count": len(comparison["tag_changes"]),
        "added_device_count": len(comparison["added_devices"]),
        "removed_device_count": len(comparison["removed_devices"]),
        "changed_count": changed_count,
    }


def write_changes_csv(path, comparison):
    columns = ["change_type", "id", "name", "ip", "platform", "old_tag", "new_tag", "remark"]
    rows = build_change_rows(comparison)

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def build_change_rows(comparison):
    rows = []
    for item in comparison["tag_changes"]:
        rows.append({"change_type": "tag_changed", **item})
    for item in comparison["added_devices"]:
        rows.append({
            "change_type": "device_added",
            "id": item["id"],
            "name": item["name"],
            "ip": item["ip"],
            "platform": item["platform"],
            "old_tag": "",
            "new_tag": item["tag"],
            "remark": item["remark"],
        })
    for item in comparison["removed_devices"]:
        rows.append({
            "change_type": "device_removed",
            "id": item["id"],
            "name": item["name"],
            "ip": item["ip"],
            "platform": item["platform"],
            "old_tag": item["tag"],
            "new_tag": "",
            "remark": item["remark"],
        })
    return rows


def append_change_history(path, comparison, generated_at):
    rows = build_change_rows(comparison)
    if not rows:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    run_context = {
        "run_timestamp": generated_at,
        "jenkins_job": os.getenv("JOB_NAME", ""),
        "jenkins_build": os.getenv("BUILD_NUMBER", ""),
        "jenkins_build_url": os.getenv("BUILD_URL", ""),
    }

    with path.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=HISTORY_COLUMNS)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({**run_context, **row})

    return len(rows)


def read_change_history(path):
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        return [{key: clean_value(row.get(key, "")) for key in HISTORY_COLUMNS} for row in reader]


def markdown_table(headers, rows):
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        output.append("| " + " | ".join(markdown_cell(value) for value in row) + " |")
    return "\n".join(output)


def write_markdown(path, devices, comparison, summary):
    lines = [
        "# Device Tag Change Report",
        "",
        f"Generated at: {summary['generated_at']}",
        "",
        f"- Total devices: {summary['total_devices']}",
        f"- Tagged devices: {summary['tagged_devices']}",
        f"- Untagged devices: {summary['untagged_devices']}",
        f"- Distinct real tags: {summary['distinct_tags']}",
        f"- Tag changes: {summary['tag_changed_count']}",
        f"- Added devices: {summary['added_device_count']}",
        f"- Removed devices: {summary['removed_device_count']}",
        "",
    ]

    if summary["baseline_created"]:
        lines.extend([
            "## Baseline Created",
            "",
            "No previous snapshot was found. This run saved the first baseline; future runs will report changes.",
            "",
        ])
    elif summary["changed_count"] == 0:
        lines.extend(["## Change Summary", "", "No device tag changes detected since the previous snapshot.", ""])
    else:
        lines.extend(["## Tag Changes", ""])
        if comparison["tag_changes"]:
            rows = [[item["id"], item["name"], item["ip"], item["platform"], item["old_tag"], item["new_tag"], item["remark"]] for item in comparison["tag_changes"]]
            lines.append(markdown_table(["ID", "Name", "IP", "Platform", "Old Tag", "New Tag", "Remark"], rows))
        else:
            lines.append("No existing devices changed tag.")
        lines.append("")

        lines.extend(["## Added Devices", ""])
        if comparison["added_devices"]:
            rows = [[item["id"], item["name"], item["ip"], item["platform"], item["tag"], item["remark"]] for item in comparison["added_devices"]]
            lines.append(markdown_table(["ID", "Name", "IP", "Platform", "Tag", "Remark"], rows))
        else:
            lines.append("No devices were added.")
        lines.append("")

        lines.extend(["## Removed Devices", ""])
        if comparison["removed_devices"]:
            rows = [[item["id"], item["name"], item["ip"], item["platform"], item["tag"], item["remark"]] for item in comparison["removed_devices"]]
            lines.append(markdown_table(["ID", "Name", "IP", "Platform", "Tag", "Remark"], rows))
        else:
            lines.append("No devices were removed.")
        lines.append("")

    lines.extend(["## Tag Summary", ""])
    tag_rows = [[tag, count] for tag, count in summary["tag_counts"].items()]
    lines.append(markdown_table(["Tag", "Count"], tag_rows))
    lines.append("")

    lines.extend(["## Current Device Map", ""])
    device_rows = [[device[column] for column in CSV_COLUMNS] for device in devices]
    lines.append(markdown_table(["ID", "Name", "IP", "Host IP", "Console IP", "Platform", "Tag", "Remark"], device_rows))
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def html_table(headers, rows):
    header_html = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    row_html = []
    for row in rows:
        cells = "".join(f"<td>{escape(clean_value(value))}</td>" for value in row)
        row_html.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(row_html)}</tbody></table>"


def write_html(path, devices, comparison, summary):
    if summary["baseline_created"]:
        change_section = "<h2>Baseline Created</h2><p>No previous snapshot was found. Future runs will report changes.</p>"
    elif summary["changed_count"] == 0:
        change_section = "<h2>Change Summary</h2><p>No device tag changes detected since the previous snapshot.</p>"
    else:
        changed_rows = [[item["id"], item["name"], item["ip"], item["platform"], item["old_tag"], item["new_tag"], item["remark"]] for item in comparison["tag_changes"]]
        added_rows = [[item["id"], item["name"], item["ip"], item["platform"], item["tag"], item["remark"]] for item in comparison["added_devices"]]
        removed_rows = [[item["id"], item["name"], item["ip"], item["platform"], item["tag"], item["remark"]] for item in comparison["removed_devices"]]
        change_section = "".join([
            "<h2>Tag Changes</h2>",
            html_table(["ID", "Name", "IP", "Platform", "Old Tag", "New Tag", "Remark"], changed_rows) if changed_rows else "<p>No existing devices changed tag.</p>",
            "<h2>Added Devices</h2>",
            html_table(["ID", "Name", "IP", "Platform", "Tag", "Remark"], added_rows) if added_rows else "<p>No devices were added.</p>",
            "<h2>Removed Devices</h2>",
            html_table(["ID", "Name", "IP", "Platform", "Tag", "Remark"], removed_rows) if removed_rows else "<p>No devices were removed.</p>",
        ])

    tag_rows = [[tag, count] for tag, count in summary["tag_counts"].items()]
    device_rows = [[device[column] for column in CSV_COLUMNS] for device in devices]
    status_class = "changed" if summary["changed_count"] else "clean"
    status_text = "Changes detected" if summary["changed_count"] else "No changes detected"
    if summary["baseline_created"]:
        status_text = "Baseline created"
        status_class = "baseline"

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Device Tag Change Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #222; }}
    h1, h2 {{ color: #1f4e79; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; font-size: 13px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f2f5f8; }}
    .summary {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0; }}
    .card {{ border: 1px solid #ddd; border-radius: 6px; padding: 12px 16px; min-width: 140px; background: #fafafa; }}
    .value {{ font-size: 24px; font-weight: bold; }}
    .changed {{ color: #b42318; }}
    .clean {{ color: #067647; }}
    .baseline {{ color: #175cd3; }}
  </style>
</head>
<body>
  <h1>Device Tag Change Report</h1>
  <p>Generated at: {escape(summary['generated_at'])}</p>
  <h2 class=\"{status_class}\">{escape(status_text)}</h2>
  <div class=\"summary\">
    <div class=\"card\"><div>Total Devices</div><div class=\"value\">{summary['total_devices']}</div></div>
    <div class=\"card\"><div>Tagged</div><div class=\"value\">{summary['tagged_devices']}</div></div>
    <div class=\"card\"><div>Untagged</div><div class=\"value\">{summary['untagged_devices']}</div></div>
    <div class=\"card\"><div>Tag Changes</div><div class=\"value\">{summary['tag_changed_count']}</div></div>
    <div class=\"card\"><div>Added</div><div class=\"value\">{summary['added_device_count']}</div></div>
    <div class=\"card\"><div>Removed</div><div class=\"value\">{summary['removed_device_count']}</div></div>
  </div>
  {change_section}
  <h2>Tag Summary</h2>
  {html_table(["Tag", "Count"], tag_rows)}
  <h2>Current Device Map</h2>
  {html_table(["ID", "Name", "IP", "Host IP", "Console IP", "Platform", "Tag", "Remark"], device_rows)}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_history_html(path, history_rows, summary):
        change_counts = Counter(row["change_type"] for row in history_rows)
        tag_change_count = change_counts.get("tag_changed", 0)
        added_count = change_counts.get("device_added", 0)
        removed_count = change_counts.get("device_removed", 0)
        latest_rows = list(reversed(history_rows))[:200]

        if history_rows:
                history_table_rows = [
                        [
                                row["run_timestamp"],
                                row["jenkins_build"],
                                row["change_type"],
                                row["id"],
                                row["name"],
                                row["ip"],
                                row["platform"],
                                row["old_tag"],
                                row["new_tag"],
                                row["remark"],
                                row["jenkins_build_url"],
                        ]
                        for row in latest_rows
                ]
                history_section = html_table(
                        ["Timestamp", "Build", "Change", "ID", "Name", "IP", "Platform", "Old Tag", "New Tag", "Remark", "Build URL"],
                        history_table_rows,
                )
        else:
                history_section = "<p>No tag changes have been recorded yet. The first successful run creates the baseline; history appears after a later run detects a change.</p>"

        html = f"""<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\">
    <title>Device Tag Tracking History</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 24px; color: #222; }}
        h1, h2 {{ color: #1f4e79; }}
        table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; font-size: 13px; }}
        th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }}
        th {{ background: #f2f5f8; }}
        .summary {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0; }}
        .card {{ border: 1px solid #ddd; border-radius: 6px; padding: 12px 16px; min-width: 150px; background: #fafafa; }}
        .value {{ font-size: 24px; font-weight: bold; }}
        .note {{ color: #555; }}
    </style>
</head>
<body>
    <h1>Device Tag Tracking History</h1>
    <p>Generated at: {escape(summary['generated_at'])}</p>
    <div class=\"summary\">
        <div class=\"card\"><div>Total History Rows</div><div class=\"value\">{len(history_rows)}</div></div>
        <div class=\"card\"><div>Tag Changes</div><div class=\"value\">{tag_change_count}</div></div>
        <div class=\"card\"><div>Added Devices</div><div class=\"value\">{added_count}</div></div>
        <div class=\"card\"><div>Removed Devices</div><div class=\"value\">{removed_count}</div></div>
    </div>
    <p class=\"note\">Showing the latest {len(latest_rows)} history rows. The complete trace is archived as <code>device_tag_change_history.csv</code>.</p>
    <h2>Recent Tracking Events</h2>
    {history_section}
</body>
</html>
"""
        path.write_text(html, encoding="utf-8")


def write_summary_properties(path, summary):
    keys = [
        "changed_count",
        "tag_changed_count",
        "added_device_count",
        "removed_device_count",
        "baseline_created",
        "total_devices",
        "tagged_devices",
        "untagged_devices",
    ]
    lines = [f"{key}={summary[key]}" for key in keys]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Track changes in public.device.tag values")
    parser.add_argument("--state-dir", default=os.getenv("DEVICE_TAG_STATE_DIR", "device_tag_tracking_state"))
    parser.add_argument("--output-dir", default=os.getenv("DEVICE_TAG_OUTPUT_DIR", "device_tag_tracking"))
    parser.add_argument("--fail-on-change", action="store_true", default=os.getenv("DEVICE_TAG_FAIL_ON_CHANGE", "").lower() in {"1", "true", "yes"})
    args = parser.parse_args()

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    state_dir = Path(args.state_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    latest_snapshot_path = state_dir / "latest_device_tags.csv"
    history_path = state_dir / "device_tag_change_history.csv"
    persistent_history_html_path = state_dir / "device_tag_change_history.html"
    previous_devices = read_snapshot(latest_snapshot_path)
    current_devices = fetch_devices()
    comparison = compare_snapshots(previous_devices, current_devices)
    summary = summarize(current_devices, comparison, generated_at)

    current_snapshot_path = output_dir / "device_tags_current.csv"
    dated_snapshot_path = output_dir / f"device_tags_snapshot_{timestamp}.csv"
    changes_csv_path = output_dir / "device_tag_changes.csv"
    markdown_path = output_dir / "device_tag_report.md"
    html_path = output_dir / "device_tag_report.html"
    history_html_path = output_dir / "device_tag_tracking_history.html"
    summary_path = output_dir / "device_tag_summary.json"
    summary_properties_path = output_dir / "device_tag_summary.properties"

    write_snapshot(current_snapshot_path, current_devices)
    write_snapshot(dated_snapshot_path, current_devices)
    write_changes_csv(changes_csv_path, comparison)
    write_markdown(markdown_path, current_devices, comparison, summary)
    write_html(html_path, current_devices, comparison, summary)
    history_rows_added = append_change_history(history_path, comparison, generated_at)
    history_rows = read_change_history(history_path)
    write_history_html(history_html_path, history_rows, summary)
    write_history_html(persistent_history_html_path, history_rows, summary)

    summary.update({
        "current_snapshot": str(current_snapshot_path),
        "dated_snapshot": str(dated_snapshot_path),
        "changes_csv": str(changes_csv_path),
        "markdown_report": str(markdown_path),
        "html_report": str(html_path),
        "history_html_report": str(history_html_path),
        "persistent_history_html_report": str(persistent_history_html_path),
        "state_snapshot": str(latest_snapshot_path),
        "history_csv": str(history_path),
        "history_rows_added": history_rows_added,
    })
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_summary_properties(summary_properties_path, summary)

    write_snapshot(latest_snapshot_path, current_devices)

    print(f"Generated {html_path}")
    print(f"Generated {history_html_path}")
    print(f"Updated {persistent_history_html_path}")
    print(f"Generated {markdown_path}")
    print(f"Generated {changes_csv_path}")
    print(f"Total devices: {summary['total_devices']}")
    print(f"Tag changes: {summary['tag_changed_count']}")
    print(f"Added devices: {summary['added_device_count']}")
    print(f"Removed devices: {summary['removed_device_count']}")
    print(f"History rows added: {history_rows_added}")

    if args.fail_on_change and summary["changed_count"] > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
