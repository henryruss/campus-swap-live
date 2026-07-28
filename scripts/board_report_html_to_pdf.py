"""Re-print /tmp/board_report/campus_swap_year_one.html to PDF without re-running
the data pull or the renderer.

Use this when you only want to tweak wording: open the HTML in an editor, change
the text, then run this to get an updated PDF.

    python3 scripts/board_report_html_to_pdf.py

WARNING: running board_report_render.py again regenerates that HTML from the
Python templates and will overwrite hand edits made here. For changes you want to
keep, edit the page blocks in scripts/board_report_render.py instead.
"""
import os
import shutil

HTML = '/tmp/board_report/campus_swap_year_one.html'
PDF = '/tmp/board_report/campus_swap_year_one.pdf'
PROJECT_COPY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'reports', 'campus_swap_year_one_board_report.pdf')


def main():
    if not os.path.exists(HTML):
        raise SystemExit(f'{HTML} not found — run scripts/board_report_render.py first.')

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 816, 'height': 1056})
        page.goto('file://' + HTML)
        page.wait_for_timeout(400)
        page.pdf(path=PDF, width='8.5in', height='11in', print_background=True,
                 margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'})
        for i, sec in enumerate(page.query_selector_all('section.page'), 1):
            sec.screenshot(path=f'/tmp/board_report/page_{i:02d}.png')
        browser.close()

    os.makedirs(os.path.dirname(PROJECT_COPY), exist_ok=True)
    shutil.copyfile(PDF, PROJECT_COPY)
    print(f'wrote {PDF}')
    print(f'wrote {PROJECT_COPY}')


if __name__ == '__main__':
    main()
