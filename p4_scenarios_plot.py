import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

file = "ci_test_priority_map_10_14_0_0_ci_2026-05-20_history_from_10_9_0_0_tuned_new_tests.csv"
df = pd.read_csv(file)

for c in [
    "hist_failed",
    "hist_executions",
    "failed",
    "executions",
    "avg_runtime_minutes",
    "priority_score",
    "hw_accel_relevance",
]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

df["hist_fail_rate"] = (df["hist_failed"] / df["hist_executions"].replace(0, pd.NA)).fillna(0)
df["curr_fail_rate"] = (df["failed"] / df["executions"].replace(0, pd.NA)).fillna(0)
df["cell"] = df["platform_type"].astype(str) + " | " + df["mode"].astype(str)

runners_per_cell = 4
base_wall_h = (df.groupby("cell")["avg_runtime_minutes"].sum() / runners_per_cell).max() / 60
total_tests = len(df)
total_runtime_h = df["avg_runtime_minutes"].sum() / 60

scenarios = {
    "Strict": (df["priority_score"] < 22)
    & (df["hist_fail_rate"] < 0.01)
    & (df["curr_fail_rate"] == 0)
    & (df["hw_accel_relevance"] == 0),
    "Balanced": (df["priority_score"] < 25)
    & (df["hist_fail_rate"] < 0.02)
    & (df["curr_fail_rate"] < 0.01)
    & (df["hw_accel_relevance"] == 0),
    "Aggressive": (df["priority_score"] < 28)
    & (df["hist_fail_rate"] < 0.03)
    & (df["curr_fail_rate"] < 0.02)
    & (df["hw_accel_relevance"] == 0),
}

rows = []
for name, mask in scenarios.items():
    s = df[mask]
    kept = df[~mask]
    wall_h = (kept.groupby("cell")["avg_runtime_minutes"].sum() / runners_per_cell).max() / 60
    rows.append(
        {
            "scenario": name,
            "tests_p4": len(s),
            "tests_p4_pct": len(s) / total_tests * 100,
            "runtime_saved_h": s["avg_runtime_minutes"].sum() / 60,
            "runtime_saved_days": (s["avg_runtime_minutes"].sum() / 60) / 24,
            "runtime_saved_pct": (s["avg_runtime_minutes"].sum() / 60) / total_runtime_h * 100,
            "wall_saved_h": base_wall_h - wall_h,
            "wall_saved_days": (base_wall_h - wall_h) / 24,
            "curr_failed_exec_in_p4": int(s["failed"].sum()),
        }
    )

out = pd.DataFrame(rows)
out.to_csv("priority_p4_scenarios_summary.csv", index=False)

colors = ["#2E7D32", "#1565C0", "#EF6C00"]
fig = make_subplots(
    rows=1,
    cols=3,
    subplot_titles=["P4 Tests (%)", "Runtime Saved (days)", "Wall-clock Saved (days)"],
)

fig.add_trace(
    go.Bar(
        x=out["scenario"],
        y=out["tests_p4_pct"],
        marker_color=colors,
        text=[f"{v:.1f}%" for v in out["tests_p4_pct"]],
        textposition="outside",
        name="P4 tests %",
    ),
    row=1,
    col=1,
)

fig.add_trace(
    go.Bar(
        x=out["scenario"],
        y=out["runtime_saved_days"],
        marker_color=colors,
        text=[f"{v:.1f}d" for v in out["runtime_saved_days"]],
        textposition="outside",
        name="Runtime saved days",
        showlegend=False,
    ),
    row=1,
    col=2,
)

fig.add_trace(
    go.Bar(
        x=out["scenario"],
        y=out["wall_saved_days"],
        marker_color=colors,
        text=[f"{v:.2f}d" for v in out["wall_saved_days"]],
        textposition="outside",
        name="Wall saved days",
        showlegend=False,
    ),
    row=1,
    col=3,
)

fig.update_layout(
    title="Priority Scenarios Comparison: Strict vs Balanced vs Aggressive",
    height=520,
    width=1400,
    margin=dict(l=40, r=40, t=80, b=60),
    template="plotly_white",
)

fig.update_yaxes(title_text="%", row=1, col=1)
fig.update_yaxes(title_text="Days", row=1, col=2)
fig.update_yaxes(title_text="Days", row=1, col=3)

notes = "<br>".join(
    [
        f"{r.scenario}: current failed executions inside P4 = {int(r.curr_failed_exec_in_p4)}"
        for _, r in out.iterrows()
    ]
)
notes += f"<br>Assumption: {runners_per_cell} runners per platform+mode cell"
fig.add_annotation(
    xref="paper",
    yref="paper",
    x=0.5,
    y=-0.20,
    showarrow=False,
    text=notes,
    font=dict(size=12, color="#444"),
)

fig.write_image("priority_p4_scenarios.png", scale=2)
print("created priority_p4_scenarios.png and priority_p4_scenarios_summary.csv")
