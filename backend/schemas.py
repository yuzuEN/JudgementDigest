"""API 的輸入輸出格式。前端的 frontend/src/api/types.ts 和這裡一一對應，改了要一起改。"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

CaseType = Literal["civil", "criminal", "unsure"]
DefendantType = Literal["person", "company", "government"]


class Health(BaseModel):
    status: str
    civil: Literal["model", "mock"]
    criminal: Literal["mock"]
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
    fallback: Optional[Literal["not_dispute", "error", "limited"]] = None   # 要求用 LLM 卻改用固定題庫的原因


class CivilInput(BaseModel):
    text: str = Field(min_length=1, max_length=20000, description="遮名後的案情描述")
    mid: Optional[str] = Field(default=None, description="案由中類，例：侵權：交通事故")
    court: Optional[str] = Field(default=None, description="法院簡稱，例：臺北；不知道就留空")
    plaintiff_has_lawyer: Optional[bool] = None
    defendant_type: Optional[DefendantType] = None
    claimed_amount: Optional[int] = Field(default=None, ge=0)
    evidence: List[str] = Field(default_factory=list, description="使用者有的證據（options.evidence 的 key）")


class ModelInfo(BaseModel):
    name: str
    description: str
    auc: Optional[float] = None
    ece: Optional[float] = None


class CivilPrediction(BaseModel):
    win_probability: float
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


class CivilReport(BaseModel):
    prediction: CivilPrediction
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
    probability: float
    sentence: List[SentenceBucket]


class CriminalReport(BaseModel):
    charges: List[Charge]
    similar: List[SimilarCase]
    mock: bool


class GuideParagraph(BaseModel):
    function: Literal["claim", "defense", "issue", "evidence", "court"]
    label: str
    text: str


class Guide(BaseModel):
    case: SimilarCase
    paragraphs: List[GuideParagraph]
    labeler: str
    mock: bool
