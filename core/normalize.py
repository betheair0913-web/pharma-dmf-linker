"""성분명 정규화 파이프라인.

식약처 DMF API(INGR_KOR_NAME)와 완제의약품 허가 API(MAIN_ITEM_INGR)의
성분 표기는 띄어쓰기/괄호/염·수화물 표기가 제각각이라 원문 그대로는 조인되지 않는다.
여기서 두 종류의 키를 만든다.

- norm_ingredient_key : 염/수화물 표기까지 살린 정밀 키 (EXACT 매칭용)
- norm_base_key       : 염/수화물/에스터를 떼어낸 골격 키 (BASE 매칭용)

두 키를 모두 저장해 두고 조인 단계에서 매칭 레벨을 구분한다.
"""

from __future__ import annotations

import re
import unicodedata

# 정규화 규칙 버전.
# norm_ingredient_key 는 finished_drug_master 의 기본키 일부라, 규칙이 바뀌면
# 기존 행이 새 키와 매칭되지 않아 고아 레코드로 남는다(예: 'l멘톨' vs '엘멘톨').
# 규칙을 손대면 이 값을 올려라. 다음 수집 때 마스터가 자동으로 재계산된다.
NORMALIZER_VERSION = "2"

# ---------------------------------------------------------------------------
# 1. 표기 이명(Synonym) 사전 - 같은 성분의 다른 한글 표기를 하나로 모은다.
# ---------------------------------------------------------------------------
KOR_SYNONYMS: dict[str, str] = {
    "비타민씨": "아스코르브산",
    "비타민c": "아스코르브산",
    "비타민비1": "티아민",
    "비타민b1": "티아민",
    "비타민비2": "리보플라빈",
    "비타민b2": "리보플라빈",
    "비타민비6": "피리독신",
    "비타민b6": "피리독신",
    "비타민비12": "시아노코발라민",
    "비타민b12": "시아노코발라민",
    "비타민디3": "콜레칼시페롤",
    "비타민d3": "콜레칼시페롤",
    "비타민이": "토코페롤",
    "비타민e": "토코페롤",
    "아세트아미노펜": "파라세타몰",
    "포도당": "글루코스",
    "무수결정포도당": "글루코스",
    "백당": "수크로스",
    "정제백당": "수크로스",
    "유당": "락토스",
    "결정셀룰로오스": "미결정셀룰로스",
    "결정셀룰로스": "미결정셀룰로스",
    "미결정셀룰로오스": "미결정셀룰로스",
}

# ---------------------------------------------------------------------------
# 2. 염(Salt) / 수화물(Hydrate) / 에스터 접미 표기.
#    길이 내림차순으로 지워야 "염산염"이 "염산"보다 먼저 걸린다.
# ---------------------------------------------------------------------------
_SALT_TOKENS: list[str] = [
    "브롬화수소산염", "브롬화수소산", "요오드화수소산염", "질산염", "인산수소염", "인산이수소염",
    "인산염", "황산수소염", "황산염", "염산염", "염화물", "탄산수소염", "탄산염",
    "메탄술폰산염", "메탄설폰산염", "메실산염", "메시레이트", "에실산염", "에탄술폰산염",
    "베실산염", "베실레이트", "벤젠술폰산염", "토실산염", "토실레이트",
    "캄실산염", "캄포술폰산염", "말레산염", "말레인산염", "푸마르산염", "숙신산염", "호박산염",
    "타르타르산염", "주석산염", "시트르산염", "구연산염", "락트산염", "젖산염",
    "글루콘산염", "아세트산염", "초산염", "옥살산염", "말산염", "사과산염", "팔미트산염",
    "스테아르산염", "글루쿠론산염", "판토텐산염", "아스파르트산염", "니코틴산염", "오로트산염",
    "파모산염", "엠보산염", "살리실산염", "말론산염", "아디프산염", "아디핀산염", "벤조산염",
    "나트륨염", "소듐염", "칼륨염", "포타슘염", "칼슘염", "마그네슘염", "아연염", "알루미늄염",
    "리튬염", "암모늄염", "메글루민염", "트로메타몰염", "디에탄올아민염", "에탄올아민염",
    "리신염", "아르기닌염", "콜린염", "디올아민염",
    "일수화물", "이수화물", "삼수화물", "사수화물", "오수화물", "육수화물", "칠수화물",
    "팔수화물", "십수화물", "반수화물", "05수화물", "15수화물", "25수화물",
    "수화물", "무수물", "함수", "결정수", "에탄올화물",
    "에틸에스터", "메틸에스터", "이소프로필에스터", "헥실에스터", "발레레이트",
    "프로피오네이트", "아세토니드", "디프로피오네이트", "푸로에이트",
    "피발레이트", "부티레이트", "카프로에이트", "데카노에이트", "에나테이트", "운데실레네이트",
    "헤미푸마르산염", "세미푸마르산염",
]
# 단독으로는 성분 골격일 수 있으나 접미로 붙으면 염인 토큰 (뒤에서만 제거)
_SALT_SUFFIX_ONLY: list[str] = [
    "나트륨", "소듐", "칼륨", "포타슘", "칼슘", "마그네슘", "염산", "황산", "인산",
    "말레산", "푸마르산", "타르타르산", "주석산", "숙신산", "아세트산", "초산", "질산",
    "메글루민", "트로메타민", "트로메타몰", "베타덱스", "수화", "무수",
]
# 한국어 표기는 염을 앞에 붙이기도 한다 (말레인산암로디핀 = 암로디핀말레산염).
# 골격 키를 만들 때 선두의 산(酸) 표기도 떼어낸다.
#
# 목록은 의도적으로 보수적이다. 니코틴산아미드, 살리실산메틸처럼 산 이름이 화합물명의
# 일부인 성분을 잘라내면 안 되므로, 실제로 카운터이온으로만 쓰이는 산만 넣는다.
_SALT_PREFIX: list[str] = [
    "브롬화수소산", "메탄술폰산", "메탄설폰산", "벤젠술폰산", "타르타르산", "글루콘산",
    "말레인산", "시트르산", "아세트산", "옥살산", "구연산", "푸마르산",
    "숙신산", "말레산", "메실산", "베실산", "토실산", "캄실산", "락트산",
    "염산", "황산", "인산", "질산", "초산", "젖산", "주석산",
]
# 접두 제거 후 남으면 안 되는 조각. 이런 값이 남는다면 그 산 표기는 카운터이온이 아니라
# 화합물명의 일부였다는 뜻이므로 제거를 되돌린다 (니코틴산아미드 -> "아미드" 방지).
_NON_BASE_REMAINDER: frozenset[str] = frozenset({
    "아미드", "메틸", "에틸", "프로필", "부틸", "벤질", "페닐",
    "나트륨", "소듐", "칼륨", "포타슘", "칼슘", "마그네슘", "아연", "철",
    "암모늄", "콜린", "리신", "아르기닌", "에스터", "에스테르", "무수물", "수화물",
})
_SALT_TOKENS.sort(key=len, reverse=True)
_SALT_SUFFIX_ONLY.sort(key=len, reverse=True)
_SALT_PREFIX.sort(key=len, reverse=True)

# 광학이성질체 접두 표기 통일 (S-암로디핀 = 에스암로디핀).
# 라틴 문자 뒤에 한글이 바로 오는 경우에만 적용하므로 esomeprazole 류는 영향받지 않는다.
_STEREO_PREFIX: dict[str, str] = {"s": "에스", "r": "알", "d": "디", "l": "엘"}

# ---------------------------------------------------------------------------
# 3. 영문 성분명 정규화용 치환 (검색 보조 및 영문 키 생성)
# ---------------------------------------------------------------------------
ENG_SALT_MAP: dict[str, str] = {
    "hydrochloride": "hcl", "hydrochlorid": "hcl", "hcl": "hcl",
    "hydrobromide": "hbr", "sulphate": "sulfate", "sulfate": "sulfate",
    "besylate": "besylate", "besilate": "besylate",
    "mesylate": "mesylate", "mesilate": "mesylate", "methanesulfonate": "mesylate",
    "tosylate": "tosylate", "tosilate": "tosylate",
    "maleate": "maleate", "fumarate": "fumarate", "tartrate": "tartrate",
    "citrate": "citrate", "succinate": "succinate", "acetate": "acetate",
    "phosphate": "phosphate", "nitrate": "nitrate", "lactate": "lactate",
    "sodium": "na", "potassium": "k", "calcium": "ca", "magnesium": "mg",
    "anhydrous": "", "monohydrate": "", "dihydrate": "", "trihydrate": "",
    "hemihydrate": "", "hydrate": "",
}

# ---------------------------------------------------------------------------
# 정규식 (모듈 로드 시 1회 컴파일)
# ---------------------------------------------------------------------------
_RE_INGR_CODE = re.compile(r"^\s*\[[A-Za-z]?\d+\]\s*")
_RE_PAREN = re.compile(r"[(（\[{][^)）\]}]*[)）\]}]")
_RE_NON_KEY = re.compile(r"[^0-9a-z가-힣]")
_RE_ENG_NON_KEY = re.compile(r"[^0-9a-z]")
_RE_MULTI_WS = re.compile(r"\s+")
_RE_HAS_LETTER = re.compile(r"[가-힣a-zA-Z]")

# 주성분 문자열에 섞여 들어오는 서술 항목 (엑스제 총량 표기 등)
_NOISE_PATTERNS = (
    "이상", "건조엑스", "엑스로서", "총량", "함유", "별규", "혼합물로서",
    "환산량", "으로서", "생약엑스",
)


def strip_ingredient_code(raw: str) -> tuple[str, str]:
    """[M040004]갈근 -> (M040004, 갈근). 코드가 없으면 ("", 원문)."""
    if not raw:
        return "", ""
    m = _RE_INGR_CODE.match(raw)
    if not m:
        return "", raw.strip()
    code = m.group(0).strip().strip("[]")
    return code, raw[m.end():].strip()


def is_noise_ingredient(name: str) -> bool:
    """성분이 아닌 서술 토큰인지 판정 (예: 이상 건조엑스로서 1.32g)."""
    if not name:
        return True
    s = name.strip()
    if len(s) < 2:
        return True
    if not _RE_HAS_LETTER.search(s):
        return True
    return any(p in s for p in _NOISE_PATTERNS)


def _prepare(name: str) -> str:
    """공통 전처리: 유니코드 정규화 -> 코드 제거 -> 괄호 제거 -> 소문자화."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name))
    _, s = strip_ingredient_code(s)
    # 괄호 블록은 이명/규격 표기가 대부분이라 제거 (중첩 대비 2회)
    for _ in range(2):
        s = _RE_PAREN.sub(" ", s)
    return _RE_MULTI_WS.sub(" ", s).strip().lower()


def _unify_stereo_prefix(s: str) -> str:
    """'s암로디핀' -> '에스암로디핀'. 라틴 1글자 + 한글일 때만 치환한다."""
    if len(s) >= 2 and s[0] in _STEREO_PREFIX and "가" <= s[1] <= "힣":
        return _STEREO_PREFIX[s[0]] + s[1:]
    return s


def normalize_ingredient(name: str | None) -> str:
    """정밀 정규화 키. 염·수화물 표기는 유지한다 (EXACT 매칭용)."""
    s = _prepare(name or "")
    if not s:
        return ""
    s = _unify_stereo_prefix(_RE_NON_KEY.sub("", s))
    return KOR_SYNONYMS.get(s, s)


def normalize_ingredient_base(name: str | None) -> str:
    """골격 정규화 키. 염/수화물/에스터 접미를 반복 제거해 유효성분 골격만 남긴다.

    예: 암로디핀베실산염 -> 암로디핀, 세프트리악손나트륨수화물 -> 세프트리악손,
        말레인산암로디핀 -> 암로디핀
    """
    s = normalize_ingredient(name)
    if not s:
        return ""
    changed = True
    while changed and len(s) > 2:
        changed = False
        for tok in _SALT_TOKENS:
            if s.endswith(tok) and len(s) - len(tok) >= 2:
                s = s[: -len(tok)]
                changed = True
                break
        if changed:
            continue
        for tok in _SALT_SUFFIX_ONLY:
            if s.endswith(tok) and len(s) - len(tok) >= 3:
                s = s[: -len(tok)]
                changed = True
                break
        if changed:
            continue
        for tok in _SALT_PREFIX:
            if s.startswith(tok) and len(s) - len(tok) >= 3:
                remainder = _unify_stereo_prefix(s[len(tok):])
                if remainder in _NON_BASE_REMAINDER:
                    continue  # 산 이름이 화합물명의 일부였다 -> 자르지 않는다
                s = remainder
                changed = True
                break
    return KOR_SYNONYMS.get(s, s) or normalize_ingredient(name)


def normalize_ingredient_en(name: str | None) -> str:
    """영문 성분명 정규화 (표시/검색 보조용. 조인 키로는 쓰지 않음)."""
    s = _prepare(name or "")
    if not s:
        return ""
    out: list[str] = []
    for t in re.split(r"[\s\-_,]+", s):
        t = _RE_ENG_NON_KEY.sub("", t)
        if not t:
            continue
        out.append(ENG_SALT_MAP.get(t, t))
    return "".join(out)


def split_main_ingredients(main_item_ingr: str | None) -> list[tuple[str, str]]:
    """MAIN_ITEM_INGR을 (성분코드, 성분명) 목록으로 분해.

    형식: [M202821]겐타마이신황산염|[M223043]베타메타손발레레이트  (구분자 "|")
    엑스제의 "이상 건조엑스로서 ..." 같은 서술 항목은 걸러낸다.
    """
    if not main_item_ingr:
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for part in str(main_item_ingr).split("|"):
        part = part.strip()
        if not part:
            continue
        code, name = strip_ingredient_code(part)
        if is_noise_ingredient(name):
            continue
        key = normalize_ingredient(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((code, name))
    return out


def split_eng_ingredients(main_ingr_eng: str | None) -> list[str]:
    """MAIN_INGR_ENG를 "/" 기준으로 분해.

    주의: 이 API의 영문 성분 목록은 알파벳순으로 재정렬되어 있어
    MAIN_ITEM_INGR(한글)과 위치가 1:1 대응하지 않는다.
    복합제에서는 개별 성분과 짝지을 수 없고, 품목 단위 참고/검색용으로만 쓴다.
    """
    if not main_ingr_eng:
        return []
    return [p.strip() for p in str(main_ingr_eng).split("/") if p.strip()]
