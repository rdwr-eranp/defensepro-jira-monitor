"""Generate TLS coverage HTML report for 10.10.5.1 vs 10.10.5.0 baseline,
broken down by platform type x mode (same layout as unified_weekly_report).
"""
import os, html
import psycopg2
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
VERSION = '10.10.5.1'
BASELINE = '10.10.5.0'
TEST_FILTER = 'tls'  # LOWER(t.name) LIKE %TEST_FILTER%

PLATFORM_CASE = """
    CASE WHEN d.platform IN ('UHT','MRQP','MR2') THEN 'FPGA'
         WHEN d.platform IN ('ESXI','KVM','VL3','HT2') THEN 'Software'
         WHEN d.platform IN ('MRQ_X','MRQX') THEN 'EZchip'
         ELSE 'Other' END
"""
MODE_CASE = "CASE WHEN p.name LIKE '%%-Routing' THEN 'Routing' ELSE 'Transparent' END"

conn = psycopg2.connect(
    host=os.getenv('PG_HOST', '10.185.20.124'),
    port=os.getenv('PG_PORT', '5432'),
    database=os.getenv('PG_DATABASE', 'results'),
    user=os.getenv('PG_USER', 'postgres'),
    password=os.getenv('PG_PASSWORD', ''),
)

# --- Latest execution per (test_id, platform_type, mode) on VERSION ---
exec_q = f"""
WITH latest AS (
  SELECT te.test_id, t.name AS test_name,
         {PLATFORM_CASE} AS platform_type,
         {MODE_CASE} AS mode,
         te.status,
         ROW_NUMBER() OVER (
           PARTITION BY te.test_id, {PLATFORM_CASE}, {MODE_CASE}
           ORDER BY te.start_time DESC
         ) AS rn
  FROM test_execution te
  JOIN device d ON te.device_id = d.id
  JOIN profile p ON te.profile_id = p.id
  JOIN test t ON te.test_id = t.id
  WHERE te.version = %(ver)s AND te.mode = 'regression'
    AND LOWER(t.name) LIKE %(flt)s
)
SELECT test_id, test_name, platform_type, mode, status FROM latest WHERE rn = 1
"""
exec_df = pd.read_sql(exec_q, conn, params={'ver': VERSION, 'flt': f'%{TEST_FILTER}%'})
exec_df['status_lower'] = exec_df['status'].str.lower()
exec_df['pt_mode'] = exec_df['platform_type'] + ' - ' + exec_df['mode']

# --- Available tests (baseline) per platform_type x mode ---
avail_q = f"""
SELECT {PLATFORM_CASE} AS platform_type,
       {MODE_CASE} AS mode,
       COUNT(DISTINCT te.test_id) AS available_tests
FROM test_execution te
JOIN device d ON te.device_id = d.id
JOIN profile p ON te.profile_id = p.id
JOIN test t ON te.test_id = t.id
WHERE te.version = %(ver)s AND te.mode = 'regression'
  AND LOWER(t.name) LIKE %(flt)s
GROUP BY 1, 2
"""
avail_df = pd.read_sql(avail_q, conn, params={'ver': BASELINE, 'flt': f'%{TEST_FILTER}%'})
avail_df['pt_mode'] = avail_df['platform_type'] + ' - ' + avail_df['mode']

# --- Build matrix ---
all_pt = ['EZchip', 'FPGA', 'Software']
all_modes = ['Routing', 'Transparent']
combos = [f'{pt} - {m}' for pt in all_pt for m in all_modes]

rows = []
for combo in combos:
    sub = exec_df[exec_df['pt_mode'] == combo]
    tests = len(sub)
    passed = int((sub['status_lower'] == 'passed').sum())
    failed = int(sub['status_lower'].isin(['failed', 'fail', 'error']).sum())
    avail = int(avail_df.loc[avail_df['pt_mode'] == combo, 'available_tests'].sum())
    coverage = min((tests / avail) * 100, 100.0) if avail else 0
    pass_ratio = (passed / tests * 100) if tests else 0
    rows.append({
        'pt_mode': combo,
        'tests': tests, 'available': avail, 'coverage': coverage,
        'passed': passed, 'failed': failed, 'pass_ratio': pass_ratio,
    })

# Failed test names for footer
fail_df = exec_df[exec_df['status_lower'].isin(['failed', 'fail', 'error'])][
    ['test_name', 'platform_type', 'mode']
].drop_duplicates().sort_values(['platform_type', 'mode', 'test_name'])

# Totals
total_tests = sum(r['tests'] for r in rows)
total_avail = sum(r['available'] for r in rows)
total_passed = sum(r['passed'] for r in rows)
total_failed = sum(r['failed'] for r in rows)
overall_cov = min((total_tests / total_avail) * 100, 100.0) if total_avail else 0
overall_pass = (total_passed / total_tests * 100) if total_tests else 0


def cov_color(c):
    if c >= 80: return '#43a047'
    if c >= 50: return '#fbc02d'
    if c >= 20: return '#fb8c00'
    return '#e53935'


def pass_color(p):
    if p >= 95: return '#43a047'
    if p >= 80: return '#fbc02d'
    return '#e53935'


# --- HTML ---
def row_html(r):
    cov_c = cov_color(r['coverage'])
    pass_c = pass_color(r['pass_ratio'])
    return f"""
    <tr>
      <td><strong>{html.escape(r['pt_mode'])}</strong></td>
      <td style="text-align:center;">{r['tests']}</td>
      <td style="text-align:center;">{r['available']}</td>
      <td style="text-align:center;">
        <span style="background:{cov_c};color:white;padding:3px 10px;border-radius:4px;font-weight:bold;">{r['coverage']:.1f}%</span>
        <div class="bar-container" style="margin-top:4px;"><div class="bar" style="background:{cov_c};width:{r['coverage']:.0f}%;"></div></div>
      </td>
      <td style="text-align:center;color:#43a047;font-weight:bold;">{r['passed']}</td>
      <td style="text-align:center;color:#e53935;font-weight:bold;">{r['failed']}</td>
      <td style="text-align:center;">
        <span style="background:{pass_c};color:white;padding:3px 10px;border-radius:4px;font-weight:bold;">{r['pass_ratio']:.1f}%</span>
      </td>
    </tr>"""

table_rows = ''.join(row_html(r) for r in rows)
fail_rows = ''.join(
    f'<tr><td>{html.escape(t)}</td><td>{html.escape(pt)}</td><td>{html.escape(m)}</td></tr>'
    for t, pt, m in fail_df.itertuples(index=False)
) or '<tr><td colspan="3" style="text-align:center;color:#43a047;">No failures</td></tr>'

# Plotly bar charts data
pt_modes_js = [r['pt_mode'] for r in rows]
cov_vals = [round(r['coverage'], 1) for r in rows]
cov_colors = [cov_color(r['coverage']) for r in rows]
pass_vals = [round(r['pass_ratio'], 1) for r in rows]
pass_colors = [pass_color(r['pass_ratio']) for r in rows]

import json
html_out = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>TLS Coverage - DefensePro {VERSION}</title>
<style>
body {{ font-family:'Segoe UI',Tahoma,sans-serif; margin:0; padding:20px; background:#f5f5f5; }}
.container {{ max-width:1400px; margin:0 auto; background:white; padding:30px; box-shadow:0 2px 10px rgba(0,0,0,0.1); }}
h1 {{ color:#1976d2; border-bottom:3px solid #1976d2; padding-bottom:10px; }}
h2 {{ color:#424242; margin-top:30px; border-bottom:2px solid #e0e0e0; padding-bottom:8px; }}
.metadata {{ background:#e3f2fd; padding:15px; border-left:4px solid #1976d2; margin-bottom:25px; }}
.summary-box {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:20px; margin:25px 0; }}
.metric-card {{ padding:20px; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.1); color:white; }}
.mc-tests {{ background:linear-gradient(135deg,#667eea 0%,#764ba2 100%); }}
.mc-cov   {{ background:linear-gradient(135deg,#4facfe 0%,#00f2fe 100%); }}
.mc-pass  {{ background:linear-gradient(135deg,#00b894 0%,#00cec9 100%); }}
.mc-fail  {{ background:linear-gradient(135deg,#f5576c 0%,#f093fb 100%); }}
.metric-label {{ font-size:14px; opacity:0.9; }}
.metric-number {{ font-size:36px; font-weight:bold; margin:10px 0; }}
.metric-detail {{ font-size:13px; opacity:0.9; }}
table {{ width:100%; border-collapse:collapse; margin:20px 0; box-shadow:0 2px 4px rgba(0,0,0,0.05); }}
th {{ background:#1976d2; color:white; padding:12px; text-align:left; font-weight:600; }}
td {{ padding:10px 12px; border-bottom:1px solid #e0e0e0; }}
tr:hover {{ background:#f9f9f9; }}
.bar-container {{ background:#e0e0e0; border-radius:4px; overflow:hidden; height:8px; }}
.bar {{ height:8px; }}
.alert-box {{ background:#fff3cd; border-left:4px solid #ffc107; padding:15px; margin:20px 0; }}
.alert-box.info {{ background:#e3f2fd; border-left-color:#2196f3; }}
.alert-box.danger {{ background:#ffebee; border-left-color:#f44336; }}
.alert-box.success {{ background:#e8f5e9; border-left-color:#43a047; }}
.chart-container {{ margin:20px 0; padding:15px; background:white; border-radius:8px; }}
.footer {{ margin-top:40px; padding-top:20px; border-top:1px solid #e0e0e0; text-align:center; color:#666; font-size:12px; }}
</style>
</head>
<body>
<div class="container">
  <h1>TLS Test Coverage - DefensePro {VERSION}</h1>
  <div class="metadata">
    <strong>Project:</strong> DP (DefensePro)<br>
    <strong>Current Version:</strong> {VERSION}<br>
    <strong>Baseline (coverage reference):</strong> {BASELINE}<br>
    <strong>Test Filter:</strong> name LIKE '%{TEST_FILTER}%' (regression mode)<br>
    <strong>Report Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  </div>

  <div class="alert-box info">
    <strong>📋 Note:</strong> Coverage = (distinct TLS tests executed on {VERSION}) / (distinct TLS tests in {BASELINE} baseline) per platform-type x mode. Pass Ratio is on the latest result per (test, platform-type, mode).
  </div>

  <div class="summary-box">
    <div class="metric-card mc-tests">
      <div class="metric-label">Tests Executed</div>
      <div class="metric-number">{total_tests}</div>
      <div class="metric-detail">of {total_avail} in baseline</div>
    </div>
    <div class="metric-card mc-cov">
      <div class="metric-label">Overall Coverage</div>
      <div class="metric-number">{overall_cov:.1f}%</div>
      <div class="metric-detail">vs {BASELINE}</div>
    </div>
    <div class="metric-card mc-pass">
      <div class="metric-label">Pass Ratio</div>
      <div class="metric-number">{overall_pass:.1f}%</div>
      <div class="metric-detail">{total_passed} passed / {total_tests}</div>
    </div>
    <div class="metric-card mc-fail">
      <div class="metric-label">Failed</div>
      <div class="metric-number">{total_failed}</div>
      <div class="metric-detail">unique (test, platform, mode)</div>
    </div>
  </div>

  <h2>📊 Coverage & Pass Ratio per Platform Type x Mode</h2>
  <div id="cov-chart" class="chart-container"></div>
  <div id="pass-chart" class="chart-container"></div>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <script>
  Plotly.newPlot('cov-chart', [{{
    type:'bar',
    x: {json.dumps(pt_modes_js)},
    y: {json.dumps(cov_vals)},
    marker:{{ color: {json.dumps(cov_colors)} }},
    text: {json.dumps([f'{v}%' for v in cov_vals])}, textposition:'outside'
  }}], {{
    title:'Coverage (%) per Platform Type x Mode - {VERSION}',
    yaxis:{{ title:'Coverage %', range:[0,110] }},
    xaxis:{{ title:'Platform Type x Mode' }},
    height:420
  }}, {{responsive:true}});
  Plotly.newPlot('pass-chart', [{{
    type:'bar',
    x: {json.dumps(pt_modes_js)},
    y: {json.dumps(pass_vals)},
    marker:{{ color: {json.dumps(pass_colors)} }},
    text: {json.dumps([f'{v}%' for v in pass_vals])}, textposition:'outside'
  }}], {{
    title:'Pass Ratio (%) per Platform Type x Mode - {VERSION}',
    yaxis:{{ title:'Pass Ratio %', range:[0,110] }},
    xaxis:{{ title:'Platform Type x Mode' }},
    height:420
  }}, {{responsive:true}});
  </script>

  <h2>📋 Detailed Breakdown</h2>
  <table>
    <thead>
      <tr>
        <th>Platform Type x Mode</th>
        <th style="text-align:center;">Tests Executed</th>
        <th style="text-align:center;">Available (baseline)</th>
        <th style="text-align:center;">Coverage</th>
        <th style="text-align:center;">Passed</th>
        <th style="text-align:center;">Failed</th>
        <th style="text-align:center;">Pass Ratio</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
      <tr style="font-weight:bold;background:#f5f5f5;">
        <td>TOTAL</td>
        <td style="text-align:center;">{total_tests}</td>
        <td style="text-align:center;">{total_avail}</td>
        <td style="text-align:center;">{overall_cov:.1f}%</td>
        <td style="text-align:center;color:#43a047;">{total_passed}</td>
        <td style="text-align:center;color:#e53935;">{total_failed}</td>
        <td style="text-align:center;">{overall_pass:.1f}%</td>
      </tr>
    </tbody>
  </table>

  <h2>❌ Failures ({total_failed})</h2>
  <table>
    <thead><tr><th>Test Name</th><th>Platform Type</th><th>Mode</th></tr></thead>
    <tbody>{fail_rows}</tbody>
  </table>

  <div class="footer">
    TLS Coverage Report - {VERSION} - Generated {datetime.now().strftime('%Y-%m-%d')}
  </div>
</div>
</body>
</html>
"""

out = f'tls_coverage_{VERSION.replace(".", "_")}.html'
with open(out, 'w', encoding='utf-8') as f:
    f.write(html_out)
print(f'Report written: {out}')
print(f'Total tests: {total_tests}/{total_avail} ({overall_cov:.1f}%)  Passed: {total_passed}  Failed: {total_failed}  Pass: {overall_pass:.1f}%')
for r in rows:
    print(f"  {r['pt_mode']:25s} {r['tests']:>3}/{r['available']:<3} cov={r['coverage']:>5.1f}%  P={r['passed']:>3} F={r['failed']:>3} pass={r['pass_ratio']:>5.1f}%")
