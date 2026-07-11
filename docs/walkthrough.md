# Stock Predictor — 구현 완료 워크스루

## 프로젝트 위치

```
/Users/gyurimyeon/.gemini/antigravity/scratch/stock_predictor/
```

> [!TIP]
> 이 디렉토리를 워크스페이스로 설정하시면 작업이 편리합니다.

---

## 생성된 파일 구조

```
stock_predictor/
├── stock_predictor.py              # 메인 진입점 (CLI + 파이프라인 오케스트레이터)
├── requirements.txt                # 의존성 목록
└── modules/
    ├── __init__.py                 # 패키지 초기화 (모든 클래스 re-export)
    ├── data_collector.py           # 주가 데이터 수집 + 네이버 뉴스 크롤링
    ├── sentiment_analyzer.py       # KR-FinBert-SC 기반 감성 분석
    ├── preprocessor.py             # 기술적 지표 생성 + 데이터 병합
    ├── trainer.py                  # XGBoost 학습 + 모델 직렬화
    └── predictor.py                # 학습된 모델 기반 추론
```

---

## 모듈별 주요 클래스 및 역할

| 파일 | 클래스 | 역할 |
|------|--------|------|
| [data_collector.py](file:///Users/gyurimyeon/.gemini/antigravity/scratch/stock_predictor/modules/data_collector.py) | `StockDataCollector` | FinanceDataReader로 일별 주가 수집, 종목명↔코드 변환 |
| [data_collector.py](file:///Users/gyurimyeon/.gemini/antigravity/scratch/stock_predictor/modules/data_collector.py) | `NaverNewsCrawler` | 네이버 뉴스 검색 크롤링 (월별 분할, 차단 방지) |
| [sentiment_analyzer.py](file:///Users/gyurimyeon/.gemini/antigravity/scratch/stock_predictor/modules/sentiment_analyzer.py) | `SentimentAnalyzer` | HuggingFace KR-FinBert-SC 감성 분석, 일별 점수 집계 |
| [preprocessor.py](file:///Users/gyurimyeon/.gemini/antigravity/scratch/stock_predictor/modules/preprocessor.py) | `DataPreprocessor` | MA/RSI/MACD/볼린저밴드 등 기술적 지표, 데이터 병합 |
| [trainer.py](file:///Users/gyurimyeon/.gemini/antigravity/scratch/stock_predictor/modules/trainer.py) | `ModelTrainer` | XGBoost 회귀+분류 학습, joblib 직렬화 |
| [predictor.py](file:///Users/gyurimyeon/.gemini/antigravity/scratch/stock_predictor/modules/predictor.py) | `StockPredictor` | 저장된 모델 로드, API-ready dict 예측 반환 |
| [stock_predictor.py](file:///Users/gyurimyeon/.gemini/antigravity/scratch/stock_predictor/stock_predictor.py) | `StockPredictionPipeline` | 전체 파이프라인 오케스트레이션 |

---

## 검증 결과

### 구문 검증
- ✅ 모든 7개 Python 파일 AST 파싱 통과
- ✅ 모든 모듈 임포트 정상 동작
- ✅ CLI `--help` 정상 출력

### 단위 테스트
- ✅ **기술적 지표 계산**: MA5, MA20, RSI(0~100), MACD, 볼린저밴드 정상
- ✅ **데이터 병합**: 주가+감성 left join, 결측치 중립 처리 정상
- ✅ **모델 학습**: XGBoost 회귀(MAE 291)/분류(Accuracy 0.6) 정상
- ✅ **모델 직렬화**: 4개 파일(regressor, classifier, scaler, metadata) 저장 확인
- ✅ **예측 반환 형식**: 요구된 dict 형태 정확히 반환

### 예측 결과 형식 (검증 통과)
```json
{
  "ticker": "TEST001",
  "target_date": "2024-05-20",
  "predicted_trend": "상승",
  "predicted_price": 65106,
  "trend_probability": 0.6234,
  "avg_sentiment_score": 0.0,
  "model_metrics": { ... },
  "predicted_at": "2026-06-29T08:57:58.123456"
}
```

---

## 실행 방법

### 1. 의존성 설치
```bash
cd /Users/gyurimyeon/.gemini/antigravity/scratch/stock_predictor
pip install -r requirements.txt
```

> [!NOTE]
> `transformers`와 `torch`는 감성 분석 모델(KR-FinBert-SC)에 필요합니다.
> 최초 실행 시 모델 다운로드에 약 500MB의 디스크 공간이 필요합니다.

### 2. 전체 파이프라인 실행
```bash
# 삼성전자 2024년 데이터로 학습 + 예측
python stock_predictor.py --stock "삼성전자" --year 2024

# 종목코드로 실행
python stock_predictor.py --stock "005930" --year 2024

# 상세 로그 출력
python stock_predictor.py --stock "삼성전자" --year 2024 --verbose
```

### 3. 기존 모델로 예측만 수행
```bash
python stock_predictor.py --stock "005930" --year 2024 --skip-train
```

### 4. 결과를 JSON 파일로 저장
```bash
python stock_predictor.py --stock "삼성전자" --year 2024 --output result.json
```

---

## FastAPI 확장 예시

`StockPredictionPipeline` 클래스는 웹 서버에서 직접 사용 가능합니다:

```python
from fastapi import FastAPI
from stock_predictor import StockPredictionPipeline

app = FastAPI()
pipeline = StockPredictionPipeline()

@app.get("/predict/{stock}")
async def predict(stock: str, year: int = 2024):
    result = pipeline.run(stock, year)
    return result  # 이미 dict → 자동 JSON 변환
```
