"""
PowerPoint Report Generator for DefensePro Weekly Report.
Converts unified report data into a multi-slide presentation.
"""
import os
import io
import json
from datetime import datetime

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.chart import XL_CHART_TYPE
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

try:
    import plotly.io as pio
    HAS_KALEIDO = True
except ImportError:
    HAS_KALEIDO = False


if HAS_PPTX:
    # Color scheme
    BLUE = RGBColor(0x19, 0x76, 0xD2)
    DARK_GRAY = RGBColor(0x42, 0x42, 0x42)
    LIGHT_GRAY = RGBColor(0x75, 0x75, 0x75)
    GREEN = RGBColor(0x27, 0xAE, 0x60)
    RED = RGBColor(0xE7, 0x4C, 0x3C)
    ORANGE = RGBColor(0xF3, 0x9C, 0x12)
    WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def _add_title_slide(prs, version, sprint_name, period, ci_run_start=None):
    """Slide 1: Title"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank layout

    # Blue header bar
    shape = slide.shapes.add_shape(1, Inches(0), Inches(0), Inches(10), Inches(2.5))  # Rectangle
    shape.fill.solid()
    shape.fill.fore_color.rgb = BLUE
    shape.line.fill.background()

    # Title text
    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(9), Inches(1.5))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = f"DefensePro {version}"
    p.font.size = Pt(36)
    p.font.bold = True
    p.font.color.rgb = WHITE

    p2 = tf.add_paragraph()
    p2.text = "Weekly Status Report"
    p2.font.size = Pt(24)
    p2.font.color.rgb = WHITE

    # Metadata
    txBox2 = slide.shapes.add_textbox(Inches(0.5), Inches(3), Inches(9), Inches(2))
    tf2 = txBox2.text_frame
    tf2.word_wrap = True
    lines = [
        f"Sprint: {sprint_name}",
        f"Period: {period}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    if ci_run_start:
        lines.append(f"CI Cycle Start: {ci_run_start}")
    for i, line in enumerate(lines):
        p = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
        p.text = line
        p.font.size = Pt(16)
        p.font.color.rgb = DARK_GRAY
        p.space_after = Pt(8)


def _add_summary_slide(prs, data):
    """Slide 2: Executive Summary with key metrics"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_slide_title(slide, "Executive Summary")

    metrics = [
        ("Bugs on Dev", str(data['bugs_on_dev']), ORANGE if data['bugs_on_dev'] > 0 else GREEN),
        ("Bugs on QA", str(data['bugs_on_qa']), ORANGE if data['bugs_on_qa'] > 3 else BLUE),
        ("Closed This Week", str(data['bugs_closed_week']), GREEN),
        ("Tests Executed", f"{data['total_tests']:,}", BLUE),
        ("Pass Ratio", f"{data['pass_ratio']:.1f}%", GREEN if data['pass_ratio'] >= 90 else RED),
        ("Coverage", f"{data.get('coverage', 0):.1f}%", BLUE),
    ]

    cols = 3
    for i, (label, value, color) in enumerate(metrics):
        row = i // cols
        col = i % cols
        left = Inches(0.5 + col * 3.1)
        top = Inches(1.8 + row * 2.2)

        # Card background
        card = slide.shapes.add_shape(1, left, top, Inches(2.8), Inches(1.8))
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(0xF5, 0xF5, 0xF5)
        card.line.color.rgb = RGBColor(0xE0, 0xE0, 0xE0)
        card.shadow.inherit = False

        # Value
        txBox = slide.shapes.add_textbox(left + Inches(0.2), top + Inches(0.2), Inches(2.4), Inches(1))
        tf = txBox.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = value
        p.font.size = Pt(28)
        p.font.bold = True
        p.font.color.rgb = color
        p.alignment = PP_ALIGN.CENTER

        # Label
        p2 = tf.add_paragraph()
        p2.text = label
        p2.font.size = Pt(12)
        p2.font.color.rgb = LIGHT_GRAY
        p2.alignment = PP_ALIGN.CENTER


def _add_bug_status_slide(prs, data):
    """Slide 3: Bug Status breakdown"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_slide_title(slide, "Bug Status Overview")

    # Summary text
    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(1))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = f"Active Bugs: {data['bugs_on_dev'] + data['bugs_on_qa']} | Closed this sprint: {data['bugs_closed_total']}"
    p.font.size = Pt(14)
    p.font.color.rgb = DARK_GRAY

    # Bug table
    if data.get('bugs_on_dev_list') or data.get('bugs_on_qa_list'):
        all_bugs = []
        for b in (data.get('bugs_on_dev_list') or [])[:5]:
            all_bugs.append(('Dev', b['key'], b['priority'], b['summary'][:50]))
        for b in (data.get('bugs_on_qa_list') or [])[:5]:
            all_bugs.append(('QA', b['key'], b['priority'], b['summary'][:50]))

        if all_bugs:
            rows = len(all_bugs) + 1
            table = slide.shapes.add_table(rows, 4, Inches(0.5), Inches(2.5), Inches(9), Inches(0.4 * rows)).table
            table.columns[0].width = Inches(0.8)
            table.columns[1].width = Inches(1.2)
            table.columns[2].width = Inches(1.2)
            table.columns[3].width = Inches(5.8)

            headers = ['Phase', 'Key', 'Priority', 'Summary']
            for i, h in enumerate(headers):
                cell = table.cell(0, i)
                cell.text = h
                cell.fill.solid()
                cell.fill.fore_color.rgb = BLUE
                for paragraph in cell.text_frame.paragraphs:
                    paragraph.font.color.rgb = WHITE
                    paragraph.font.size = Pt(10)
                    paragraph.font.bold = True

            for row_idx, (phase, key, priority, summary) in enumerate(all_bugs, 1):
                table.cell(row_idx, 0).text = phase
                table.cell(row_idx, 1).text = key
                table.cell(row_idx, 2).text = priority
                table.cell(row_idx, 3).text = summary
                for col_idx in range(4):
                    for paragraph in table.cell(row_idx, col_idx).text_frame.paragraphs:
                        paragraph.font.size = Pt(9)


def _add_automation_slide(prs, data):
    """Slide 4: Automation / CI metrics"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_slide_title(slide, "CI Iteration - Automation Status")

    lines = [
        f"Tests Executed: {data['total_tests']:,} unique tests, {data['total_executions']:,} total runs",
        f"Pass Ratio: {data['pass_ratio']:.1f}% ({data['passed']:,} passed / {data['failed']:,} failed)",
        f"Coverage: {data.get('coverage', 0):.1f}%",
    ]
    if data.get('critical_failures', 0) > 0:
        lines.append(f"Critical Failures: {data['critical_failures']} tests failing on ALL platforms")
    if data.get('avg_daily_rate'):
        lines.append(f"Velocity: {data['avg_daily_rate']}%/day")
    if data.get('projected_coverage'):
        lines.append(f"Projected at Sprint End: {data['projected_coverage']}%")

    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(1.8), Inches(9), Inches(4))
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"• {line}"
        p.font.size = Pt(14)
        p.font.color.rgb = DARK_GRAY
        p.space_after = Pt(12)


def _add_chart_slide(prs, title, fig_json, width=9, height=5):
    """Add a slide with a Plotly chart rendered as image."""
    if not fig_json or not HAS_KALEIDO:
        return

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_slide_title(slide, title)

    try:
        import plotly.io as pio
        fig = pio.from_json(fig_json)
        img_bytes = fig.to_image(format="png", width=int(width * 100), height=int(height * 100), scale=2)
        image_stream = io.BytesIO(img_bytes)
        slide.shapes.add_picture(image_stream, Inches(0.5), Inches(1.5), Inches(width), Inches(height))
    except Exception as e:
        # Fallback: add text noting chart couldn't be rendered
        txBox = slide.shapes.add_textbox(Inches(1), Inches(3), Inches(8), Inches(1))
        txBox.text_frame.paragraphs[0].text = f"[Chart not available: {str(e)[:80]}]"
        txBox.text_frame.paragraphs[0].font.size = Pt(12)
        txBox.text_frame.paragraphs[0].font.color.rgb = LIGHT_GRAY


def _add_sub_exec_slide(prs, data):
    """Slide: Sub Test Execution status"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_slide_title(slide, "Sub Test Execution Status")

    total = data.get('total', 0)
    completed = data.get('completed', 0)
    in_progress = data.get('in_progress', 0)
    not_started = data.get('not_started', 0)

    # Progress bar
    bar_top = Inches(1.8)
    bar_width = Inches(8)
    bar_height = Inches(0.5)

    # Background bar
    bg = slide.shapes.add_shape(1, Inches(1), bar_top, bar_width, bar_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = RGBColor(0xE0, 0xE0, 0xE0)
    bg.line.fill.background()

    # Progress fill
    if total > 0:
        pct = completed / total
        fg = slide.shapes.add_shape(1, Inches(1), bar_top, Inches(8 * pct), bar_height)
        fg.fill.solid()
        fg.fill.fore_color.rgb = GREEN
        fg.line.fill.background()

    # Stats text
    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(2.6), Inches(9), Inches(3))
    tf = txBox.text_frame
    tf.word_wrap = True
    lines = [
        f"Total: {total} sub test executions",
        f"Completed: {completed} ({completed/max(total,1)*100:.0f}%)",
        f"In Progress: {in_progress}",
        f"Not Started: {not_started}",
    ]

    # Xray metrics if available
    xray = data.get('xray', {})
    if xray.get('total_tests', 0) > 0:
        lines.append("")
        lines.append(f"Xray Test Runs: {xray['total_tests']}")
        lines.append(f"Testing Coverage: {xray.get('testing_coverage', 0):.1f}%")
        lines.append(f"Pass Ratio: {xray.get('pass_ratio', 0):.1f}%")
        lines.append(f"Automation Coverage: {xray.get('automation_coverage', 0):.1f}%")

    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"• {line}" if line else ""
        p.font.size = Pt(13)
        p.font.color.rgb = DARK_GRAY
        p.space_after = Pt(8)


def _add_changelog_slide(prs, build_changelogs):
    """Slide: Build changelog summary"""
    if not build_changelogs:
        return

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_slide_title(slide, "Build Changes in CI Cycle")

    total_changes = sum(len(b['changes']) for b in build_changelogs)

    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(5.5))
    tf = txBox.text_frame
    tf.word_wrap = True

    p = tf.paragraphs[0]
    p.text = f"{total_changes} change(s) across {len(build_changelogs)} build(s)"
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = DARK_GRAY
    p.space_after = Pt(16)

    for build in build_changelogs:
        p = tf.add_paragraph()
        result_icon = "✓" if build.get('result') == 'SUCCESS' else "✗"
        p.text = f"{result_icon} {build['displayName']} — {len(build['changes'])} change(s)"
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = GREEN if build.get('result') == 'SUCCESS' else RED
        p.space_before = Pt(10)

        for change in build['changes'][:5]:  # Max 5 changes per build
            p = tf.add_paragraph()
            p.text = f"    {change['commitId']} {change['msg'][:70]} ({change['author']})"
            p.font.size = Pt(9)
            p.font.color.rgb = LIGHT_GRAY

        if len(build['changes']) > 5:
            p = tf.add_paragraph()
            p.text = f"    ... and {len(build['changes']) - 5} more"
            p.font.size = Pt(9)
            p.font.color.rgb = LIGHT_GRAY


def _add_insights_slide(prs, insights, ai_insights=None):
    """Slide: Key insights"""
    if not insights and not ai_insights:
        return

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_slide_title(slide, "Key Insights")

    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(5.5))
    tf = txBox.text_frame
    tf.word_wrap = True

    if insights:
        for i, insight in enumerate(insights[:8]):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = f"• {insight}"
            p.font.size = Pt(12)
            p.font.color.rgb = DARK_GRAY
            p.space_after = Pt(8)

    if ai_insights:
        p = tf.add_paragraph()
        p.space_before = Pt(16)
        p = tf.add_paragraph()
        p.text = "AI-Generated Insights:"
        p.font.size = Pt(12)
        p.font.bold = True
        p.font.color.rgb = BLUE
        p.space_after = Pt(8)

        # Strip HTML tags from ai_insights
        import re
        clean = re.sub(r'<[^>]+>', '', ai_insights)
        for line in clean.split('\n')[:10]:
            line = line.strip()
            if line:
                p = tf.add_paragraph()
                p.text = line[:120]
                p.font.size = Pt(10)
                p.font.color.rgb = DARK_GRAY


def _add_slide_title(slide, title):
    """Add a consistent title to a slide."""
    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(1))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(24)
    p.font.bold = True
    p.font.color.rgb = BLUE

    # Underline
    line = slide.shapes.add_shape(1, Inches(0.5), Inches(1.1), Inches(9), Inches(0.03))
    line.fill.solid()
    line.fill.fore_color.rgb = BLUE
    line.line.fill.background()


def generate_ppt(report_data, output_path):
    """
    Generate a PowerPoint presentation from report data.
    
    Args:
        report_data: dict with all report sections
        output_path: path to save the .pptx file
    
    Returns:
        output_path if successful, None if python-pptx not available
    """
    if not HAS_PPTX:
        print("⚠️  python-pptx not installed, skipping PPT generation")
        return None

    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    # Slide 1: Title
    _add_title_slide(
        prs,
        version=report_data.get('version', ''),
        sprint_name=report_data.get('sprint_name', ''),
        period=report_data.get('period', ''),
        ci_run_start=report_data.get('ci_run_start'),
    )

    # Slide 2: Executive Summary
    _add_summary_slide(prs, report_data)

    # Slide 3: Bug Status
    _add_bug_status_slide(prs, report_data)

    # Slide 4: Automation / CI
    _add_automation_slide(prs, report_data)

    # Slide 5: Charts (bug trend)
    if report_data.get('bug_trend_fig_json'):
        _add_chart_slide(prs, "Bug Trend", report_data['bug_trend_fig_json'])

    # Slide 6: Charts (automation)
    if report_data.get('automation_fig_json'):
        _add_chart_slide(prs, "Automation Results", report_data['automation_fig_json'])

    # Slide 7: Sub Test Execution
    if report_data.get('sub_exec_total', 0) > 0:
        _add_sub_exec_slide(prs, {
            'total': report_data.get('sub_exec_total', 0),
            'completed': report_data.get('sub_exec_completed', 0),
            'in_progress': report_data.get('sub_exec_in_progress', 0),
            'not_started': report_data.get('sub_exec_not_started', 0),
            'xray': report_data.get('xray_summary', {}),
        })

    # Slide 8: Build Changelog
    _add_changelog_slide(prs, report_data.get('build_changelogs'))

    # Slide 9: Insights
    _add_insights_slide(prs, report_data.get('insights'), report_data.get('ai_insights'))

    prs.save(output_path)
    return output_path
