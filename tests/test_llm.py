# -*- coding: utf-8 -*-
"""
backend/llm 的離線測試：不連線、不花錢。Gemini 用假的 HTTP 回應。
最重要的兩件事：送出去的文字一定遮過名；LLM 壞掉時網站照樣能用。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import llm  # noqa: E402
from backend.llm.fake import FakeClient  # noqa: E402
from backend.llm.gemini import DEFAULT_MODEL, GeminiClient  # noqa: E402
from backend.llm.tasks import FOLLOWUP_SCHEMA, MAX_QUESTION, followup_questions, outgoing  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.settings import Settings  # noqa: E402

DISPUTE = "朋友跟我借了三十萬沒有還，他的電話是0912345678，住在臺北市大安區和平東路二段106號。"
GOOD = {"questions": [{"text": "有沒有寫借據？", "why": "法院要看有沒有借貸的證明。"}]}


def gemini(handler):
    return GeminiClient("secret-key", "test-model", transport=httpx.MockTransport(handler))


def gemini_reply(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


class TestGemini(unittest.TestCase):
    def test_request_shape(self):
        seen = {}

        def handler(request):
            seen.update(url=str(request.url), key=request.headers["x-goog-api-key"], body=json.loads(request.content))
            return gemini_reply(GOOD)

        self.assertEqual(gemini(handler).generate_json("系統", "使用者", FOLLOWUP_SCHEMA), GOOD)
        self.assertTrue(seen["url"].endswith("/models/test-model:generateContent"))
        self.assertEqual(seen["key"], "secret-key")
        self.assertNotIn("secret-key", seen["url"], "key 不能放在網址")
        self.assertEqual(seen["body"]["systemInstruction"]["parts"][0]["text"], "系統")
        self.assertEqual(seen["body"]["contents"][0]["parts"][0]["text"], "使用者")
        self.assertEqual(seen["body"]["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(seen["body"]["generationConfig"]["responseJsonSchema"], FOLLOWUP_SCHEMA)

    def test_default_model(self):
        self.assertEqual(GeminiClient("k").model, DEFAULT_MODEL)

    def test_failures_become_llm_error_without_the_key(self):
        def timeout(request):
            raise httpx.ConnectTimeout("boom")

        for handler in (lambda r: httpx.Response(402, json={"error": "no credit"}),
                        lambda r: httpx.Response(429), timeout,
                        lambda r: httpx.Response(200, json={"candidates": []}),
                        lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
                        lambda r: gemini_reply("不是 JSON")):
            with self.assertRaises(llm.LLMError) as e:
                gemini(handler).generate_json("s", "u", {})
            self.assertNotIn("secret-key", str(e.exception))

    def test_error_status_is_never_treated_as_an_answer(self):
        body = gemini_reply(GOOD).json()
        with self.assertRaises(llm.LLMError):
            gemini(lambda r: httpx.Response(503, json=body)).generate_json("s", "u", {})


class TestCreateClient(unittest.TestCase):
    def test_not_configured(self):
        self.assertIsNone(llm.create_client(""))

    def test_providers(self):
        self.assertEqual(llm.create_client("fake").name, "fake")
        self.assertEqual(llm.create_client("gemini", "m", "k").model, "m")

    def test_mistakes_fail_at_startup(self):
        with self.assertRaises(RuntimeError):
            llm.create_client("gemini", "", "")
        with self.assertRaises(RuntimeError):
            llm.create_client("gpt")


class TestFollowupTask(unittest.TestCase):
    def test_text_is_masked_before_it_leaves(self):
        client = FakeClient(GOOD)
        followup_questions(client, "civil", "民間借貸", DISPUTE)
        self.assertNotIn("0912345678", client.sent[0])
        self.assertNotIn("和平東路", client.sent[0])
        self.assertIn("三十萬", client.sent[0])
        self.assertEqual(outgoing("電話0912345678"), "電話【電話】")

    def test_shape_for_the_frontend(self):
        out = followup_questions(FakeClient(GOOD), "civil", None, DISPUTE)
        self.assertEqual(out, [{"id": "llm1", "text": "有沒有寫借據？", "why": "法院要看有沒有借貸的證明。"}])

    def test_limit_and_bad_items_dropped(self):
        items = [{"text": "太長" * MAX_QUESTION, "why": "x"}, {"text": "", "why": "x"}, "不是物件"]
        items += [{"text": f"問題{i}", "why": "因為"} for i in range(6)]
        out = followup_questions(FakeClient({"questions": items}), "civil", None, DISPUTE, limit=8)
        self.assertEqual([q["text"] for q in out], [f"問題{i}" for i in range(5)])
        self.assertEqual([q["id"] for q in out], [f"llm{i}" for i in range(1, 6)])

    def test_unusable_results(self):
        for reply in ({"questions": []}, {"other": 1}, {"questions": "x"}, {"questions": [{"text": ""}]}):
            with self.assertRaises(llm.LLMError):
                followup_questions(FakeClient(reply), "civil", None, DISPUTE)


class TestEndpoint(unittest.TestCase):
    def client(self, fake=None, provider="fake"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch("backend.main.llm.create_client", return_value=fake):
            return TestClient(create_app(Settings(artifacts_dir=Path(tmp.name), llm_provider=provider)))

    def ask(self, client, text=DISPUTE):
        return client.post("/api/intake/followup", json={"case_type": "civil", "mid": "民間借貸", "text": text}).json()

    def test_llm_used_when_configured(self):
        c = self.client(FakeClient(GOOD))
        r = self.ask(c)
        self.assertEqual(r["source"], "llm")
        self.assertEqual(r["questions"][0]["id"], "llm1")
        self.assertEqual(c.get("/api/health").json()["followup"], "llm")

    def test_falls_back_to_rules_when_llm_fails(self):
        for error in (llm.LLMError("HTTP 402"), llm.LLMError("逾時")):
            r = self.ask(self.client(FakeClient(error=error)))
            self.assertEqual(r["source"], "rules")
            self.assertGreater(len(r["questions"]), 0)

    def test_unrelated_text_does_not_spend_money(self):
        fake = FakeClient(GOOD)
        r = self.ask(self.client(fake), "今天天氣很好，我想去海邊走走。")
        self.assertEqual(r["source"], "rules")
        self.assertEqual(fake.sent, [])

    def test_no_llm_by_default(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        c = TestClient(create_app(Settings(artifacts_dir=Path(tmp.name))))
        self.assertEqual(self.ask(c)["source"], "rules")
        self.assertEqual(c.get("/api/health").json()["followup"], "rules")


class TestSettings(unittest.TestCase):
    def test_key_not_in_repr(self):
        self.assertNotIn("abc123", repr(Settings(llm_api_key="abc123")))

    def test_reads_environment(self):
        env = {"JD_LLM_PROVIDER": " Gemini ", "JD_LLM_MODEL": "m", "GEMINI_API_KEY": "k"}
        with mock.patch.dict("os.environ", env), mock.patch("backend.settings.load_dotenv"):
            s = Settings.from_env()
        self.assertEqual((s.llm_provider, s.llm_model, s.llm_api_key), ("gemini", "m", "k"))

    def test_env_file_is_ignored_by_git(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn(".env", (root / ".gitignore").read_text(encoding="utf-8").splitlines())
        for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY"):
                self.assertEqual(line, "GEMINI_API_KEY=", "範本不能有真的 key")


if __name__ == "__main__":
    unittest.main()
