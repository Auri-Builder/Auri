"""
tests/test_ui_smoke.py
----------------------
Playwright smoke tests for the Auri Streamlit app.

Requires the app to be running before executing:
    streamlit run Home.py --server.port 8501 --server.headless true

Run with:
    pytest tests/test_ui_smoke.py -v --base-url http://localhost:8501

Or with headed browser for visual debugging:
    pytest tests/test_ui_smoke.py -v --headed --base-url http://localhost:8501
"""

import re
import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:8501"

# How long to wait for Streamlit to finish rendering (ms)
STREAMLIT_TIMEOUT = 15_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for_streamlit(page: Page) -> None:
    """Wait until the Streamlit 'Running…' spinner disappears."""
    # Streamlit shows a status indicator while rerunning
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"stStatusWidget\"]')"
        " || document.querySelector('[data-testid=\"stStatusWidget\"]').innerText === ''",
        timeout=STREAMLIT_TIMEOUT,
    )
    # Also wait for the main content block to appear
    page.wait_for_selector("[data-testid='stAppViewContainer']", timeout=STREAMLIT_TIMEOUT)


def no_error_banner(page: Page) -> None:
    """Assert no Streamlit error/exception alert is visible."""
    error_locator = page.locator("[data-testid='stException'], .stException, [data-testid='stAlert'][kind='error']")
    expect(error_locator).to_have_count(0, timeout=3_000)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Set a realistic viewport."""
    return {**browser_context_args, "viewport": {"width": 1440, "height": 900}}


# ---------------------------------------------------------------------------
# Hub / Home
# ---------------------------------------------------------------------------

class TestHome:
    def test_loads(self, page: Page):
        """Home page loads without errors."""
        page.goto(BASE_URL)
        wait_for_streamlit(page)
        no_error_banner(page)

    def test_title_visible(self, page: Page):
        """Auri branding appears on the home page."""
        page.goto(BASE_URL)
        wait_for_streamlit(page)
        # Title or heading contains "Auri"
        expect(page.get_by_text(re.compile(r"Auri", re.IGNORECASE)).first).to_be_visible()

    def test_sidebar_navigation_links(self, page: Page):
        """Sidebar contains nav links for all main pages."""
        page.goto(BASE_URL)
        wait_for_streamlit(page)
        sidebar = page.locator("[data-testid='stSidebarNav']")
        expect(sidebar).to_be_visible()
        for label in ("Portfolio", "Wealth", "Retirement"):
            expect(sidebar.get_by_text(re.compile(label, re.IGNORECASE)).first).to_be_visible()


# ---------------------------------------------------------------------------
# Portfolio IA  (page 1)
# ---------------------------------------------------------------------------

class TestPortfolioPage:
    PAGE = f"{BASE_URL}/Portfolio"

    def test_loads(self, page: Page):
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        no_error_banner(page)

    def test_heading_visible(self, page: Page):
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        expect(page.get_by_text(re.compile(r"Portfolio", re.IGNORECASE)).first).to_be_visible()

    def test_no_unhandled_exception(self, page: Page):
        """Catch Python traceback blocks rendered by Streamlit."""
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        tb = page.locator("text=Traceback (most recent call last)")
        expect(tb).to_have_count(0)


# ---------------------------------------------------------------------------
# Analysis  (page 5)
# ---------------------------------------------------------------------------

class TestAnalysisPage:
    PAGE = f"{BASE_URL}/Analysis"

    def test_loads(self, page: Page):
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        no_error_banner(page)

    def test_no_unhandled_exception(self, page: Page):
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        expect(page.locator("text=Traceback (most recent call last)")).to_have_count(0)


# ---------------------------------------------------------------------------
# Wealth Builder  (page 6)
# ---------------------------------------------------------------------------

class TestWealthBuilderPage:
    PAGE = f"{BASE_URL}/WealthBuilder"

    def test_loads(self, page: Page):
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        no_error_banner(page)

    def test_five_tabs_visible(self, page: Page):
        """All five Wealth Builder tabs are rendered."""
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        tabs = page.locator("[data-testid='stTab']")
        expect(tabs).to_have_count(5)

    def test_rrsp_tfsa_tab(self, page: Page):
        """RRSP vs TFSA tab renders a result section."""
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        # Click first tab (RRSP vs TFSA)
        page.locator("[data-testid='stTab']").first.click()
        wait_for_streamlit(page)
        no_error_banner(page)

    def test_savings_projector_tab(self, page: Page):
        """Savings Projector tab is accessible."""
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        page.locator("[data-testid='stTab']").nth(1).click()
        wait_for_streamlit(page)
        no_error_banner(page)

    def test_net_worth_tab(self, page: Page):
        """Net Worth tab is accessible."""
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        page.locator("[data-testid='stTab']").nth(4).click()
        wait_for_streamlit(page)
        no_error_banner(page)

    def test_no_unhandled_exception(self, page: Page):
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        expect(page.locator("text=Traceback (most recent call last)")).to_have_count(0)


# ---------------------------------------------------------------------------
# Retirement Planner  (page 7)
# ---------------------------------------------------------------------------

class TestRetirementPage:
    PAGE = f"{BASE_URL}/Retirement"

    def test_loads(self, page: Page):
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        no_error_banner(page)

    def test_spending_phase_sidebar_controls(self, page: Page):
        """Sidebar spending phase toggles are present."""
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        sidebar = page.locator("[data-testid='stSidebar']")
        expect(sidebar.get_by_text(re.compile(r"Slow.Go", re.IGNORECASE)).first).to_be_visible()
        expect(sidebar.get_by_text(re.compile(r"No.Go", re.IGNORECASE)).first).to_be_visible()

    def test_no_unhandled_exception(self, page: Page):
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        expect(page.locator("text=Traceback (most recent call last)")).to_have_count(0)


# ---------------------------------------------------------------------------
# CSV Wizard
# ---------------------------------------------------------------------------

class TestWizardPage:
    PAGE = f"{BASE_URL}/wizard"

    def test_loads(self, page: Page):
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        no_error_banner(page)

    def test_file_uploader_present(self, page: Page):
        """File uploader widget is visible on the wizard page."""
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        uploader = page.locator("[data-testid='stFileUploader']")
        expect(uploader.first).to_be_visible()

    def test_no_unhandled_exception(self, page: Page):
        page.goto(self.PAGE)
        wait_for_streamlit(page)
        expect(page.locator("text=Traceback (most recent call last)")).to_have_count(0)
