"""
FastAPI 기반 주가 예측 API 서버 (main.py)

stock_predictor.py의 StockPredictionPipeline을 HTTP API로 노출합니다.
Flutter 앱 등 외부 클라이언트에서 JSON 기반 HTTP 통신으로 호출할 수 있습니다.

엔드포인트:
    GET  /predict            동기 예측 (파이프라인 완료까지 대기, 응답 반환)
    POST /predict/async      비동기 예측 (즉시 task_id 반환, 백그라운드 실행)
    GET  /predict/status/{id} 비동기 작업 상태 조회 및 결과 수신
    GET  /health             서버 헬스체크
    GET  /stocks             지원 종목 목록 조회

실행:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Flutter 호출 예시:
    GET http://localhost:8000/predict?stock=삼성전자
    GET http://localhost:8000/predict?stock=005930&year=2024&skip_train=true
"""

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ─── 프로젝트 경로 설정 ─────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from stock_predictor import StockPredictionPipeline
from modules.data_collector import KOREAN_STOCK_MAP

# ─── 로깅 설정 ──────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.WARNING)
logging.getLogger("xgboost").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ─── FastAPI 앱 초기화 ──────────────────────────────────────
app = FastAPI(
    title="Stock Predictor API",
    description=(
        "뉴스 감성 분석 + 기술적 지표 기반 주가 예측 API.\n"
        "KR-FinBert-SC 감성 분석 모델과 XGBoost를 활용하여 "
        "다음 거래일의 주가를 예측합니다."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS 설정 (Flutter 웹/앱 호출 허용) ────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 프로덕션에서는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 파이프라인 싱글턴 ──────────────────────────────────────
# 서버 시작 시 1회 초기화, 모든 요청에서 공유
pipeline: Optional[StockPredictionPipeline] = None


# ─── 비동기 작업 저장소 ─────────────────────────────────────
class TaskStatus(str, Enum):
    """비동기 예측 작업의 상태"""
    PENDING = "pending"       # 대기 중
    RUNNING = "running"       # 실행 중
    COMPLETED = "completed"   # 완료
    FAILED = "failed"         # 실패


# 인메모리 작업 저장소 (프로덕션에서는 Redis 등으로 교체)
task_store: Dict[str, Dict[str, Any]] = {}


# ─── 라이프사이클 이벤트 ────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    """
    서버 시작 시 StockPredictionPipeline을 초기화합니다.
    감성 분석 모델(KR-FinBert-SC)은 첫 예측 요청 시 lazy 로드됩니다.
    """
    global pipeline
    logger.info("=" * 50)
    logger.info("Stock Predictor API 서버 시작")
    logger.info("=" * 50)

    try:
        pipeline = StockPredictionPipeline(model_dir="models")
        logger.info("파이프라인 초기화 완료")
    except Exception as e:
        logger.error(f"파이프라인 초기화 실패: {e}")
        raise


# ─── 헬스체크 ───────────────────────────────────────────────
@app.get(
    "/health",
    tags=["시스템"],
    summary="서버 상태 확인",
    response_description="서버 상태 및 파이프라인 준비 여부",
)
async def health_check():
    """
    서버 상태를 확인합니다.
    Flutter 앱에서 서버 연결 상태를 확인할 때 사용합니다.
    """
    return {
        "status": "healthy",
        "pipeline_ready": pipeline is not None,
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
    }


# ─── 지원 종목 목록 ────────────────────────────────────────
@app.get(
    "/stocks",
    tags=["정보"],
    summary="지원 종목 목록 조회",
    response_description="한글 종목명 매핑 딕셔너리에 등록된 종목 목록",
)
async def list_supported_stocks():
    """
    한글 종목명으로 검색 가능한 종목 목록을 반환합니다.
    목록에 없는 종목은 6자리 종목코드로 직접 입력할 수 있습니다.
    """
    stocks = []
    seen_codes = set()
    for name, info in KOREAN_STOCK_MAP.items():
        if info["code"] not in seen_codes:
            stocks.append({
                "name": name,
                "code": info["code"],
                "ticker": info["ticker"],
                "market": info["market"],
            })
            seen_codes.add(info["code"])

    return {
        "count": len(stocks),
        "stocks": stocks,
        "note": "목록에 없는 종목은 6자리 종목코드(예: 005930) 또는 yfinance 티커(예: 005930.KS)로 입력 가능합니다.",
    }


# ─── 동기 예측 엔드포인트 ───────────────────────────────────
@app.get(
    "/predict",
    tags=["예측"],
    summary="주가 예측 (동기)",
    response_description="예측 결과 JSON (파이프라인 완료까지 대기)",
)
async def predict_sync(
    stock: str = Query(
        ...,
        description='종목명 또는 종목코드 (예: "삼성전자", "005930", "005930.KS")',
        examples=["삼성전자", "005930", "AAPL"],
    ),
    year: int = Query(
        default=datetime.now().year,
        description="학습 대상 연도 (미지정 시 오늘 기준 최근 1년 자동 분석)",
        ge=2000,
        le=2030,
    ),
    skip_train: bool = Query(
        default=False,
        description="True이면 기존 학습된 모델로 예측만 수행 (학습 건너뜀)",
    ),
):
    """
    주가 예측 파이프라인을 실행하고 결과를 반환합니다.

    **주의**: 최초 실행 시 뉴스 크롤링 + 감성 분석 + 모델 학습에
    수 분이 소요될 수 있습니다. `skip_train=true`로 기존 모델을 사용하면
    응답이 빠릅니다.

    **Flutter 호출 예시**:
    ```
    GET http://localhost:8000/predict?stock=삼성전자
    GET http://localhost:8000/predict?stock=005930&year=2024&skip_train=true
    ```
    """
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="파이프라인이 아직 초기화되지 않았습니다. 잠시 후 다시 시도해주세요.",
        )

    try:
        # CPU-bound 파이프라인을 별도 스레드에서 실행 (이벤트 루프 블로킹 방지)
        result = await asyncio.to_thread(
            pipeline.run,
            stock_input=stock,
            year=year,
            skip_train=skip_train,
        )
        return JSONResponse(content=_serialize_result(result))

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"학습된 모델을 찾을 수 없습니다. skip_train=false로 먼저 학습을 수행해주세요. ({e})",
        )
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"필수 라이브러리가 설치되지 않았습니다: {e}",
        )
    except Exception as e:
        logger.error(f"예측 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"예측 중 오류가 발생했습니다: {str(e)}",
        )


# ─── 비동기 예측 엔드포인트 ─────────────────────────────────
@app.post(
    "/predict/async",
    tags=["예측"],
    summary="주가 예측 (비동기)",
    response_description="작업 ID 반환 (결과는 /predict/status/{task_id}에서 조회)",
)
async def predict_async(
    stock: str = Query(
        ...,
        description='종목명 또는 종목코드',
        examples=["삼성전자", "005930"],
    ),
    year: int = Query(default=datetime.now().year, ge=2000, le=2030),
    skip_train: bool = Query(default=False),
):
    """
    예측 작업을 백그라운드에서 시작하고 즉시 task_id를 반환합니다.

    파이프라인 실행에 수 분이 걸리므로, Flutter 앱에서 타임아웃 없이
    결과를 받으려면 이 엔드포인트를 사용하세요.

    **Flutter 호출 흐름**:
    1. `POST /predict/async?stock=삼성전자` → `task_id` 수신
    2. `GET /predict/status/{task_id}` → 주기적 폴링 (2~5초 간격)
    3. `status == "completed"` 시 `result` 필드에서 예측 결과 획득
    """
    if pipeline is None:
        raise HTTPException(status_code=503, detail="파이프라인 미초기화")

    task_id = str(uuid.uuid4())

    task_store[task_id] = {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "stock": stock,
        "year": year,
        "skip_train": skip_train,
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
        "result": None,
        "error": None,
    }

    # 백그라운드 태스크 시작
    asyncio.create_task(_run_prediction_task(task_id, stock, year, skip_train))

    return {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "message": "예측 작업이 시작되었습니다. /predict/status/{task_id}에서 결과를 확인하세요.",
        "poll_url": f"/predict/status/{task_id}",
    }


@app.get(
    "/predict/status/{task_id}",
    tags=["예측"],
    summary="비동기 예측 작업 상태 조회",
    response_description="작업 상태 및 완료 시 예측 결과",
)
async def predict_status(task_id: str):
    """
    비동기 예측 작업의 현재 상태를 조회합니다.

    **응답 status 값**:
    - `pending`: 대기 중
    - `running`: 실행 중 (크롤링, 감성분석, 학습 진행)
    - `completed`: 완료 (result 필드에 예측 결과 포함)
    - `failed`: 실패 (error 필드에 오류 메시지 포함)
    """
    if task_id not in task_store:
        raise HTTPException(
            status_code=404,
            detail=f"작업을 찾을 수 없습니다: {task_id}",
        )

    task = task_store[task_id]

    response = {
        "task_id": task["task_id"],
        "status": task["status"],
        "stock": task["stock"],
        "year": task["year"],
        "created_at": task["created_at"],
        "completed_at": task["completed_at"],
    }

    if task["status"] == TaskStatus.COMPLETED:
        response["result"] = task["result"]
    elif task["status"] == TaskStatus.FAILED:
        response["error"] = task["error"]

    return response


# ─── 백그라운드 작업 실행 함수 ──────────────────────────────
async def _run_prediction_task(
    task_id: str, stock: str, year: int, skip_train: bool
) -> None:
    """
    백그라운드에서 예측 파이프라인을 실행합니다.

    작업 진행 상태를 task_store에 업데이트하며,
    완료 또는 실패 시 결과/에러를 저장합니다.
    """
    task_store[task_id]["status"] = TaskStatus.RUNNING
    logger.info(f"[Task {task_id[:8]}] 백그라운드 예측 시작: {stock} ({year}년)")

    try:
        result = await asyncio.to_thread(
            pipeline.run,
            stock_input=stock,
            year=year,
            skip_train=skip_train,
        )

        task_store[task_id]["status"] = TaskStatus.COMPLETED
        task_store[task_id]["result"] = _serialize_result(result)
        task_store[task_id]["completed_at"] = datetime.now().isoformat()

        logger.info(f"[Task {task_id[:8]}] 예측 완료: {stock}")

    except Exception as e:
        task_store[task_id]["status"] = TaskStatus.FAILED
        task_store[task_id]["error"] = str(e)
        task_store[task_id]["completed_at"] = datetime.now().isoformat()

        logger.error(f"[Task {task_id[:8]}] 예측 실패: {e}", exc_info=True)


# ─── 유틸리티 ───────────────────────────────────────────────
def _serialize_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    예측 결과 딕셔너리를 JSON 직렬화 가능한 형태로 변환합니다.

    numpy/pandas 타입을 Python 기본 타입으로 변환합니다.
    """
    import numpy as np

    def convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [convert(i) for i in obj]
        return obj

    return convert(result)


# ─── 에러 핸들러 ────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """처리되지 않은 예외에 대한 글로벌 핸들러"""
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "서버 내부 오류가 발생했습니다.",
            "error": str(exc),
            "timestamp": datetime.now().isoformat(),
        },
    )


# ─── 직접 실행 시 ───────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
