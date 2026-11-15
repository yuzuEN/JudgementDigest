"""Opt-in real-model + browser smoke: python -m tests.model_smoke (not offline discovery)."""
import json
import math
import os
import socket
import subprocess
import sys
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CRIMINAL = "被告飲用啤酒後仍騎乘機車上路，經警攔查，吐氣酒精濃度達每公升零點四毫克。"
CIVIL = "被告駕車未注意前方車況，撞傷原告，原告支出醫療費用並無法工作，請求被告賠償損害。" * 4


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def wait_ready(url, process):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Smoke server exited; see backend/frontend smoke log")
        try:
            with urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            pass
        time.sleep(0.5)
    raise TimeoutError(url)


class RealModelSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        artifacts = Path(os.environ["JD_ARTIFACTS_DIR"]).resolve()
        cls.revision = json.loads((artifacts / "smoke-revision.json").read_text())
        api_port, ui_port = free_port(), free_port()
        cls.url = "http://127.0.0.1:" + str(ui_port)
        api_url = "http://127.0.0.1:" + str(api_port)
        env = dict(os.environ, JD_ARTIFACTS_DIR=str(artifacts), JD_BACKEND_MODE="auto",
                   JD_LLM_PROVIDER="", GEMINI_API_KEY="", OPENAI_API_KEY="", VITE_API_PROXY=api_url)
        for name, command, cwd, url in [
            ("backend", [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(api_port)], ROOT, api_url + "/api/health"),
            ("frontend", ["npm", "run", "preview", "--", "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"], ROOT / "frontend", cls.url),
        ]:
            log = cls.stack.enter_context((artifacts / (name + "-smoke.log")).open("w"))
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            cls.stack.callback(stop, process)
            wait_ready(url, process)
        cls.pw = cls.stack.enter_context(sync_playwright())
        cls.browser = cls.pw.chromium.launch()
        cls.stack.callback(cls.browser.close)

    def test_health_uses_all_real_models(self):
        with urlopen(self.url + "/api/health", timeout=30) as response:
            health = json.load(response)
        self.assertEqual(health["status"], "ok")
        for key in ("civil", "criminal", "amount"):
            self.assertEqual(health[key], "model", (key, health))
        self.assertEqual(health["criminal_sentence"], "electra", health)

    def test_results_render_real_predictions(self):
        from playwright.sync_api import expect

        for kind, text, endpoint, tab in [
            ("criminal", CRIMINAL, "/api/criminal/predict", "刑期範圍"),
            ("civil", CIVIL, "/api/civil/report", "可能的金額"),
        ]:
            with self.subTest(kind=kind):
                page = self.browser.new_page()
                try:
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    intake = {"caseType": kind, "text": text, "maskedText": text, "claimedAmount": "100000", "mids": ["侵權：交通事故"] if kind == "civil" else [], "sensitiveConsent": True}
                    page.add_init_script("sessionStorage.setItem('casey-intake-v1', " + json.dumps(json.dumps(intake)) + ");")
                    with page.expect_response(lambda response: response.url.endswith(endpoint) and response.request.method == "POST", timeout=120000) as pending:
                        page.goto(self.url + "/result/" + kind)
                    response = pending.value
                    self.assertEqual(response.status, 200)
                    report = response.json()
                    self.assertFalse(report["mock"])
                    self.assertTrue(report["similar"], "Real retrieval must return cases")
                    expect(page.get_by_role("heading", name="刑事參考結果" if kind == "criminal" else "民事參考結果：侵權：交通事故", exact=True)).to_be_visible()
                    if kind == "criminal":
                        self.assertTrue(report["charges"])
                        charge = report["charges"][0]
                        self.assertTrue(0 <= charge["probability"] <= 1)
                        sentence = charge["sentence"]
                        self.assertEqual(len(sentence), 6)
                        self.assertTrue(all(math.isfinite(item["share"]) and 0 <= item["share"] <= 1 for item in sentence))
                        self.assertAlmostEqual(sum(item["share"] for item in sentence), 1, places=3)
                        self.assertEqual(report["model"]["sentence_description"], "法律 ELECTRA")
                        expect(page.get_by_text(charge["name"], exact=True).first).to_be_visible()
                    else:
                        self.assertTrue(0 <= report["prediction"]["win_probability"] <= 1)
                        self.assertEqual(report["amount_range"]["source"], "model")
                    page.get_by_role("tab", name=tab, exact=True).click()
                    expect(page.get_by_role("tab", name=tab, exact=True)).to_have_attribute("aria-selected", "true")
                    self.assertEqual(errors, [])
                finally:
                    page.close()


if __name__ == "__main__":
    program = unittest.main(verbosity=2, exit=False)
    artifacts = Path(os.environ["JD_ARTIFACTS_DIR"])
    revision = json.loads((artifacts / "smoke-revision.json").read_text())
    (artifacts / "smoke-result.json").write_text(json.dumps({"revision": revision, "passed": program.result.wasSuccessful()}, indent=2))
    sys.exit(0 if program.result.wasSuccessful() else 1)
