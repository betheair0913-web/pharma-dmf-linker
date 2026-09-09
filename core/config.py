"""애플리케이션 설정.

API 인증키는 아래 우선순위로 해석한다.
  1) SQLite app_setting 테이블 (동기화 화면에서 저장한 값)
  2) 환경변수 / .env 파일의 DATA_GO_KR_SERVICE_KEY
  3) 빈 문자열 (미설정 -> UI에서 입력 요구)

인증키는 소스에 하드코딩하지 않는다. .env 는 .gitignore 대상이다.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
EXPORT_DIR = BASE_DIR / "exports"
DB_PATH = DATA_DIR / "dmf_linker.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

# --- Open API 엔드포인트 ----------------------------------------------------
DMF_BASE_URL = "https://apis.data.go.kr/1471000/MdcDmfInfoService01"
DMF_OPERATION = "getMdcDmfList01"

DRUG_BASE_URL = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07"
DRUG_OPERATION = "getDrugPrdtPrmsnDtlInq06"

# --- 수집 튜닝 --------------------------------------------------------------
# 두 API 모두 numOfRows=500 까지 응답하는 것을 실측 확인했다 (1000은 실패).
PAGE_SIZE_DMF = 500
PAGE_SIZE_DRUG = 500
# 공공데이터포털 트래픽 제한을 감안한 동시 요청 수. 429/5xx 발생 시 낮춘다.
MAX_CONCURRENCY = 6
REQUEST_TIMEOUT = 90.0
MAX_RETRIES = 4

SETTING_KEY_API = "service_key"


def get_service_key() -> str:
    """저장된 인증키를 반환한다 (DB 우선, 없으면 환경변수)."""
    try:
        from .db import get_setting

        saved = get_setting(SETTING_KEY_API)
        if saved:
            return saved.strip()
    except Exception:
        # DB 초기화 전 호출될 수 있으므로 조용히 넘어간다.
        pass
    return (os.getenv("DATA_GO_KR_SERVICE_KEY") or "").strip()


def save_service_key(key: str) -> None:
    from .db import set_setting

    set_setting(SETTING_KEY_API, key.strip())
