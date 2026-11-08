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
from backend.llm.base import LLMError  # noqa: E402
from backend.llm.fake import FakeClient  # noqa: E402
from backend.llm.gemini import DEFAULT_MODEL, GeminiClient  # noqa: E402
from backend.llm.limits import UsageLimiter  # noqa: E402
from backend.llm.tasks import (added_numbers, rewrite_claim, FOLLOWUP_SCHEMA, MAX_INPUT, MAX_QUESTION, SAFE_WHY,  # noqa: E402
                               followup_questions, outgoing)
from backend.main import create_app  # noqa: E402
from backend.settings import Settings  # noqa: E402

DISPUTE = "朋友跟我借了三十萬沒有還，他的電話是0912345678，住在臺北市大安區和平東路二段106號。"
GOOD = {"questions": [{"text": "有沒有寫借據？", "why": "可以確認借貸的經過。"}]}


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


class TestUsageLimiter(unittest.TestCase):
    def limiter(self, per_ip=2, per_day=5):
        self.now = 1_800_000_000.0
        return UsageLimiter(per_ip, per_day, clock=lambda: self.now)

    def test_per_ip_limit_and_recovery(self):
        limit = self.limiter()
        self.assertEqual([limit.allow("a") for _ in range(3)], [True, True, False])
        self.assertTrue(limit.allow("b"), "別的 IP 不受影響")
        self.now += 3601
        self.assertTrue(limit.allow("a"))

    def test_daily_limit_covers_all_ips(self):
        limit = self.limiter(per_ip=99, per_day=3)
        self.assertEqual([limit.allow(ip) for ip in "abcd"], [True, True, True, False])

    def test_new_day_resets(self):
        limit = self.limiter(per_ip=99, per_day=1)
        self.assertTrue(limit.allow("a"))
        self.assertFalse(limit.allow("b"))
        self.now += 86400
        self.assertTrue(limit.allow("b"))

    def test_rejected_calls_are_not_counted(self):
        limit = self.limiter(per_ip=1, per_day=2)
        limit.allow("a")
        for _ in range(5):
            limit.allow("a")
        self.assertTrue(limit.allow("b"), "被擋下的次數不算進每日上限")


class TestUsageLog(unittest.TestCase):
    def test_tokens_logged_without_content(self):
        def handler(request):
            r = gemini_reply(GOOD).json()
            r["usageMetadata"] = {"promptTokenCount": 11, "candidatesTokenCount": 22}
            return httpx.Response(200, json=r)

        with self.assertLogs("uvicorn.error", level="INFO") as logs:
            gemini(handler).generate_json("系統", "秘密案情", FOLLOWUP_SCHEMA)
        text = "\n".join(logs.output)
        self.assertIn("input=11", text)
        self.assertIn("output=22", text)
        self.assertNotIn("秘密案情", text)
        self.assertNotIn("secret-key", text)


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

    def test_input_is_limited(self):
        client = FakeClient(GOOD)
        followup_questions(client, "civil", None, "借錢" * MAX_INPUT)
        self.assertLess(len(client.sent[0]), MAX_INPUT + 100)

    def test_legal_claims_are_removed_from_the_explanation(self):
        claims = ["法院通常會核算零件折舊", "依民法第 184 條要負責", "法官會看這個", "這會影響責任比例",
                  "依法可以請求", "一般會判賠比較多"]
        for why in claims:
            reply = {"questions": [{"text": "有維修單據嗎？", "why": why}]}
            out = followup_questions(FakeClient(reply), "civil", None, DISPUTE)
            self.assertEqual(out[0]["why"], SAFE_WHY, why)

    def test_plain_explanation_is_kept(self):
        reply = {"questions": [{"text": "有維修單據嗎？", "why": "可以確認實際花了多少錢。"}]}
        out = followup_questions(FakeClient(reply), "civil", None, DISPUTE)
        self.assertEqual(out[0]["why"], "可以確認實際花了多少錢。")

    def test_shape_for_the_frontend(self):
        out = followup_questions(FakeClient(GOOD), "civil", None, DISPUTE)
        self.assertEqual(out, [{"id": "llm1", "text": "有沒有寫借據？", "why": "可以確認借貸的經過。"}])

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


class TestRewriteTask(unittest.TestCase):
    def test_text_is_masked_and_questions_removed(self):
        client = FakeClient({"claim": "原告主張被告借款三十萬元未還。"})
        rewrite_claim(client, "民間借貸", DISPUTE + "\n追問：對方怎麼說？\n回答：他說沒錢")
        self.assertNotIn("0912345678", client.sent[0])
        self.assertNotIn("追問", client.sent[0])
        self.assertIn("他說沒錢", client.sent[0])

    def test_result_is_masked(self):
        r = rewrite_claim(FakeClient({"claim": "原告電話0912345678，被告未還款。"}), None, DISPUTE)
        self.assertNotIn("0912345678", r["text"])

    def test_flags_numbers_that_are_not_in_the_description(self):
        self.assertEqual(added_numbers("去年五月到期", "民國112年5月到期"), ["112"])
        self.assertEqual(added_numbers("月租一萬四，押金兩萬八", "月租14,000元，押金新臺幣2萬8,000元"), [])
        self.assertEqual(added_numbers("月租一萬四，押金兩萬八", "月租14,000元，押金28,000元"), [])
        self.assertEqual(added_numbers("借七十五萬", "借款新臺幣75萬元"), [])
        self.assertEqual(added_numbers("月薪六萬八", "月薪6萬8千元"), [])

    def test_bad_results_fail(self):
        for reply in ({}, {"claim": ""}, {"claim": "長" * 5000}, "不是物件"):
            with self.assertRaises(LLMError):
                rewrite_claim(FakeClient(reply), None, DISPUTE)


class TestRewriteEndpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def client(self, fake, **settings):
        with mock.patch("backend.main.llm.create_client", return_value=fake):
            return TestClient(create_app(Settings(artifacts_dir=Path(self.tmp.name), **settings)))

    def rewrite(self, c, text=DISPUTE, allow_llm=True):
        return c.post("/api/intake/rewrite", json={"text": text, "allow_llm": allow_llm}).json()

    def test_rewrites_when_allowed(self):
        fake = FakeClient({"claim": "原告主張被告未還款。"})
        r = self.rewrite(self.client(fake))
        self.assertEqual((r["source"], r["text"]), ("llm", "原告主張被告未還款。"))

    def test_nothing_is_sent_without_permission(self):
        fake = FakeClient()
        r = self.rewrite(self.client(fake), allow_llm=False)
        self.assertEqual((r["source"], r["fallback"]), ("none", "no_llm"))
        self.assertEqual(fake.sent, [])

    def test_no_provider(self):
        r = self.rewrite(self.client(None))
        self.assertEqual(r["fallback"], "no_llm")

    def test_unrelated_text_is_not_sent(self):
        fake = FakeClient()
        r = self.rewrite(self.client(fake), "今天天氣很好")
        self.assertEqual(r["fallback"], "not_dispute")
        self.assertEqual(fake.sent, [])

    def test_failure_falls_back(self):
        r = self.rewrite(self.client(FakeClient(error=LLMError("逾時"))))
        self.assertEqual((r["source"], r["fallback"]), ("none", "error"))

    def test_shares_the_limit(self):
        fake = FakeClient({"claim": "原告主張。"})
        c = self.client(fake, llm_per_ip_hour=1)
        self.assertEqual([self.rewrite(c)["source"], self.rewrite(c)["fallback"]], ["llm", "limited"])


class TestEndpoint(unittest.TestCase):
    def client(self, fake=None, provider="fake", **limits):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch("backend.main.llm.create_client", return_value=fake):
            return TestClient(create_app(Settings(artifacts_dir=Path(tmp.name), llm_provider=provider, **limits)))

    def ask(self, client, text=DISPUTE, allow_llm=True):
        return client.post("/api/intake/followup", json={"case_type": "civil", "mid": "民間借貸", "text": text,
                                                         "allow_llm": allow_llm}).json()

    def test_nothing_leaves_without_explicit_permission(self):
        fake = FakeClient(GOOD)
        c = self.client(fake)
        r = self.ask(c, allow_llm=False)
        self.assertEqual((r["source"], r["llm_available"]), ("rules", True))
        r = c.post("/api/intake/followup", json={"case_type": "civil", "text": DISPUTE}).json()
        self.assertEqual(r["source"], "rules", "沒有寫 allow_llm 也不能傳")
        self.assertEqual(fake.sent, [])

    def test_llm_used_when_configured(self):
        c = self.client(FakeClient(GOOD))
        r = self.ask(c)
        self.assertEqual(r["source"], "llm")
        self.assertEqual(r["questions"][0]["id"], "llm1")
        self.assertEqual(c.get("/api/health").json()["followup"], "llm")

    def test_falls_back_to_rules_when_llm_fails(self):
        for error in (llm.LLMError("HTTP 402"), llm.LLMError("逾時")):
            r = self.ask(self.client(FakeClient(error=error)))
            self.assertEqual((r["source"], r["fallback"]), ("rules", "error"))
            self.assertGreater(len(r["questions"]), 0)

    def test_unrelated_text_does_not_spend_money(self):
        fake = FakeClient(GOOD)
        r = self.ask(self.client(fake), "今天天氣很好，我想去海邊走走。")
        self.assertEqual((r["source"], r["fallback"]), ("rules", "not_dispute"))
        self.assertEqual(fake.sent, [])

    def test_limit_stops_spending(self):
        fake = FakeClient(GOOD)
        c = self.client(fake, llm_per_ip_hour=2)
        results = [self.ask(c) for _ in range(3)]
        self.assertEqual([r["source"] for r in results], ["llm", "llm", "rules"])
        self.assertEqual(results[-1]["fallback"], "limited")
        self.assertEqual(len(fake.sent), 2)

    def test_limit_is_per_visitor(self):
        fake = FakeClient(GOOD)
        c = self.client(fake, llm_per_ip_hour=1)
        body = {"case_type": "civil", "text": DISPUTE, "allow_llm": True}
        sources = [c.post("/api/intake/followup", json=body, headers={"X-Real-IP": ip}).json()["source"]
                   for ip in ("1.1.1.1", "2.2.2.2", "1.1.1.1")]
        self.assertEqual(sources, ["llm", "llm", "rules"])

    def test_unrelated_text_does_not_use_the_quota(self):
        c = self.client(FakeClient(GOOD), llm_per_ip_hour=1)
        self.ask(c, "今天天氣很好")
        self.assertEqual(self.ask(c)["source"], "llm")

    def test_requests_without_permission_do_not_use_the_quota(self):
        c = self.client(FakeClient(GOOD), llm_per_ip_hour=1)
        self.ask(c, allow_llm=False)
        self.assertEqual(self.ask(c)["source"], "llm")

    def test_no_llm_by_default(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        c = TestClient(create_app(Settings(artifacts_dir=Path(tmp.name))))
        r = self.ask(c)
        self.assertEqual((r["source"], r["llm_available"]), ("rules", False))
        self.assertEqual(c.get("/api/health").json()["followup"], "rules")


class TestSettings(unittest.TestCase):
    def test_nginx_passes_the_visitor_ip(self):
        conf = (Path(__file__).resolve().parents[1] / "frontend" / "nginx.conf").read_text(encoding="utf-8")
        self.assertIn("X-Real-IP $remote_addr", conf)

    def test_limits_from_environment(self):
        env = {"JD_LLM_PER_IP_HOUR": "3", "JD_LLM_PER_DAY": ""}
        with mock.patch.dict("os.environ", env), mock.patch("backend.settings.load_dotenv"):
            s = Settings.from_env()
        self.assertEqual((s.llm_per_ip_hour, s.llm_per_day), (3, 300))

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
