# KIS API 기반 국내 주가 수집 분리 파이프라인

기존에는 모든 주식(국내/해외) 데이터를 `yfinance` 라이브러리로 수집했습니다. 이번 변경을 통해 **해외 주식은 기존대로 `yfinance`를 사용하고, 한국 주식(KOSPI, KOSDAQ)은 한국투자증권(KIS) API에서 수집**하도록 데이터 파이프라인을 이원화합니다.

## ⚠️ User Review Required
- **인증키 관리**: KIS API 호출에 필요한 `APP_KEY`와 `APP_SECRET`은 보안을 위해 `.env` 파일로 관리할 예정입니다.
- **모듈 설치**: 환경변수 처리를 위해 `python-dotenv` 및 HTTP 요청 처리를 위해 `requests` 패키지를 백엔드에 설치해야 합니다.

## ❓ Open Questions

> [!IMPORTANT]
> 구현을 시작하기 위해 다음 정보가 필요합니다:
> 
> 1. **한국투자증권(KIS) API 키 발급 여부**: `APP_KEY`와 `APP_SECRET`을 발급받으셨나요? 발급받으셨다면 `.env` 파일에 저장해야 하므로 저에게 채팅으로 알려주시면 제가 파일로 세팅해 드리겠습니다.
> 2. **실전투자 vs 모의투자**: 발급받으신 키가 실전투자용인가요, 모의투자(가상계좌)용인가요? (이에 따라 호출하는 API 주소가 다릅니다)
>    - 실전투자: `https://openapi.koreainvestment.com:9443`
>    - 모의투자: `https://openapivts.koreainvestment.com:29443`

---

## Proposed Changes

### 백엔드 (FastAPI & 데이터 모듈)

#### [MODIFY] [data_collector.py](file:///Users/gyurimyeon/Documents/git-repositories/stock_predictor/modules/data_collector.py)
`fetch_stock_data` 메서드를 다음과 같이 리팩토링합니다:
1. `ticker`가 `.KS`나 `.KQ`로 끝나거나 한국 주식으로 매핑된 경우 👉 `_fetch_kis_stock_data()` 호출
2. 그 외의 경우 (US 등) 👉 기존의 `yfinance` 기반 `_fetch_yfinance_stock_data()` 호출

**KIS API 연동 로직 (`_fetch_kis_stock_data`):**
- **인증(Token)**: `POST /oauth2/tokenP` 엔드포인트를 호출하여 Access Token 발급 및 캐싱
- **일별 주가 수집**: `GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice` (기간별 시세 조회) 호출
- **데이터 변환**: 응답받은 JSON 배열을 기존 파이프라인과 완벽히 호환되는 `pandas.DataFrame`(`Date, Open, High, Low, Close, Volume, Change`)으로 변환

#### [MODIFY] [stock_predictor.py](file:///Users/gyurimyeon/Documents/git-repositories/stock_predictor/stock_predictor.py)
`data_collector.fetch_stock_data()`를 호출할 때, 단순 티커 문자열뿐만 아니라 해당 종목이 한국 주식인지 판단할 수 있는 `market` 파라미터(KOSPI/KOSDAQ/US)도 함께 전달하도록 수정합니다.

#### [NEW] .env
프로젝트 루트 디렉토리에 `.env` 파일을 생성하고 다음 환경변수를 정의합니다:
```env
KIS_APP_KEY="사용자_키"
KIS_APP_SECRET="사용자_시크릿"
KIS_DOMAIN="https://openapi.koreainvestment.com:9443"
```

## Verification Plan

### Automated Tests
1. **국내 주식 (삼성전자)**: `stock_predictor.py`를 단독 실행하여 KIS API를 통해 주가 데이터가 성공적으로 1년 치 수집되는지 확인합니다.
2. **해외 주식 (AAPL)**: `stock_predictor.py`를 통해 해외 주식은 여전히 `yfinance`에서 문제없이 데이터를 받아오는지 확인합니다.

### Manual Verification
1. FastAPI 서버를 띄운 후 `/predict?stock=삼성전자` API를 호출합니다.
2. 로그에서 `[INFO] KIS API를 통한 주가 수집 (005930)` 메시지가 출력되는지 확인합니다.
3. 앱(Flutter)에서 화면이 정상적으로 출력되는지 확인합니다.
