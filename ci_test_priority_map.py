"""
CI Test Priority Mapping

Builds a scored map of CI regression tests using a risk-weighted priority model
that accounts for platform type and operation mode.

Priority formula (normalized 0..1 inputs):
    score = 100 * (
        3 * change_impact
            + 3 * historical_failure
      + 2 * platform_mode_risk
            + 1 * hw_accel_relevance
      + 1 * business_criticality
      - 1 * runtime_cost
        ) / 9

historical_failure is blended from:
- failure rate over selected history range
- recent 14-day failure rate
- failure volume signal over selected history range (so tests that failed more
    often in older releases get additional uplift)

Usage examples:
    python ci_test_priority_map.py --version 10.14.0.0 --ci-start 2026-05-20
    python ci_test_priority_map.py --version 10.14.0.0 --sprint-start 2026-05-20 --sprint-end 2026-06-03
    python ci_test_priority_map.py --version 10.14.0.0 --ci-start 2026-05-20 --history-from-version 10.12.0.0

Optional CSV overrides:
- --change-impact-file: test_id,value OR test_name,value (0..1)
- --business-criticality-file: test_id,value OR test_name,value (0..1)
- --platform-risk-file: platform_type,mode,value (0..1)

New-test policy:
- New tests are promoted to P1 by default until they stabilize.
- Stabilization default: at least 3 executions in current window and 0 failures.

Optional defer policy:
- Recommended deferred tests can be labeled as P4 (deferred bucket) using
    --defer-to-p4 balanced (or strict/aggressive).

Output:
- CSV with one row per (test_id, platform_type, mode)
- Ranked by score descending
"""

import argparse
import math
import os
from datetime import datetime

import pandas as pd
import psycopg2
from dotenv import load_dotenv


load_dotenv()


KNOWN_PLATFORMS = ("UHT", "MRQP", "MR2", "ESXI", "KVM", "VL3", "HT2", "MRQ_X", "MRQX")

DEFAULT_PLATFORM_MODE_RISK = {
    ("FPGA", "Routing"): 0.90,
    ("Software", "Routing"): 0.85,
    ("EZchip", "Routing"): 0.80,
    ("FPGA", "Transparent"): 0.70,
    ("Software", "Transparent"): 0.65,
    ("EZchip", "Transparent"): 0.60,
}

HW_ACCEL_FEATURE_RULES = {
    "BDoS": ["bdos", "behavioral dos", "behavioral doS"],
    "SYN Protection": ["syn protection", "syn cookies", "tcp syn"],
    "Allow/Block List": ["allow list", "allow-list", "block list", "block-list", "whitelist", "blacklist"],
    "AppSec": ["appsec", "application security", "web attack", "waf"],
    "Traffic Filters": ["traffic filter", "traffic filters", "filtering", "acl"],
}


def parse_args():
    parser = argparse.ArgumentParser(description="Map and score CI tests for optimized regression execution")
    parser.add_argument("--version", required=True, help="Version to analyze, e.g. 10.14.0.0")

    period = parser.add_mutually_exclusive_group(required=True)
    period.add_argument("--ci-start", help="CI start date (YYYY-MM-DD). End defaults to now.")
    period.add_argument("--sprint-start", help="Sprint start date (YYYY-MM-DD). Use with --sprint-end")

    parser.add_argument("--sprint-end", help="Sprint end date (YYYY-MM-DD), required when using --sprint-start")
    parser.add_argument("--end", help="Optional end date (YYYY-MM-DD) when using --ci-start")
    parser.add_argument(
        "--history-from-version",
        default="10.12.0.0",
        help="Earliest release version to include in historical scoring signals (default: 10.12.0.0)",
    )

    parser.add_argument("--change-impact-file", help="CSV: test_id,value or test_name,value (0..1)")
    parser.add_argument("--business-criticality-file", help="CSV: test_id,value or test_name,value (0..1)")
    parser.add_argument("--platform-risk-file", help="CSV: platform_type,mode,value (0..1)")
    parser.add_argument(
        "--new-test-min-runs",
        type=int,
        default=3,
        help="Minimum executions in current window to consider a new test stable (default: 3)",
    )
    parser.add_argument(
        "--disable-new-test-p1-policy",
        action="store_true",
        help="Disable automatic P1 promotion for unstable new tests",
    )
    parser.add_argument(
        "--defer-to-p4",
        choices=["none", "strict", "balanced", "aggressive"],
        default="none",
        help="Apply defer policy and relabel matching tests to P4-Deferred (default: none)",
    )

    parser.add_argument(
        "--output",
        help="Output CSV path",
    )
    return parser.parse_args()


def connect():
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "10.185.20.124"),
        port=os.getenv("PG_PORT", "5432"),
        database=os.getenv("PG_DATABASE", "results"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
    )


def parse_version_tuple(version):
    parts = [int(p) for p in str(version).split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def version_range_condition(alias, min_version, max_version):
    min_v = parse_version_tuple(min_version)
    max_v = parse_version_tuple(max_version)
    return f"""
        (
            {alias}.version ~ '^[0-9]+(\\.[0-9]+){{3}}$'
            AND
            (
                COALESCE(NULLIF(split_part({alias}.version, '.', 1), ''), '0')::int,
                COALESCE(NULLIF(split_part({alias}.version, '.', 2), ''), '0')::int,
                COALESCE(NULLIF(split_part({alias}.version, '.', 3), ''), '0')::int,
                COALESCE(NULLIF(split_part({alias}.version, '.', 4), ''), '0')::int
            ) BETWEEN ({min_v[0]}, {min_v[1]}, {min_v[2]}, {min_v[3]})
              AND ({max_v[0]}, {max_v[1]}, {max_v[2]}, {max_v[3]})
        )
    """


def clamp01(value):
    if value is None or pd.isna(value):
        return 0.0
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, x))


def detect_hw_features(test_name):
    name = str(test_name or "").lower()
    matched = []
    for feature, keywords in HW_ACCEL_FEATURE_RULES.items():
        if any(keyword in name for keyword in keywords):
            matched.append(feature)
    return matched


def compute_hw_accel_relevance(platform_type, test_name):
    # HW-accelerated security features are more platform-sensitive on FPGA/EZchip.
    matched = detect_hw_features(test_name)
    if not matched:
        return 0.0, ""

    if platform_type in ("FPGA", "EZchip"):
        return 1.0, "; ".join(matched)
    return 0.25, "; ".join(matched)


def normalize_series(series):
    if series.empty:
        return series
    min_v = float(series.min())
    max_v = float(series.max())
    if max_v <= min_v:
        return pd.Series([0.0] * len(series), index=series.index)
    return (series - min_v) / (max_v - min_v)


def read_override_file(path, key_columns):
    if not path:
        return pd.DataFrame()

    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    value_col = cols.get("value")
    if not value_col:
        raise ValueError(f"Override file {path} must include 'value' column")

    actual_keys = []
    for key in key_columns:
        key_col = cols.get(key)
        if key_col:
            actual_keys.append(key_col)

    if not actual_keys:
        raise ValueError(f"Override file {path} must include one of: {', '.join(key_columns)}")

    keep_cols = actual_keys + [value_col]
    out = df[keep_cols].copy()
    out.rename(columns={value_col: "value"}, inplace=True)
    out["value"] = out["value"].apply(clamp01)
    return out


def load_platform_risk_overrides(path):
    if not path:
        return {}

    df = pd.read_csv(path)
    req = {"platform_type", "mode", "value"}
    cols = {c.lower().strip(): c for c in df.columns}
    if not req.issubset(cols.keys()):
        raise ValueError("platform risk file must include columns: platform_type, mode, value")

    risk = {}
    for _, row in df.iterrows():
        pt = str(row[cols["platform_type"]]).strip()
        mode = str(row[cols["mode"]]).strip()
        risk[(pt, mode)] = clamp01(row[cols["value"]])
    return risk


def test_execution_columns(conn):
    sql = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'test_execution'
    """
    df = pd.read_sql(sql, conn)
    return set(df["column_name"].tolist())


def build_runtime_expr(columns):
    # Returns minutes expression or NULL when no timing columns are available.
    if "duration" in columns:
        return "CASE WHEN te.duration IS NOT NULL THEN te.duration / 60.0 ELSE NULL END"
    if "end_time" in columns and "start_time" in columns:
        return "CASE WHEN te.end_time IS NOT NULL AND te.start_time IS NOT NULL THEN EXTRACT(EPOCH FROM (te.end_time - te.start_time)) / 60.0 ELSE NULL END"
    return "NULL"


def fetch_test_metrics(conn, version, start_date, end_date, runtime_expr, history_from_version):
    platform_list = "', '".join(KNOWN_PLATFORMS)
    history_condition = version_range_condition("te", history_from_version, version)

    sql = f"""
        WITH current_base AS (
            SELECT
                te.test_id,
                t.name AS test_name,
                CASE
                    WHEN d.platform IN ('UHT','MRQP','MR2') THEN 'FPGA'
                    WHEN d.platform IN ('ESXI','KVM','VL3','HT2') THEN 'Software'
                    WHEN d.platform IN ('MRQ_X','MRQX') THEN 'EZchip'
                    ELSE 'Other'
                END AS platform_type,
                CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END AS mode,
                te.status,
                te.start_time,
                {runtime_expr} AS runtime_minutes
            FROM test_execution te
            JOIN device d ON te.device_id = d.id
            JOIN profile p ON te.profile_id = p.id
            JOIN test t ON te.test_id = t.id
            WHERE te.version = '{version}'
              AND te.mode = 'regression'
              AND d.platform IN ('{platform_list}')
              AND te.start_time >= '{start_date}'
              AND te.start_time < '{end_date}'::date + interval '1 day'
              AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
        ),
        current_agg AS (
            SELECT
                test_id,
                MAX(test_name) AS test_name,
                platform_type,
                mode,
                COUNT(*) AS executions,
                SUM(CASE WHEN LOWER(status) = 'passed' THEN 1 ELSE 0 END) AS passed,
                SUM(CASE WHEN LOWER(status) IN ('failed','error','fail') THEN 1 ELSE 0 END) AS failed,
                MAX(start_time) AS last_execution
            FROM current_base
            WHERE platform_type != 'Other'
            GROUP BY test_id, platform_type, mode
        ),
                prior_presence AS (
                        SELECT DISTINCT te.test_id
                        FROM test_execution te
                        JOIN device d ON te.device_id = d.id
                        JOIN profile p ON te.profile_id = p.id
                        JOIN test t ON te.test_id = t.id
                        WHERE te.mode = 'regression'
                            AND d.platform IN ('{platform_list}')
                      AND {history_condition}
                      AND te.version <> '{version}'
                            AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
                ),
        history_base AS (
            SELECT
                te.test_id,
                CASE
                    WHEN d.platform IN ('UHT','MRQP','MR2') THEN 'FPGA'
                    WHEN d.platform IN ('ESXI','KVM','VL3','HT2') THEN 'Software'
                    WHEN d.platform IN ('MRQ_X','MRQX') THEN 'EZchip'
                    ELSE 'Other'
                END AS platform_type,
                CASE WHEN p.name LIKE '%-Routing' THEN 'Routing' ELSE 'Transparent' END AS mode,
                te.status,
                te.start_time,
                {runtime_expr} AS runtime_minutes
            FROM test_execution te
            JOIN device d ON te.device_id = d.id
            JOIN profile p ON te.profile_id = p.id
            JOIN test t ON te.test_id = t.id
            WHERE te.mode = 'regression'
              AND d.platform IN ('{platform_list}')
              AND {history_condition}
              AND NOT (p.name LIKE '%-Routing' AND LOWER(t.name) LIKE '%antiscan%')
        ),
        history_agg AS (
            SELECT
                test_id,
                platform_type,
                mode,
                COUNT(*) AS hist_executions,
                SUM(CASE WHEN LOWER(status) IN ('failed','error','fail') THEN 1 ELSE 0 END) AS hist_failed,
                AVG(runtime_minutes) AS hist_avg_runtime_minutes
            FROM history_base
            WHERE platform_type != 'Other'
            GROUP BY test_id, platform_type, mode
        ),
        recent_agg AS (
            SELECT
                test_id,
                platform_type,
                mode,
                SUM(CASE WHEN LOWER(status) IN ('failed','error','fail') THEN 1 ELSE 0 END) AS recent_failed_14d,
                COUNT(*) AS recent_exec_14d
            FROM history_base
            WHERE platform_type != 'Other'
              AND start_time >= NOW() - interval '14 days'
            GROUP BY test_id, platform_type, mode
        )
        SELECT
            c.test_id,
            c.test_name,
            c.platform_type,
            c.mode,
            c.executions,
            c.passed,
            c.failed,
            c.last_execution,
            CASE WHEN pp.test_id IS NULL THEN TRUE ELSE FALSE END AS is_new_test,
            COALESCE(h.hist_executions, c.executions) AS hist_executions,
            COALESCE(h.hist_failed, c.failed) AS hist_failed,
            COALESCE(h.hist_avg_runtime_minutes, 0.0) AS avg_runtime_minutes,
            COALESCE(r.recent_failed_14d, 0) AS recent_failed_14d,
            COALESCE(r.recent_exec_14d, 0) AS recent_exec_14d
        FROM current_agg c
        LEFT JOIN history_agg h
            ON h.test_id = c.test_id
           AND h.platform_type = c.platform_type
           AND h.mode = c.mode
        LEFT JOIN prior_presence pp
            ON pp.test_id = c.test_id
        LEFT JOIN recent_agg r
            ON r.test_id = c.test_id
           AND r.platform_type = c.platform_type
           AND r.mode = c.mode
    """
    return pd.read_sql(sql, conn)


def apply_overrides(scored_df, change_df, criticality_df, platform_risk):
    scored = scored_df.copy()

    scored["change_impact"] = 0.0
    scored["business_criticality"] = 0.5

    if not change_df.empty:
        if "test_id" in change_df.columns:
            merge_df = change_df[["test_id", "value"]].dropna(subset=["test_id"]).copy()
            merge_df["test_id"] = merge_df["test_id"].astype(int)
            scored = scored.merge(merge_df, on="test_id", how="left", suffixes=("", "_change_id"))
            scored["change_impact"] = scored["value"].fillna(scored["change_impact"])
            scored.drop(columns=["value"], inplace=True)

        if "test_name" in change_df.columns:
            merge_df = change_df[["test_name", "value"]].dropna(subset=["test_name"]).copy()
            merge_df["test_name"] = merge_df["test_name"].astype(str)
            scored = scored.merge(merge_df, on="test_name", how="left", suffixes=("", "_change_name"))
            scored["change_impact"] = scored["value"].fillna(scored["change_impact"])
            scored.drop(columns=["value"], inplace=True)

    if not criticality_df.empty:
        if "test_id" in criticality_df.columns:
            merge_df = criticality_df[["test_id", "value"]].dropna(subset=["test_id"]).copy()
            merge_df["test_id"] = merge_df["test_id"].astype(int)
            scored = scored.merge(merge_df, on="test_id", how="left", suffixes=("", "_bc_id"))
            scored["business_criticality"] = scored["value"].fillna(scored["business_criticality"])
            scored.drop(columns=["value"], inplace=True)

        if "test_name" in criticality_df.columns:
            merge_df = criticality_df[["test_name", "value"]].dropna(subset=["test_name"]).copy()
            merge_df["test_name"] = merge_df["test_name"].astype(str)
            scored = scored.merge(merge_df, on="test_name", how="left", suffixes=("", "_bc_name"))
            scored["business_criticality"] = scored["value"].fillna(scored["business_criticality"])
            scored.drop(columns=["value"], inplace=True)

    def lookup_risk(row):
        key = (row["platform_type"], row["mode"])
        return platform_risk.get(key, DEFAULT_PLATFORM_MODE_RISK.get(key, 0.5))

    scored["platform_mode_risk"] = scored.apply(lookup_risk, axis=1).apply(clamp01)
    scored["change_impact"] = scored["change_impact"].apply(clamp01)
    scored["business_criticality"] = scored["business_criticality"].apply(clamp01)

    return scored


def score_tests(df):
    scored = df.copy()

    failure_rate = (
        scored["hist_failed"] / scored["hist_executions"].clip(lower=1)
    ).clip(lower=0.0, upper=1.0)

    recent_failure_rate = scored["recent_failed_14d"] / scored["recent_exec_14d"].replace(0, pd.NA)
    recent_failure_rate = recent_failure_rate.fillna(0.0).clip(lower=0.0, upper=1.0)

    # Failure-volume signal: normalize log(1 + total historical failures) to
    # reward tests with repeated failures across long history windows.
    failure_volume_signal = normalize_series(
        (scored["hist_failed"].fillna(0).clip(lower=0) + 1).map(lambda x: math.log(x))
    ).fillna(0.0).clip(lower=0.0, upper=1.0)

    # Blend long-term rate, recent instability, and historical failure volume.
    scored["historical_failure"] = (
        failure_rate * 0.60 + recent_failure_rate * 0.20 + failure_volume_signal * 0.20
    ).clip(lower=0.0, upper=1.0)

    runtime = scored["avg_runtime_minutes"].fillna(0.0)
    scored["runtime_cost"] = normalize_series(runtime).fillna(0.0).clip(lower=0.0, upper=1.0)

    hw = scored.apply(
        lambda r: compute_hw_accel_relevance(r["platform_type"], r["test_name"]),
        axis=1,
    )
    scored["hw_accel_relevance"] = hw.map(lambda t: clamp01(t[0]))
    scored["hw_accel_features"] = hw.map(lambda t: t[1])

    weighted = (
        3 * scored["change_impact"]
        + 3 * scored["historical_failure"]
        + 2 * scored["platform_mode_risk"]
        + 1 * scored["hw_accel_relevance"]
        + 1 * scored["business_criticality"]
        - 1 * scored["runtime_cost"]
    )

    scored["priority_score"] = (100.0 * weighted / 9.0).round(2)

    scored["score_band"] = pd.cut(
        scored["priority_score"],
        bins=[-999, 39.99, 54.99, 79.99, 1000],
        labels=["P3-Low", "P2-Medium", "P1-High", "P0-Critical"],
    )

    scored.sort_values(
        by=["priority_score", "historical_failure", "executions"],
        ascending=[False, False, False],
        inplace=True,
    )

    return scored


def apply_new_test_policy(df, min_runs=3, enabled=True):
    scored = df.copy()
    scored["is_new_test"] = scored["is_new_test"].fillna(False).astype(bool)
    scored["new_test_stable"] = (
        scored["is_new_test"]
        & (scored["executions"].fillna(0) >= max(int(min_runs), 1))
        & (scored["failed"].fillna(0) == 0)
    )
    scored["new_test_policy_applied"] = False

    if enabled:
        promote_mask = scored["is_new_test"] & ~scored["new_test_stable"]
        promote_mask = promote_mask & scored["score_band"].isin(["P2-Medium", "P3-Low"])
        scored.loc[promote_mask, "score_band"] = "P1-High"
        scored.loc[promote_mask, "new_test_policy_applied"] = True

    return scored


def apply_defer_policy(df, profile="none"):
    scored = df.copy()
    scored["base_score_band"] = scored["score_band"].astype(str)
    scored["deferred_candidate"] = False
    scored["deferred_profile"] = ""

    if profile == "none":
        return scored

    for c in [
        "hist_failed",
        "hist_executions",
        "failed",
        "executions",
        "priority_score",
        "hw_accel_relevance",
    ]:
        scored[c] = pd.to_numeric(scored[c], errors="coerce").fillna(0)

    hist_fail_rate = (scored["hist_failed"] / scored["hist_executions"].replace(0, pd.NA)).fillna(0)
    curr_fail_rate = (scored["failed"] / scored["executions"].replace(0, pd.NA)).fillna(0)

    profiles = {
        "strict": (
            (scored["priority_score"] < 22)
            & (hist_fail_rate < 0.01)
            & (curr_fail_rate == 0)
            & (scored["hw_accel_relevance"] == 0)
        ),
        "balanced": (
            (scored["priority_score"] < 25)
            & (hist_fail_rate < 0.02)
            & (curr_fail_rate < 0.01)
            & (scored["hw_accel_relevance"] == 0)
        ),
        "aggressive": (
            (scored["priority_score"] < 28)
            & (hist_fail_rate < 0.03)
            & (curr_fail_rate < 0.02)
            & (scored["hw_accel_relevance"] == 0)
        ),
    }

    mask = profiles[profile]
    scored["deferred_candidate"] = mask
    scored.loc[mask, "deferred_profile"] = profile
    scored["score_band"] = scored["score_band"].astype(str)
    scored.loc[mask, "score_band"] = "P4-Deferred"
    return scored


def main():
    args = parse_args()

    if args.sprint_start and not args.sprint_end:
        raise ValueError("--sprint-end is required when --sprint-start is used")

    if args.ci_start:
        start_date = args.ci_start
        end_date = args.end or datetime.now().strftime("%Y-%m-%d")
        period_label = f"ci_{start_date}_to_{end_date}"
    else:
        start_date = args.sprint_start
        end_date = args.sprint_end
        period_label = f"sprint_{start_date}_to_{end_date}"

    output = args.output or f"ci_test_priority_map_{args.version.replace('.', '_')}_{period_label}.csv"

    conn = connect()
    try:
        columns = test_execution_columns(conn)
        runtime_expr = build_runtime_expr(columns)
        metrics = fetch_test_metrics(
            conn,
            args.version,
            start_date,
            end_date,
            runtime_expr,
            args.history_from_version,
        )

        if metrics.empty:
            print("No test execution data found for the selected period.")
            return

        change_df = read_override_file(args.change_impact_file, ["test_id", "test_name"])
        criticality_df = read_override_file(args.business_criticality_file, ["test_id", "test_name"])
        platform_risk = DEFAULT_PLATFORM_MODE_RISK.copy()
        platform_risk.update(load_platform_risk_overrides(args.platform_risk_file))

        merged = apply_overrides(metrics, change_df, criticality_df, platform_risk)
        scored = score_tests(merged)
        scored = apply_new_test_policy(
            scored,
            min_runs=args.new_test_min_runs,
            enabled=not args.disable_new_test_p1_policy,
        )
        scored = apply_defer_policy(scored, profile=args.defer_to_p4)

        cols = [
            "test_id",
            "test_name",
            "platform_type",
            "mode",
            "is_new_test",
            "new_test_stable",
            "new_test_policy_applied",
            "executions",
            "passed",
            "failed",
            "last_execution",
            "hist_executions",
            "hist_failed",
            "avg_runtime_minutes",
            "change_impact",
            "historical_failure",
            "platform_mode_risk",
            "hw_accel_relevance",
            "hw_accel_features",
            "business_criticality",
            "runtime_cost",
            "base_score_band",
            "deferred_candidate",
            "deferred_profile",
            "priority_score",
            "score_band",
        ]

        scored[cols].to_csv(output, index=False)

        print(f"Saved scored CI test map: {output}")
        print(f"Rows: {len(scored):,}")
        print(f"Historical scoring range: {args.history_from_version} -> {args.version}")
        if args.defer_to_p4 != "none":
            print(
                f"Deferred policy: {args.defer_to_p4} | "
                f"P4-Deferred rows: {int(scored['deferred_candidate'].sum()):,}"
            )
        print("Top 10:")
        print(
            scored[
                [
                    "test_id",
                    "test_name",
                    "platform_type",
                    "mode",
                    "priority_score",
                    "score_band",
                ]
            ]
            .head(10)
            .to_string(index=False)
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
