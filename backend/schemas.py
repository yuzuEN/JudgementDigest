"""API 的輸入輸出格式。前端的 frontend/src/api/types.ts 和這裡一一對應，改了要一起改。"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

CaseType = Literal["civil", "criminal", "unsure"]
DefendantType = Literal["person", "company", "government"]


class Health(BaseModel):
    status: str
    civil: Literal["model", "mock"]
    criminal: Literal["model", "mock"]          # 罪名、法條、刑度、相似判決
    followup: Literal["rules", "llm"]
    model: Optional[str] = None


class Option(BaseModel):
    value: str
    n: int = 0


class MidGroup(BaseModel):
    category: str
    mids: List[Option]


class EvidenceOption(BaseModel):
    key: str
    label: str


class Options(BaseModel):
    mid_groups: List[MidGroup]
    courts: List[str]
    evidence: List[EvidenceOption]
    mock: bool


class MaskRequest(BaseModel):
    text: str = Field(max_length=20000)
    names: List[str] = Field(default_factory=list, description="使用者要另外遮的名字")


class MaskedSpan(BaseModel):
    start: int
    end: int
    kind: str
    label: str


class MaskResponse(BaseModel):
    masked_text: str
    spans: List[MaskedSpan]


class FollowupRequest(BaseModel):
    case_type: CaseType = "civil"
    mid: Optional[str] = None
    text: str = Field(default="", max_length=20000)
    allow_llm: bool = Field(default=False, description="使用者看過說明並按下按鈕才是 true；預設不傳給外部服務")


class Question(BaseModel):
    id: str
    text: str
    why: str
    skip_if: Optional[str] = None      # 描述符合這個規則時不用問（正規表達式）


class FollowupResponse(BaseModel):
    questions: List[Question]
    source: Literal["rules", "llm"]
    llm_available: bool = False
    llm_vendor: Optional[str] = Field(default=None, description="LLM 廠商名稱，前端的資料使用說明會寫出內容傳給誰")
    fallback: Optional[Literal["not_dispute", "error", "limited"]] = None   # 要求用 LLM 卻改用固定題庫的原因


class RewriteRequest(BaseModel):
    case_type: CaseType = "civil"
    mid: Optional[str] = None
    text: str = Field(min_length=1, max_length=20000, description="遮名後的案情描述")
    allow_llm: bool = Field(default=False, description="使用者看過說明並按下按鈕才是 true")


class RewriteResponse(BaseModel):
    text: Optional[str] = None
    source: Literal["llm", "none"]
    added_numbers: List[str] = Field(default_factory=list, description="改寫裡有、描述裡沒有的數字，要提醒使用者確認")
    fallback: Optional[Literal["no_llm", "not_dispute", "error", "limited"]] = None


class CivilInput(BaseModel):
    text: str = Field(min_length=1, max_length=20000, description="遮名後的案情描述")
    search_text: Optional[str] = Field(default=None, max_length=20000, description="使用者確認過的改寫，只用來搜尋相似判決")
    mid: Optional[str] = Field(default=None, description="案由中類，例：侵權：交通事故")
    court: Optional[str] = Field(default=None, description="法院簡稱，例：臺北；不知道就留空")
    plaintiff_has_lawyer: Optional[bool] = None
    defendant_type: Optional[DefendantType] = None
    claimed_amount: Optional[int] = Field(default=None, ge=0)
    evidence: List[str] = Field(default_factory=list, description="使用者有的證據（options.evidence 的 key）")


class ModelInfo(BaseModel):
    name: str
    description: str
    win_precision: Optional[float] = None
    win_recall: Optional[float] = None
    lose_precision: Optional[float] = None
    lose_recall: Optional[float] = None
    ece: Optional[float] = None


class CivilPrediction(BaseModel):
    win_probability: float
    signal: Literal["strong", "weak", "insufficient"]    # 結果頁的提示，規則見 quality.win_signal
    model: ModelInfo
    warnings: List[str]
    mock: bool


class AmountBucket(BaseModel):
    low: float
    high: float
    count: int


class AmountRange(BaseModel):
    n_cases: int
    ratio_low: float
    ratio_median: float
    ratio_high: float
    coverage: float
    claimed: Optional[int] = None
    amount_low: Optional[int] = None
    amount_median: Optional[int] = None
    amount_high: Optional[int] = None
    buckets: List[AmountBucket] = Field(default_factory=list, description="獲償比例每兩成一組的件數")


class SimilarCase(BaseModel):
    source: Literal["civil", "criminal"]
    case_id: int
    case_number: str
    court: str
    year: str
    mid: str
    outcome: str
    similarity: float
    summary: str
    claimed_amount: Optional[int] = None
    awarded_amount: Optional[int] = None
    sentence: Optional[str] = None
    default_judgment: bool = False      # 一造辯論：被告沒有到庭
    url: Optional[str] = None           # 刑事：司法院裁判書系統的原文網址（刑事判決沒有導讀）


class EvidenceRow(BaseModel):
    key: str
    label: str
    share: float
    user_has: bool


class DefenseRow(BaseModel):
    key: str
    label: str
    description: str
    share: float


class OutcomeCounts(BaseModel):
    total: int
    win: int
    partial: int
    lose: int


class CivilReport(BaseModel):
    prediction: CivilPrediction
    outcomes: OutcomeCounts
    default_cases: int = 0     # 最相似的 30 件（含一造辯論）裡，被告未到庭的件數
    amount_range: Optional[AmountRange]
    similar: List[SimilarCase]
    evidence: List[EvidenceRow]
    defenses: List[DefenseRow]
    n_compared: int
    mock: bool


class SearchRequest(BaseModel):
    type: Literal["civil", "criminal", "both"] = "civil"
    text: str = Field(min_length=1, max_length=20000)
    mid: Optional[str] = None
    k: int = Field(default=10, ge=1, le=50)


class SearchResponse(BaseModel):
    civil: List[SimilarCase]
    criminal: List[SimilarCase]
    mock: bool


class CriminalInput(BaseModel):
    text: str = Field(min_length=1, max_length=20000, description="遮名後的犯罪事實描述")


class SentenceBucket(BaseModel):
    label: str
    share: float


class Charge(BaseModel):
    name: str
    law: str
    law_note: Optional[str] = None                        # 修法換條號時註明舊條號
    probability: float
    sentence: List[SentenceBucket]                        # 罪名模型推估的刑度分布（6 區間，含拘役、罰金）
    similar_sentence: Optional[List[SentenceBucket]] = None   # 相似判決中同罪名案件的宣告刑分布
    n_similar: Optional[int] = None                       # similar_sentence 用了幾件判決


class CriminalModelInfo(BaseModel):
    name: str
    description: str
    n_test: Optional[int] = None
    charge_top1: Optional[float] = None                   # 第一個罪名猜中的比例
    bucket_accuracy: Optional[float] = None               # 刑度區間猜中的比例
    bucket_within_one: Optional[float] = None             # 刑度區間差一格以內的比例


class SentenceModel(BaseModel):
    name: str
    description: str


class SentenceDistribution(BaseModel):
    """ELECTRA 刑期模型（目前停用）的輸出：有期徒刑落在各區間的機率（只估有期徒刑，不含拘役、罰金）。"""
    buckets: List[SentenceBucket]
    mock: bool
    model: SentenceModel


class CriminalReport(BaseModel):
    sentence: Optional[SentenceDistribution] = None      # ELECTRA 刑期，目前停用、不回傳
    charges: List[Charge]
    similar: List[SimilarCase]
    model: Optional[CriminalModelInfo] = None
    mock: bool = Field(description="罪名、刑度與相似判決是否為示例資料")


class GuideParagraph(BaseModel):
    function: Literal["claim", "defense", "issue", "evidence", "court"]
    label: str
    text: str


class Guide(BaseModel):
    case: SimilarCase
    paragraphs: List[GuideParagraph]
    labeler: str
    mock: bool
