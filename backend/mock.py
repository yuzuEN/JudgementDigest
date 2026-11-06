"""
示例資料：功能還沒有接上真正的模型或資料時回傳這些（回應裡 mock = true，前端會標示「示例資料」）。
  - 刑事：刑事組的模型完成前
  - 民事：伺服器上沒有 artifacts/（例如 CI、剛 clone 下來的組員）
字號一律用 ○○○，不放真實案件。
"""
from typing import Dict, List

from backend.quality import win_signal
from civil.insights import DEFENSES, EVIDENCE

MOCK_OPTIONS = {
    "mid_groups": [
        {"category": "侵權", "mids": [{"value": "侵權：交通事故", "n": 0}, {"value": "侵權：其他", "n": 0}]},
        {"category": "民間借貸", "mids": [{"value": "民間借貸", "n": 0}]},
        {"category": "契約", "mids": [{"value": "契約：買賣", "n": 0}, {"value": "契約：工程與承攬", "n": 0}]},
        {"category": "勞動", "mids": [{"value": "勞動：工資與加班費", "n": 0}]},
    ],
    "courts": ["臺北", "新北", "臺中", "高雄"],
}

_MOCK_CASES = [
    ("機車直行遭右轉汽車撞擊，骨折住院", "一部勝訴一部敗訴", 480_000, 310_000, 0.62),
    ("路口碰撞，請求醫療費與工作損失", "勝訴", 220_000, 220_000, 0.58),
    ("轉彎車未禮讓直行機車", "一部勝訴一部敗訴", 650_000, 400_000, 0.55),
    ("雙方各有過失，原告未能證明薪資損失", "敗訴", 300_000, 0, 0.51),
    ("請求精神慰撫金與看護費", "一部勝訴一部敗訴", 500_000, 180_000, 0.49),
]


def civil_cases(mid: str = "侵權：交通事故") -> List[Dict]:
    return [{"source": "civil", "case_id": -(i + 1), "case_number": "臺灣○○地方法院 ○○○ 年度訴字第 ○○○ 號",
             "court": "臺灣○○地方法院", "year": "○○○", "mid": mid or "侵權：交通事故", "outcome": outcome,
             "similarity": sim, "summary": f"（示例）{summary}", "claimed_amount": claimed, "awarded_amount": awarded}
            for i, (summary, outcome, claimed, awarded, sim) in enumerate(_MOCK_CASES)]


def civil_report(text: str, claimed: int = None, user_evidence=()) -> Dict:
    # 示例的機率隨描述長度變一點，讓前端看得出「有在算」，但數字本身沒有意義
    p = round(min(0.8, 0.45 + len(text) / 5000), 2)
    have = set(user_evidence)
    shares = [0.82, 0.74, 0.61, 0.35, 0.33]
    keys = ["medical", "receipt", "accident", "chat", "salary"]
    labels = {k: label for k, label, _ in EVIDENCE}
    defense = {k: (label, desc) for k, label, desc, _ in DEFENSES}
    amount = None
    if claimed:
        amount = {"n_cases": 30, "ratio_low": 0.36, "ratio_median": 0.6, "ratio_high": 0.84, "coverage": 0.8, "buckets": [{"low": round(i * 0.2, 1), "high": round(i * 0.2 + 0.2, 1), "count": c} for i, c in enumerate((2, 6, 11, 8, 3))],
                  "claimed": claimed, "amount_low": round(claimed * 0.36), "amount_median": round(claimed * 0.6),
                  "amount_high": round(claimed * 0.84)}
    return {
        "prediction": {"win_probability": p, "signal": win_signal(p, text), "warnings": [], "mock": True,
                       "model": {"name": "mock", "description": "示例資料（伺服器上沒有模型檔）"}},
        "amount_range": amount,
        "similar": civil_cases(),
        "evidence": [{"key": k, "label": labels[k], "share": s, "user_has": k in have} for k, s in zip(keys, shares)],
        "defenses": [{"key": k, "label": defense[k][0], "description": defense[k][1], "share": s}
                     for k, s in (("contributory", 0.46), ("excessive", 0.38), ("paid", 0.21))],
        "outcomes": {"total": 30, "win": 8, "partial": 13, "lose": 9},
        "n_compared": 30,
        "mock": True,
    }


_BUCKETS = ["拘役、罰金", "1～6 個月", "7～12 個月", "1～3 年", "3～10 年", "10 年以上"]


def criminal_report() -> Dict:
    charges = [("過失傷害罪", "刑法第 284 條", 0.71, [0.38, 0.41, 0.14, 0.05, 0.02, 0.0]),
               ("過失致重傷罪", "刑法第 284 條後段", 0.18, [0.06, 0.35, 0.33, 0.21, 0.05, 0.0]),
               ("肇事逃逸罪", "刑法第 185 條之 4", 0.06, [0.02, 0.30, 0.41, 0.22, 0.05, 0.0])]
    similar = [{"source": "criminal", "case_id": -(i + 1), "case_number": f"臺灣○○地方法院 ○○○ 年度{kind}字第 ○○○ 號",
                "court": "臺灣○○地方法院", "year": "○○○", "mid": "過失傷害", "outcome": "有罪", "similarity": sim,
                "summary": "（示例）駕車未注意車前狀況，致被害人受傷", "sentence": sentence}
               for i, (kind, sentence, sim) in enumerate((("交簡", "拘役 30 日，得易科罰金", 0.64),
                                                         ("交易", "有期徒刑 3 月，得易科罰金", 0.59),
                                                         ("交簡", "有期徒刑 2 月，緩刑 2 年", 0.52)))]
    return {"charges": [{"name": n, "law": law, "probability": p,
                         "sentence": [{"label": b, "share": s} for b, s in zip(_BUCKETS, dist)]}
                        for n, law, p, dist in charges],
            "similar": similar, "mock": True}


def guide(case: Dict) -> Dict:
    paragraphs = [
        ("claim", "原告主張：被告駕駛自用小客車於路口右轉時，未禮讓直行之原告機車，致原告受有右手骨折等傷害。"),
        ("defense", "被告則以：原告行經路口時車速過快，對事故之發生與有過失；請求之金額亦屬過高等語，資為抗辯。"),
        ("issue", "本件爭點為：（一）被告就本件事故有無過失？原告是否與有過失？（二）原告得請求賠償之項目及金額為何？"),
        ("evidence", "經查，原告提出之診斷證明書記載其受有右手橈骨骨折，另有交通事故初步分析研判表在卷可稽。"),
        ("court", "本院審酌上開證據，認被告右轉未禮讓直行車，有過失；原告亦與有過失，應負擔百分之二十之過失責任。"),
    ]
    labels = {"claim": "原告主張", "defense": "被告答辯", "issue": "爭點", "evidence": "證據", "court": "法院判斷"}
    return {"case": case, "labeler": "mock", "mock": True,
            "paragraphs": [{"function": f, "label": labels[f], "text": "（示例）" + t} for f, t in paragraphs]}
