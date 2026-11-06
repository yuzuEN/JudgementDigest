"""
類案判決參考平台的 API 伺服器。

    uvicorn backend.main:app --reload            # 在 repo 根目錄執行；文件在 http://127.0.0.1:8000/docs

所有路徑都在 /api 底下。刑事模型、LLM 追問、段落功能標註還沒完成的部分先回傳示例資料或規則式的結果，
回應裡的 mock、source、labeler 會說明是哪一種，前端據此標示「示例資料」。
"""
import logging
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from backend import followup, llm, mock, schemas
from backend.civil_service import CivilService
from backend.criminal_service import CriminalService
from backend.llm.limits import UsageLimiter
from backend.llm.tasks import followup_questions
from backend.quality import looks_like_dispute
from backend.settings import Settings
from retrieval.masking import TAGS, mask


logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    """nginx 會設定 X-Real-IP。後端只在 Docker 內網，外面的人碰不到，所以可以相信這個標頭。"""
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    civil = CivilService(settings.artifacts_dir, force_mock=settings.mode == "mock")
    criminal = CriminalService(settings.artifacts_dir, force_mock=settings.mode == "mock")
    llm_client = llm.create_client(settings.llm_provider, settings.llm_model, settings.llm_api_key)
    llm_limit = UsageLimiter(settings.llm_per_ip_hour, settings.llm_per_day)
    app = FastAPI(title="類案判決參考平台 API", version="0.1.0",
                  description="刑事及民事類案判決參考平台。結果是「類似案件如果打到判決」的統計參考，不是法律意見。")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"])
    api = APIRouter(prefix="/api")

    @api.get("/health", response_model=schemas.Health)
    def health():
        return {"status": "ok", "civil": "mock" if civil.mock else "model", "criminal": "mock" if criminal.mock else "model",
                "followup": "llm" if llm_client else "rules", "model": None if civil.mock else civil.meta["name"]}

    @api.get("/meta/options", response_model=schemas.Options)
    def options():
        """問卷的選項：糾紛類型（案由中類，依大類分組）、法院、證據。"""
        return civil.options()

    @api.post("/intake/mask", response_model=schemas.MaskResponse)
    def mask_text(req: schemas.MaskRequest):
        """遮掉身分證字號、電話、電子郵件、地址，以及使用者指定的名字。送到任何外部服務之前都要先經過這裡。"""
        text, spans = mask(req.text, req.names)
        return {"masked_text": text,
                "spans": [{"start": s.start, "end": s.end, "kind": s.kind, "label": TAGS[s.kind]} for s in spans]}

    @api.post("/intake/followup", response_model=schemas.FollowupResponse)
    def ask_followup(req: schemas.FollowupRequest, request: Request):
        """
        追問描述裡缺少的事實。預設用固定題庫，文字不離開伺服器。
        只有 allow_llm（使用者加好姓名、同意之後自己按按鈕）才傳給 LLM；失敗或內容不像法律糾紛時退回固定題庫。
        """
        available = llm_client is not None
        fallback = None
        if req.allow_llm and available and not looks_like_dispute(req.text):
            fallback = "not_dispute"
        elif req.allow_llm and available and not llm_limit.allow(client_ip(request)):
            fallback = "limited"
        elif req.allow_llm and available:
            try:
                return {"questions": followup_questions(llm_client, req.case_type, req.mid, req.text), "source": "llm",
                        "llm_available": True}
            except llm.LLMError as e:
                logger.warning("LLM 追問失敗，改用固定題庫：%s", e)
                fallback = "error"
        return {"questions": followup.questions(req.case_type, req.mid, req.text), "source": "rules",
                "llm_available": available, "fallback": fallback}

    @api.post("/civil/predict", response_model=schemas.CivilPrediction)
    def civil_predict(req: schemas.CivilInput):
        return civil.predict(req)

    @api.post("/civil/report", response_model=schemas.CivilReport)
    def civil_report(req: schemas.CivilInput):
        """結果頁需要的全部內容：勝訴機率、金額範圍、相似判決、證據對照、常見抗辯。"""
        return civil.report(req)

    @api.post("/criminal/predict", response_model=schemas.CriminalReport)
    def criminal_predict(req: schemas.CriminalInput):
        """刑事：罪名、法條、刑期分布、相似判決。沒有模型檔時回傳示例資料。"""
        return criminal.report(req.text)

    @api.post("/retrieval/search", response_model=schemas.SearchResponse)
    def search(req: schemas.SearchRequest):
        civil_cases = civil.search(req.text, req.mid, req.k) if req.type in ("civil", "both") else []
        criminal_cases = criminal.search(req.text, req.k) if req.type in ("criminal", "both") else []
        return {"civil": civil_cases, "criminal": criminal_cases,
                "mock": (civil.mock and req.type != "criminal") or (criminal.mock and req.type != "civil")}

    @api.get("/judgments/{source}/{case_id}/guide", response_model=schemas.Guide)
    def guide(source: str, case_id: int):
        """判決導讀：判決分成原告主張、被告答辯、爭點、證據、法院判斷。"""
        if source == "civil":
            result = civil.guide(case_id)
        elif source == "criminal":
            # 真的刑事判決沒有導讀（列表附司法院原文網址），只有示例資料有
            cases = {c["case_id"]: c for c in mock.criminal_report()["similar"]} if criminal.mock else {}
            result = mock.guide(cases[case_id]) if case_id in cases else None
        else:
            raise HTTPException(404, "source 只能是 civil 或 criminal")
        if result is None:
            raise HTTPException(404, "找不到這件判決")
        return result

    app.include_router(api)
    return app


_app = None


def __getattr__(name):
    # uvicorn 取 backend.main:app 時才建立（讀模型要幾秒）；測試只 import create_app，不會讀到正式的模型檔
    global _app
    if name == "app":
        if _app is None:
            try:
                _app = create_app()
            except AttributeError as e:
                # uvicorn 把這裡的 AttributeError 當成「模組裡沒有 app」，真正的原因會被蓋掉
                raise RuntimeError(f"建立 app 失敗：{e}") from e
        return _app
    raise AttributeError(name)
