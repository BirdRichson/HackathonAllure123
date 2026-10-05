"""Классификация текста отчёта рабочего: что случилось (подтип) и к какой причине это относится.

Три уровня, от лучшего к запасному:
1. LLM (Groq/Gemini) — для свободного текста с формы, когда есть ключ и сеть (app/assistant/reports.py);
2. локальная модель TF-IDF + логистическая регрессия — работает всегда, без сети, за миллисекунды;
3. правила по ключевым словам — если модели нет.

Модель учится на корпусе синтетических отчётов (те же шаблоны, что у симулятора, с опечатками и сокращениями).
Честная проверка — на отдельном наборе фраз, написанных вручную (`backend/ml_train/report_holdout.csv`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from app.config import MODELS_DIR, plant_config
from app.sim.report_texts import TEMPLATES, make_report_text

# Подтип → причина по справочнику config/reasons.yaml
SUBTYPE_REASON = {
    "датчик": "breakdown",
    "цепь": "breakdown",
    "горелка": "breakdown",
    "калибровка": "breakdown",
    "фильтр": "consumables",
    "плановое ТО": "planned_maintenance",
    "микроостановка": "other",
}
SUBTYPE_LABEL = {
    "датчик": "сбой датчика",
    "цепь": "износ или обрыв цепи",
    "горелка": "сбой горелки печи",
    "калибровка": "сбой калибровки стенда",
    "фильтр": "засорение фильтра",
    "плановое ТО": "плановое ТО",
    "микроостановка": "микроостановка",
}
SUBTYPES = list(SUBTYPE_REASON)

# Запасной уровень: корни слов по подтипам (порядок важен — первое совпадение).
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("плановое ТО", ("планов", "по графику", "регламент", "обслуживан")),
    ("цепь", ("цеп", "звен", "звёздоч", "звездоч", "натяж")),
    ("фильтр", ("фильтр", "перепад", "сорн", "пыль", "вытяжк", "включени")),
    ("горелка", ("горелк", "печь", "печи", "розжиг", "температур")),
    ("калибровка", ("калибр", "замер", "эталон")),
    ("датчик", ("датчик", "энкодер", "сенсор", "не видит", "концевик")),
    ("микроостановка", ("коротк", "пару минут", "криво", "поправили")),
]

# Детали, которые стоит считать по повторам (для выводов о повторяющихся проблемах).
COMPONENTS: list[tuple[str, tuple[str, ...]]] = [
    ("разъём датчика", ("разъём", "разъем")),
    ("энкодер", ("энкодер",)),
    ("датчик присутствия кузова", ("присутствия", "не видит деталь")),
    ("датчик положения", ("положения",)),
    ("звено цепи", ("звен",)),
    ("натяжение цепи", ("натяж", "слетела")),
    ("звёздочка привода", ("звёздоч", "звездоч")),
    ("электрод розжига", ("электрод",)),
    ("фильтры потолка", ("потолк",)),
]


@dataclass
class Prediction:
    subtype: str
    reason: str
    confidence: float
    source: str                      # ml | rules | llm
    component: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {"subtype": self.subtype, "subtype_label": SUBTYPE_LABEL.get(self.subtype, self.subtype),
                "reason": self.reason, "confidence": round(self.confidence, 3), "source": self.source,
                "component": self.component, "note": self.note}


def report_text(description: str | None, actions: str | None = "") -> str:
    return " ".join(x.strip() for x in (description or "", actions or "") if x and x.strip())


def find_component(text: str) -> str:
    low = text.lower()
    for name, keys in COMPONENTS:
        if any(k in low for k in keys):
            return name
    return ""


def rules_predict(text: str) -> Prediction | None:
    low = " " + text.lower() + " "
    for subtype, keys in KEYWORDS:
        if any(k in low for k in keys):
            return Prediction(subtype, SUBTYPE_REASON[subtype], 0.6, "rules", find_component(text))
    if re.search(r"\bто\b", low):
        return Prediction("плановое ТО", "planned_maintenance", 0.55, "rules")
    return None


# ─────────────────────────────── корпус и модель ──────────────────────────────


def build_corpus(per_subtype: int = 500, seed: int = 7) -> tuple[list[str], list[str]]:
    """Синтетические отчёты по всем подтипам с разными названиями оборудования."""
    rng = np.random.default_rng(seed)
    names_by_type: dict[str, list[str]] = {}
    for e in plant_config()["equipment"]:
        names_by_type.setdefault(e["type"], []).append(e["name"])
    all_names = [n for v in names_by_type.values() for n in v]
    subtype_types = {"датчик": "robot", "цепь": "conveyor", "фильтр": "paint_booth", "горелка": "oven",
                     "калибровка": "test_stand"}
    texts, labels = [], []
    for subtype in TEMPLATES:
        pool = names_by_type.get(subtype_types.get(subtype, ""), all_names)
        n = 0
        while n < per_subtype:
            name = str(rng.choice(pool))
            r = make_report_text(subtype, name, SUBTYPE_REASON.get(subtype, "other"), rng)
            if not r["completed"]:
                continue
            texts.append(report_text(str(r["description"]), str(r["actions_taken"])))
            labels.append(subtype)
            n += 1
    return texts, labels


class ReportClassifier:
    """TF-IDF по словам и по буквенным n-граммам (устойчиво к опечаткам) + логистическая регрессия."""

    VERSION = 1

    def __init__(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline, make_union

        self.pipe = make_pipeline(
            make_union(
                TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, sublinear_tf=True),
                TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True),
            ),
            LogisticRegression(C=4.0, max_iter=3000),
        )

    def fit(self, texts: list[str], labels: list[str]) -> "ReportClassifier":
        self.pipe.fit([t.lower() for t in texts], labels)
        return self

    def predict_many(self, texts: list[str]) -> list[Prediction | None]:
        idx = [i for i, t in enumerate(texts) if t and t.strip()]
        out: list[Prediction | None] = [None] * len(texts)
        if not idx:
            return out
        proba = self.pipe.predict_proba([texts[i].lower() for i in idx])
        classes = self.pipe.classes_
        for k, i in enumerate(idx):
            j = int(np.argmax(proba[k]))
            sub = str(classes[j])
            out[i] = Prediction(sub, SUBTYPE_REASON[sub], float(proba[k][j]), "ml", find_component(texts[i]))
        return out

    def predict(self, text: str) -> Prediction | None:
        return self.predict_many([text])[0]


def _model_path():
    import sklearn

    return MODELS_DIR / f"report_clf_v{ReportClassifier.VERSION}_sk{sklearn.__version__}.joblib"


def train_classifier(save: bool = True) -> ReportClassifier:
    texts, labels = build_corpus()
    clf = ReportClassifier().fit(texts, labels)
    if save:
        try:
            import joblib

            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            joblib.dump(clf, _model_path())
        except OSError:
            pass
    return clf


@lru_cache(maxsize=1)
def get_classifier() -> ReportClassifier:
    """Модель с диска (если версия sklearn совпадает) или обучение заново — около секунды."""
    path = _model_path()
    if path.is_file():
        try:
            import joblib

            clf = joblib.load(path)
            if isinstance(clf, ReportClassifier):
                return clf
        except Exception:
            pass
    return train_classifier()


def classify(text: str) -> Prediction | None:
    """Локальная классификация: модель, а если её нет — правила."""
    if not text or not text.strip():
        return None
    try:
        return get_classifier().predict(text)
    except Exception:
        return rules_predict(text)


def classify_many(texts: list[str]) -> list[Prediction | None]:
    try:
        return get_classifier().predict_many(texts)
    except Exception:
        return [rules_predict(t) if t else None for t in texts]
