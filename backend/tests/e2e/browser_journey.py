"""Critical browser journeys (Playwright, using the locally installed Microsoft Edge).

Prerequisites: backend on :8000 and frontend on :5173 (scripts/start.ps1).
Run:  .venv\Scripts\python tests\e2e\browser_journey.py [screenshot_dir]
Exits non-zero if any journey step fails.
"""
import sys
import time
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://localhost:5173"
PWD = "PayInsight@2026"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
results = []


def step(name):
    def deco(fn):
        def run(*a):
            t0 = time.perf_counter()
            try:
                fn(*a)
                results.append((name, "PASS", time.perf_counter() - t0, ""))
            except Exception as exc:  # noqa: BLE001
                try:
                    page.screenshot(path=OUT / f"FAILED_{name.split()[0]}.png", full_page=True)
                except Exception:  # noqa: BLE001
                    pass
                results.append((name, "FAIL", time.perf_counter() - t0, str(exc).splitlines()[0][:200]))
        return run
    return deco


def login(page, email):
    page.goto(BASE)
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password", exact=True).fill(PWD)
    page.locator("form").get_by_role("button", name="Sign in").click()
    expect(page.get_by_text("Payments overview")).to_be_visible(timeout=15000)


def ask(page, q):
    page.get_by_role("button", name="Analytics Workspace").click()
    page.get_by_placeholder("e.g. Why did payment success rate decline?").fill(q)
    page.get_by_role("button", name="Run analysis").click()


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    @step("J1 login page renders demo accounts")
    def j1():
        page.goto(BASE)
        expect(page.get_by_text("admin@payinsight.demo")).to_be_visible()
        page.screenshot(path=OUT / "01_login.png")
    j1()

    @step("J2 admin login and dashboard KPIs/charts")
    def j2():
        login(page, "admin@payinsight.demo")
        page.get_by_role("combobox").first.select_option("A")
        expect(page.get_by_text("Payment success rate").first).to_be_visible()
        page.wait_for_timeout(1500)
        page.screenshot(path=OUT / "02_dashboard.png", full_page=True)
    j2()

    @step("J3 scenario B root-cause analysis with SQL + evidence")
    def j3():
        page.get_by_role("combobox").first.select_option("B")
        expect(page.get_by_text("Scenario B active")).to_be_visible(timeout=30000)
        ask(page, "Why did payment success rate decline?")
        expect(page.get_by_text("Deccan Commercial Bank").first).to_be_visible(timeout=20000)
        expect(page.get_by_text("Verdict:")).to_be_visible()
        expect(page.get_by_text("OBSERVED FACTS", exact=False).first).to_be_visible()
        page.wait_for_timeout(1200)
        page.screenshot(path=OUT / "03_why_decline.png", full_page=True)
    j3()

    @step("J4 scenario D mix decomposition")
    def j4():
        page.get_by_role("combobox").first.select_option("D")
        expect(page.get_by_text("Scenario D active")).to_be_visible(timeout=30000)
        ask(page, "Is the decline caused by payment-method mix?")
        expect(page.get_by_text("Verdict: Transaction mix shift").first).to_be_visible(timeout=20000)
        page.wait_for_timeout(1200)
        page.screenshot(path=OUT / "04_mix_shift.png", full_page=True)
    j4()

    @step("J5 scenario E data-quality warnings visible")
    def j5():
        page.get_by_role("combobox").first.select_option("E")
        expect(page.get_by_text("Scenario E active")).to_be_visible(timeout=30000)
        page.get_by_role("button", name="Data Quality & Sources").click()
        expect(page.get_by_text("Duplicate transaction IDs")).to_be_visible(timeout=15000)
        expect(page.get_by_text("FAIL", exact=True).first).to_be_visible()
        page.screenshot(path=OUT / "05_data_quality.png", full_page=True)
    j5()

    @step("J6 scenario G source discrepancy flagged")
    def j6():
        page.get_by_role("combobox").first.select_option("G")
        expect(page.get_by_text("Scenario G active")).to_be_visible(timeout=30000)
        page.get_by_role("button", name="Source reconciliation").click()
        expect(page.get_by_text("Ganga Valley Bank").first).to_be_visible(timeout=15000)
        expect(page.get_by_text("CRITICAL").first).to_be_visible()
        page.screenshot(path=OUT / "06_reconciliation.png", full_page=True)
        page.get_by_role("combobox").first.select_option("A")
        expect(page.get_by_text("Scenario A active")).to_be_visible(timeout=30000)
    j6()

    @step("J7 viewer bank-level request rejected (HTTP 403)")
    def j7():
        page.get_by_title("Sign out").click()
        login(page, "viewer@payinsight.demo")
        expect(page.get_by_text("Bank performance is restricted")).to_be_visible(timeout=15000)
        ask(page, "Compare payment success rates by bank")
        expect(page.get_by_text("Access denied — HTTP 403")).to_be_visible(timeout=15000)
        page.screenshot(path=OUT / "07_viewer_403.png", full_page=True)
    j7()

    @step("J8 ambiguous question asks for clarification")
    def j8():
        ask(page, "How are we doing?")
        expect(page.get_by_text("Clarification needed")).to_be_visible(timeout=15000)
    j8()

    @step("J9 session survives page reload (httpOnly refresh cookie, token not in storage)")
    def j9():
        page.reload()
        expect(page.get_by_text("Payments overview")).to_be_visible(timeout=15000)
        stored = page.evaluate("() => JSON.stringify({...localStorage}) + JSON.stringify({...sessionStorage}) + document.cookie")
        assert "eyJ" not in stored and "payinsight_refresh" not in stored, f"token visible to JS: {stored[:80]}"
    j9()

    new_email = f"priya.{uuid.uuid4().hex[:6]}@e2e.payinsight.test"
    new_pwd = "Settle-Up#2026"

    @step("J10 sign up a new account (VIEWER) and see it in Account & Security")
    def j10():
        page.get_by_title("Sign out").click()
        page.get_by_test_id("tab-signup").click()
        page.get_by_label("Full name").fill("Priya Sharma")
        page.get_by_label("Email").fill(new_email)
        page.get_by_label("Password", exact=True).fill("short")
        expect(page.get_by_role("button", name="Create account").last).to_be_disabled()
        page.get_by_label("Password", exact=True).fill(new_pwd)
        page.screenshot(path=OUT / "10_signup.png")
        page.get_by_role("button", name="Create account").last.click()
        expect(page.get_by_text("Payments overview")).to_be_visible(timeout=15000)
        expect(page.locator("header").get_by_text("VIEWER")).to_be_visible()
        page.get_by_role("button", name="Account & Security").click()
        expect(page.get_by_test_id("sessions-table").get_by_text("This device")).to_be_visible(timeout=10000)
        page.screenshot(path=OUT / "10_account_sessions.png", full_page=True)
    j10()

    admin_ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    admin_page = admin_ctx.new_page()

    @step("J11 admin promotes the new user; role applies without re-login")
    def j11():
        login(admin_page, "admin@payinsight.demo")
        admin_page.get_by_role("button", name="Users & Audit").click()
        admin_page.get_by_label(f"Role for {new_email}").select_option("ANALYST")
        expect(admin_page.get_by_text(f"{new_email} is now ANALYST.")).to_be_visible(timeout=10000)
        expect(admin_page.get_by_test_id("audit-table").get_by_text("USER_UPDATED").first).to_be_visible()
        admin_page.screenshot(path=OUT / "11_admin_users_audit.png", full_page=True)
        ask(page, "Compare payment success rates by bank")  # same browser session as before the promotion
        expect(page.get_by_text("Deccan Commercial Bank").first).to_be_visible(timeout=20000)
    j11()

    @step("J12 admin disables the user; their open session is ended")
    def j12():
        row = admin_page.locator(f"tr[data-email='{new_email}']")
        row.get_by_role("button", name="Disable").click()
        expect(admin_page.get_by_text(f"{new_email} disabled and signed out.")).to_be_visible(timeout=10000)
        page.get_by_role("button", name="Dashboard").click()
        expect(page.get_by_text("Your session ended")).to_be_visible(timeout=15000)
        page.locator("form").get_by_role("button", name="Sign in").wait_for()
        page.get_by_label("Email").fill(new_email)
        page.get_by_label("Password", exact=True).fill(new_pwd)
        page.locator("form").get_by_role("button", name="Sign in").click()
        expect(page.get_by_text("disabled by an administrator")).to_be_visible(timeout=10000)
        page.screenshot(path=OUT / "12_disabled.png")
    j12()
    admin_ctx.close()
    browser.close()


def cleanup_e2e_users() -> None:
    """Remove accounts created by J10-J12 from the dev database so demos stay clean (audit rows are kept)."""
    import sqlite3
    db = Path(__file__).resolve().parents[3] / "data" / "app.db"
    if not db.exists():
        return
    with sqlite3.connect(db) as c:
        ids = [r[0] for r in c.execute("SELECT user_id FROM users WHERE email LIKE '%@e2e.payinsight.test'")]
        for uid in ids:
            c.execute("DELETE FROM auth_sessions WHERE user_id = ?", (uid,))
            c.execute("DELETE FROM analysis_history WHERE user_id = ?", (uid,))
            c.execute("DELETE FROM users WHERE user_id = ?", (uid,))
    print(f"cleaned up {len(ids)} e2e test account(s)")


cleanup_e2e_users()

width = max(len(r[0]) for r in results)
for name, status, secs, err in results:
    print(f"{name.ljust(width)}  {status}  {secs:5.1f}s  {err}")
print(f"screenshots: {OUT}")
sys.exit(0 if all(r[1] == "PASS" for r in results) else 1)
