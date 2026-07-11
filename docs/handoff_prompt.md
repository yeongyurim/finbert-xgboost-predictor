# 📋 프로젝트 인수인계 프롬프트

## 프로젝트 개요
주가 예측 AI 시스템: **FastAPI 백엔드 + Flutter 프론트엔드**
- 사용자가 종목명(예: 삼성전자)을 입력하면, 최근 1년 뉴스 감성 분석 + 기술적 지표를 결합한 XGBoost 모델로 **내일 주가를 예측**
- 네이버 뉴스 수집을 **크롤링 → 공식 네이버 검색 API**로 방금 전환 완료 (아직 테스트 미완료)

---

## 프로젝트 경로

| 구성요소 | 경로 |
|---------|------|
| **백엔드 (Python/FastAPI)** | `/Users/gyurimyeon/Documents/git-repositories/stock_predictor/` |
| **프론트엔드 (Flutter)** | `/Users/gyurimyeon/Documents/git-repositories/stock_predictor_app/` |

---

## 핵심 파일 구조

### 백엔드 (`stock_predictor/`)
```
stock_predictor/
├── main.py                      # FastAPI 서버 (포트 8000)
├── stock_predictor.py           # 파이프라인 오케스트레이터
├── modules/
│   ├── data_collector.py        # ⭐ 방금 수정됨 — StockDataCollector(yfinance) + NaverNewsCrawler(API)
│   ├── sentiment_analyzer.py    # KR-FinBert-SC 감성 분석
│   ├── preprocessor.py          # 기술적 지표 생성 + 데이터 병합
│   ├── trainer.py               # XGBoost 회귀/분류 모델 학습
│   └── predictor.py             # 학습된 모델로 예측 수행
└── models/                      # 학습된 모델 파일 (.pkl) 저장 위치
```

### 프론트엔드 (`stock_predictor_app/`)
```
stock_predictor_app/
├── pubspec.yaml                 # 의존성: http, google_fonts, intl
└── lib/main.dart                # 전체 앱 코드 (터미널 감성 UI)
```

---

## 방금 완료한 작업 (테스트 필요)

### 1. 네이버 뉴스 크롤링 → 공식 API 전환
- **파일**: `modules/data_collector.py`의 `NaverNewsCrawler` 클래스
- **변경**: BeautifulSoup 웹 스크래핑 제거 → `https://openapi.naver.com/v1/search/news.json` REST API 사용
- **API 키**: Client ID = `w4W0lisnfIJWAcqO2SrZ`, Secret = `7Ehd00vKls` (하드코딩 + 환경변수 오버라이드 가능)
- **수집 전략**: 4가지 검색어(`{종목명} 주가`, `{종목명} 전망`, `{종목명} 실적`, `{종목명}`)로 각각 최대 1000건 페이지네이션 후 날짜 필터링
- **API 제한**: 일 25,000건, 요청당 최대 100건, start 최대 1000

### 2. 날짜 범위 변경: 고정 연도 → 오늘 기준 최근 1년
- **파일**: `stock_predictor.py` (Line ~166-185)
- `start_date = 오늘 - 365일`, `end_date = 오늘`로 자동 계산
- `main.py`의 year 기본값도 `datetime.now().year`로 변경됨
- Flutter `main.dart`에서 year 파라미터 제거 완료

---

## 테스트해야 할 것

### ✅ 즉시 테스트 (우선순위 높음)
```bash
# 1. 네이버 API 뉴스 수집 1년 분포 테스트
cd /Users/gyurimyeon/Documents/git-repositories/stock_predictor
python3 -c "
import sys; sys.path.insert(0, '.')
from modules.data_collector import NaverNewsCrawler
from datetime import datetime, timedelta

crawler = NaverNewsCrawler()
end = datetime.now().strftime('%Y-%m-%d')
start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
df = crawler.crawl_news('삼성전자', start_date=start, end_date=end)
print(f'총: {len(df)}건')
df['month'] = df['date'].dt.to_period('M')
print(df.groupby('month').size())
"
```

**주의**: API가 최신순(sort=date)으로 정렬하고 start 최대 1000이라, 과거 뉴스가 적을 수 있음.
만약 최근 2-3개월에만 편중되면 → 월별 쿼리 분할 방식으로 다시 변경해야 함.

### ✅ 전체 파이프라인 E2E 테스트
```bash
# 2. 파이프라인 전체 실행 (삼성전자, 최근 1년)
cd /Users/gyurimyeon/Documents/git-repositories/stock_predictor
python3 stock_predictor.py --stock "삼성전자"
```
- 기존 models/ 폴더에 이전 학습 모델이 있으므로 `--skip-train` 없이 실행하여 새로 학습
- F1 스코어가 0.069였던 것이 뉴스 데이터 증가로 개선되었는지 확인

### ✅ FastAPI + Flutter 통합 테스트
```bash
# 터미널 1: 서버
cd /Users/gyurimyeon/Documents/git-repositories/stock_predictor
python3 main.py

# 터미널 2: 앱
cd /Users/gyurimyeon/Documents/git-repositories/stock_predictor_app
flutter run -d chrome --web-port 3000
```

---

## 알려진 이슈 & 주의사항

1. **네이버 API 날짜 한계**: 검색 API는 date range 파라미터를 지원하지 않음. sort=date로 최신순 정렬 후 클라이언트 필터링만 가능. 따라서 1년 전 뉴스는 수집이 어려울 수 있음.

2. **모델 성능**: 이전 스크래핑에서는 54건 뉴스 → F1=0.069. API로 수백~수천 건 수집되면 F1 0.4~0.6 기대.

3. **감성 분석 모델**: `snunlp/KR-FinBert-SC` — HuggingFace에서 최초 로드 시 다운로드 필요 (~수분).

4. **Flutter Noto 폰트 경고**: `Could not find a set of Noto fonts` 경고가 나오지만 한글 표시에 문제없음.

5. **Android 에뮬레이터**: `main.dart`의 `kApiBaseUrl`을 `http://10.0.2.2:8000`으로 변경 필요.

---

## 기술 스택
- **백엔드**: Python 3.13, FastAPI, uvicorn, yfinance, XGBoost, KR-FinBert-SC (transformers)
- **프론트엔드**: Flutter 3.44.5, Dart 3.12.2, http 패키지, google_fonts
- **ML**: XGBRegressor (종가 예측) + XGBClassifier (상승/하락 분류)
- **피처**: MA(5,20,60), RSI, MACD, 볼린저 밴드, 거래량 변화율, 감성 스코어 등 23개
