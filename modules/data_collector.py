"""
데이터 수집 모듈 (Data Collection Module)

yfinance를 활용한 주가 데이터 수집과
네이버 검색 API 기반 뉴스 수집 기능을 제공합니다.

Classes:
    StockDataCollector: 종목 코드 해석 및 일별 주가 데이터 수집 (yfinance 기반)
    NaverNewsCrawler: 네이버 검색 API 기반 뉴스 수집 (공식 REST API)

Usage:
    >>> collector = StockDataCollector()
    >>> info = collector.resolve_ticker("삼성전자")
    >>> stock_df = collector.fetch_stock_data("005930.KS", "2024-01-01", "2024-12-31")

    >>> crawler = NaverNewsCrawler()
    >>> news_df = crawler.crawl_news("삼성전자", start_date="2025-07-01", end_date="2026-07-01")
"""

import time
import random
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import pandas as pd
import requests

try:
    import yfinance as yf
except ImportError:
    yf = None

logger = logging.getLogger(__name__)


# ─── 한국 주요 종목 매핑 딕셔너리 ─────────────────────────────
# 한글 종목명 → yfinance 티커 (KRX: .KS = KOSPI, .KQ = KOSDAQ)
# 사용자가 한글 이름을 입력할 경우 이 매핑을 통해 자동 변환합니다.
# 필요에 따라 종목을 추가하세요.
KOREAN_STOCK_MAP: Dict[str, Dict[str, str]] = {
    # ── KOSPI 대형주 ──
    "삼성전자": {"ticker": "005930.KS", "code": "005930", "market": "KOSPI"},
    "SK하이닉스": {"ticker": "000660.KS", "code": "000660", "market": "KOSPI"},
    "LG에너지솔루션": {"ticker": "373220.KS", "code": "373220", "market": "KOSPI"},
    "삼성바이오로직스": {"ticker": "207940.KS", "code": "207940", "market": "KOSPI"},
    "현대자동차": {"ticker": "005380.KS", "code": "005380", "market": "KOSPI"},
    "현대차": {"ticker": "005380.KS", "code": "005380", "market": "KOSPI"},
    "기아": {"ticker": "000270.KS", "code": "000270", "market": "KOSPI"},
    "셀트리온": {"ticker": "068270.KS", "code": "068270", "market": "KOSPI"},
    "KB금융": {"ticker": "105560.KS", "code": "105560", "market": "KOSPI"},
    "신한지주": {"ticker": "055550.KS", "code": "055550", "market": "KOSPI"},
    "POSCO홀딩스": {"ticker": "005490.KS", "code": "005490", "market": "KOSPI"},
    "포스코홀딩스": {"ticker": "005490.KS", "code": "005490", "market": "KOSPI"},
    "NAVER": {"ticker": "035420.KS", "code": "035420", "market": "KOSPI"},
    "네이버": {"ticker": "035420.KS", "code": "035420", "market": "KOSPI"},
    "카카오": {"ticker": "035720.KS", "code": "035720", "market": "KOSPI"},
    "삼성SDI": {"ticker": "006400.KS", "code": "006400", "market": "KOSPI"},
    "LG화학": {"ticker": "051910.KS", "code": "051910", "market": "KOSPI"},
    "현대모비스": {"ticker": "012330.KS", "code": "012330", "market": "KOSPI"},
    "삼성물산": {"ticker": "028260.KS", "code": "028260", "market": "KOSPI"},
    "SK이노베이션": {"ticker": "096770.KS", "code": "096770", "market": "KOSPI"},
    "SK텔레콤": {"ticker": "017670.KS", "code": "017670", "market": "KOSPI"},
    "KT": {"ticker": "030200.KS", "code": "030200", "market": "KOSPI"},
    "LG전자": {"ticker": "066570.KS", "code": "066570", "market": "KOSPI"},
    "한화에어로스페이스": {"ticker": "012450.KS", "code": "012450", "market": "KOSPI"},
    "두산에너빌리티": {"ticker": "034020.KS", "code": "034020", "market": "KOSPI"},
    "HD현대중공업": {"ticker": "329180.KS", "code": "329180", "market": "KOSPI"},
    "삼성전기": {"ticker": "009150.KS", "code": "009150", "market": "KOSPI"},
    "하이브": {"ticker": "352820.KS", "code": "352820", "market": "KOSPI"},
    "크래프톤": {"ticker": "259960.KS", "code": "259960", "market": "KOSPI"},
    # ── KOSDAQ 대형주 ──
    "에코프로비엠": {"ticker": "247540.KQ", "code": "247540", "market": "KOSDAQ"},
    "에코프로": {"ticker": "086520.KQ", "code": "086520", "market": "KOSDAQ"},
    "알테오젠": {"ticker": "196170.KQ", "code": "196170", "market": "KOSDAQ"},
    "HLB": {"ticker": "028300.KQ", "code": "028300", "market": "KOSDAQ"},
    "리가켐바이오": {"ticker": "141080.KQ", "code": "141080", "market": "KOSDAQ"},
    "엔켐": {"ticker": "348370.KQ", "code": "348370", "market": "KOSDAQ"},
}


class StockDataCollector:
    """
    주가 데이터 수집 클래스 (yfinance 기반)

    yfinance 라이브러리를 활용하여 Yahoo Finance에서
    일별 주가 데이터(시가, 종가, 고가, 저가, 거래량, 등락률)를 수집합니다.
    KRX 서버(data.krx.co.kr) 의존성을 완전히 제거하여
    서버 장애·크롤링 차단 문제를 회피합니다.

    한국 주식의 경우:
        - 6자리 종목코드 입력 → 자동으로 .KS(KOSPI) 접미사 추가
        - 한글 종목명 입력 → 내장 매핑 딕셔너리로 변환
        - 해외 주식(AAPL 등) → 그대로 사용

    Methods:
        resolve_ticker: 종목명/종목코드를 입력받아 표준화된 종목 정보 반환
        fetch_stock_data: 지정 기간의 일별 주가 데이터를 DataFrame으로 반환
    """

    def __init__(self):
        """StockDataCollector 초기화. yfinance 설치 여부를 확인합니다."""
        if yf is None:
            raise ImportError(
                "yfinance가 설치되지 않았습니다. "
                "pip install yfinance 로 설치해주세요."
            )

    def resolve_ticker(self, stock_input: str) -> Dict[str, str]:
        """
        종목명 또는 종목코드를 입력받아 yfinance 호환 티커 정보를 반환합니다.

        변환 규칙:
            1. 6자리 숫자 → 국내 종목으로 판단, .KS 접미사 추가 (KOSPI 기본)
            2. 한글 종목명 → KOREAN_STOCK_MAP 매핑 딕셔너리에서 검색
            3. 이미 .KS/.KQ 접미사가 포함된 티커 → 그대로 사용
            4. 영문 티커(AAPL 등) → 해외 종목으로 그대로 사용

        Args:
            stock_input: 종목명 (예: "삼성전자"), 종목코드 (예: "005930"),
                         또는 yfinance 티커 (예: "005930.KS", "AAPL")

        Returns:
            dict: 종목 정보 딕셔너리
                - ticker (str): yfinance 호환 티커 (예: "005930.KS")
                - name (str): 종목명
                - market (str): 소속 시장

        Raises:
            ValueError: 한글 종목명이 매핑 딕셔너리에 없는 경우
        """
        logger.info(f"종목 정보 조회: {stock_input}")
        stock_input = stock_input.strip()

        # Case 1: 6자리 숫자 → 국내 종목 (.KS 접미사 추가)
        if stock_input.isdigit() and len(stock_input) == 6:
            ticker = f"{stock_input}.KS"
            # 매핑 딕셔너리에서 이름 찾기
            name = stock_input
            market = "KOSPI"
            for k_name, info in KOREAN_STOCK_MAP.items():
                if info["code"] == stock_input:
                    name = k_name
                    ticker = info["ticker"]
                    market = info["market"]
                    break
            logger.info(f"  국내 종목 코드 감지: {stock_input} → {ticker} ({name})")
            return {"ticker": ticker, "name": name, "market": market}

        # Case 2: 한글 종목명 → 매핑 딕셔너리 검색
        if re.search(r"[가-힣]", stock_input):
            # 완전 일치 검색
            if stock_input in KOREAN_STOCK_MAP:
                info = KOREAN_STOCK_MAP[stock_input]
                logger.info(f"  매핑 완료: {stock_input} → {info['ticker']}")
                return {
                    "ticker": info["ticker"],
                    "name": stock_input,
                    "market": info["market"],
                }

            # 부분 일치 검색
            for k_name, info in KOREAN_STOCK_MAP.items():
                if stock_input in k_name or k_name in stock_input:
                    logger.info(f"  부분 일치: {stock_input} → {k_name} ({info['ticker']})")
                    return {
                        "ticker": info["ticker"],
                        "name": k_name,
                        "market": info["market"],
                    }

            # 매핑 실패
            available = ", ".join(sorted(KOREAN_STOCK_MAP.keys()))
            raise ValueError(
                f"'{stock_input}'에 대한 종목 매핑을 찾을 수 없습니다.\n"
                f"다음 중 하나를 시도해주세요:\n"
                f"  1. 6자리 종목코드를 직접 입력 (예: 005930)\n"
                f"  2. yfinance 티커를 직접 입력 (예: 005930.KS)\n"
                f"  3. 지원되는 종목명: {available}"
            )

        # Case 3: 이미 .KS/.KQ 접미사가 포함된 티커
        if stock_input.endswith((".KS", ".KQ")):
            code = stock_input.split(".")[0]
            market = "KOSPI" if stock_input.endswith(".KS") else "KOSDAQ"
            name = stock_input
            for k_name, info in KOREAN_STOCK_MAP.items():
                if info["ticker"] == stock_input:
                    name = k_name
                    break
            logger.info(f"  yfinance 티커 직접 입력: {stock_input}")
            return {"ticker": stock_input, "name": name, "market": market}

        # Case 4: 해외 주식 티커 (AAPL, MSFT 등)
        logger.info(f"  해외 종목 티커로 처리: {stock_input}")
        return {"ticker": stock_input, "name": stock_input, "market": "US"}

    def fetch_stock_data(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        yfinance를 통해 지정된 기간의 일별 주가 데이터를 수집합니다.

        Args:
            ticker: yfinance 호환 티커 (예: "005930.KS", "AAPL")
            start_date: 시작일 (예: "2024-01-01")
            end_date: 종료일 (예: "2024-12-31")

        Returns:
            pd.DataFrame: 일별 주가 데이터
                컬럼: Date, Open, High, Low, Close, Volume, Change
        """
        logger.info(f"주가 데이터 수집 시작 (yfinance): {ticker} ({start_date} ~ {end_date})")

        try:
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date, auto_adjust=True)
        except Exception as e:
            logger.error(f"yfinance 주가 데이터 수집 실패: {e}")
            raise

        if df.empty:
            logger.warning(f"수집된 주가 데이터가 없습니다: {ticker}")
            return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume", "Change"])

        # 인덱스(DatetimeIndex)를 Date 컬럼으로 변환
        df = df.reset_index()

        # yfinance는 컬럼명이 'Date' 또는 'Datetime'일 수 있음
        if "Datetime" in df.columns:
            df = df.rename(columns={"Datetime": "Date"})
        if "Date" not in df.columns:
            first_col = df.columns[0]
            df = df.rename(columns={first_col: "Date"})

        df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)

        # 등락률 계산 (yfinance는 Change 컬럼을 제공하지 않음)
        df["Change"] = df["Close"].pct_change()

        # 필수 컬럼 확인 및 정리
        required_cols = ["Date", "Open", "High", "Low", "Close", "Volume", "Change"]
        for col in required_cols:
            if col not in df.columns:
                logger.warning(f"누락된 컬럼: {col}, 0으로 채웁니다.")
                df[col] = 0

        df = df[required_cols].copy()
        df = df.sort_values("Date").reset_index(drop=True)

        logger.info(f"주가 데이터 수집 완료: {len(df)} 거래일")
        return df


class NaverNewsCrawler:
    """
    네이버 뉴스 검색 API 클래스 (공식 REST API 사용)

    네이버 Open API의 뉴스 검색 엔드포인트를 사용하여
    특정 종목의 뉴스 기사 제목을 수집합니다.

    웹 스크래핑과 달리 차단 위험이 없으며,
    JSON 응답을 직접 파싱하므로 안정적이고 빠릅니다.

    API 제한: 일 25,000건, 요청당 최대 100건, 시작 위치 최대 1000

    Attributes:
        client_id: 네이버 Open API Client ID
        client_secret: 네이버 Open API Client Secret
        max_results: 전체 최대 수집 건수 (기본: 1000)

    Methods:
        crawl_news: 뉴스 기사 제목 수집
    """

    NAVER_API_URL = "https://openapi.naver.com/v1/search/news.json"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        max_results: int = 1000,
        max_pages_per_month: int = 5,  # 하위 호환용 (무시됨)
    ):
        """
        NaverNewsCrawler 초기화

        Args:
            client_id: 네이버 Open API Client ID
                       (미지정 시 환경변수 NAVER_CLIENT_ID 사용)
            client_secret: 네이버 Open API Client Secret
                           (미지정 시 환경변수 NAVER_CLIENT_SECRET 사용)
            max_results: 전체 최대 수집 건수 (기본: 1000, API 한도)
            max_pages_per_month: 하위 호환을 위해 유지 (실제로 사용되지 않음)
        """
        import os
        self.client_id = (
            client_id
            or os.environ.get("NAVER_CLIENT_ID", "w4W0lisnfIJWAcqO2SrZ")
        )
        self.client_secret = (
            client_secret
            or os.environ.get("NAVER_CLIENT_SECRET", "7Ehd00vKls")
        )
        self.max_results = min(max_results, 1000)  # API 한도
        self.session = requests.Session()

    def crawl_news(
        self,
        stock_name: str,
        year: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        특정 종목의 뉴스 기사 제목을 수집합니다.

        네이버 검색 API로 뉴스를 검색한 후, 지정된 날짜 범위에
        해당하는 기사만 필터링하여 반환합니다.

        Args:
            stock_name: 종목명 (예: "삼성전자")
            year: 대상 연도 (예: 2024). start_date/end_date 미지정 시 사용
            start_date: 수집 시작일 (형식: "YYYY-MM-DD")
            end_date: 수집 종료일 (형식: "YYYY-MM-DD")

        Returns:
            pd.DataFrame: 수집된 뉴스 데이터
                컬럼: date (datetime), title (str)
        """
        # 날짜 범위 결정
        if start_date and end_date:
            dt_start = datetime.strptime(start_date, "%Y-%m-%d")
            dt_end = datetime.strptime(end_date, "%Y-%m-%d")
        elif year:
            dt_start = datetime(year, 1, 1)
            dt_end = datetime(year, 12, 31)
        else:
            dt_end = datetime.now()
            dt_start = dt_end - timedelta(days=365)

        logger.info(
            f"뉴스 수집 시작 (네이버 검색 API): '{stock_name}' "
            f"({dt_start.strftime('%Y-%m-%d')} ~ {dt_end.strftime('%Y-%m-%d')})"
        )

        all_news: List[Dict[str, str]] = []
        seen_titles = set()

        # ── 월별 분할 쿼리로 과거~현재 뉴스를 고르게 수집 (유사도순) ──
        current = dt_start.replace(day=1)
        while current <= dt_end:
            month_start = max(current, dt_start)
            if current.month == 12:
                month_end_dt = datetime(current.year, 12, 31)
            else:
                month_end_dt = datetime(current.year, current.month + 1, 1) - timedelta(days=1)
            month_end = min(month_end_dt, dt_end)

            # 검색어에 월 포함 + 유사도순(sim)으로 과거 기사 유도
            month_query = f"{stock_name} {current.year}년 {current.month}월"
            query_added = 0

            # 한 달에 최대 300건(3페이지) 정도만 수집 시도 (API 한도 절약)
            for start_pos in range(1, 301, 100):
                items, total = self._fetch_page(month_query, display=100, start=start_pos, sort="sim")
                if not items:
                    break

                for item in items:
                    pub_date = self._parse_pub_date(item.get("pubDate", ""))
                    if pub_date is None:
                        continue
                    
                    # 날짜가 해당 월에 속하는지 필터링 (정확도 향상)
                    if month_start <= pub_date <= month_end:
                        title = self._clean_title(item.get("title", ""))
                        if title and len(title) >= 10 and title not in seen_titles:
                            all_news.append({
                                "date": pub_date.strftime("%Y-%m-%d"),
                                "title": title,
                            })
                            seen_titles.add(title)
                            query_added += 1

                if start_pos + 100 > min(total, 1000):
                    break
                time.sleep(random.uniform(0.1, 0.2))

            logger.info(f"  {current.year}년 {current.month}월: {query_added}건 (누적 {len(all_news)}건)")

            # 다음 달로 이동
            if current.month == 12:
                current = datetime(current.year + 1, 1, 1)
            else:
                current = datetime(current.year, current.month + 1, 1)

        # ── 최신 뉴스 보충 (sort=date) ──
        # 과거 뉴스 수집 후 최근 트렌드를 정확히 반영하기 위해 최근 뉴스를 추가
        recent_added = 0
        for start_pos in range(1, 301, 100):
            items, total = self._fetch_page(f"{stock_name} 주가", display=100, start=start_pos, sort="date")
            if not items:
                break
            for item in items:
                pub_date = self._parse_pub_date(item.get("pubDate", ""))
                if pub_date is None:
                    continue
                if dt_start <= pub_date <= dt_end:
                    title = self._clean_title(item.get("title", ""))
                    if title and len(title) >= 10 and title not in seen_titles:
                        all_news.append({
                            "date": pub_date.strftime("%Y-%m-%d"),
                            "title": title,
                        })
                        seen_titles.add(title)
                        recent_added += 1
            if start_pos + 100 > min(total, 1000):
                break
            time.sleep(random.uniform(0.1, 0.2))
            
        logger.info(f"  최신 보충: {recent_added}건 (최종 누적 {len(all_news)}건)")

        if not all_news:
            logger.warning("수집된 뉴스가 없습니다.")
            return pd.DataFrame(columns=["date", "title"])

        df = pd.DataFrame(all_news)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        # 이미 set으로 걸렀지만 만약의 경우를 위해 중복 제거
        df = df.drop_duplicates(subset=["title"], keep="first").reset_index(drop=True)

        logger.info(f"뉴스 수집 완료: 총 {len(df)}건 (API)")
        return df

    def _fetch_page(
        self, query: str, display: int = 100, start: int = 1, sort: str = "date"
    ) -> tuple:
        """
        네이버 검색 API에서 뉴스 한 페이지를 가져옵니다.

        Args:
            query: 검색어
            display: 한 번에 가져올 결과 수 (최대 100)
            start: 시작 위치 (1~1000)
            sort: 정렬 방식 ('sim' 유사도순, 'date' 최신순)

        Returns:
            tuple: (items 리스트, total 검색 결과 수)
        """
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }
        params = {
            "query": query,
            "display": display,
            "start": start,
            "sort": sort,
        }

        try:
            resp = self.session.get(
                self.NAVER_API_URL,
                headers=headers,
                params=params,
                timeout=10,
            )

            if resp.status_code == 401:
                logger.error("네이버 API 인증 실패: Client ID/Secret을 확인하세요.")
                return [], 0
            elif resp.status_code == 429:
                logger.warning("네이버 API 요청 한도 초과, 1초 대기 후 재시도")
                time.sleep(1)
                resp = self.session.get(
                    self.NAVER_API_URL,
                    headers=headers,
                    params=params,
                    timeout=10,
                )

            resp.raise_for_status()
            data = resp.json()

            return data.get("items", []), data.get("total", 0)

        except requests.exceptions.RequestException as e:
            logger.warning(f"  API 요청 오류: {e}")
            return [], 0

    @staticmethod
    def _parse_pub_date(pub_date_str: str) -> Optional[datetime]:
        """
        네이버 API의 pubDate(RFC 822 형식)를 datetime으로 변환합니다.

        Args:
            pub_date_str: "Mon, 09 Jul 2026 12:00:00 +0900" 형식

        Returns:
            datetime 또는 None
        """
        if not pub_date_str:
            return None
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub_date_str)
            # timezone-aware → naive (다른 모듈과 호환)
            return dt.replace(tzinfo=None)
        except (ValueError, TypeError):
            pass

        # 폴백: 직접 파싱
        for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"]:
            try:
                return datetime.strptime(pub_date_str, fmt).replace(tzinfo=None)
            except ValueError:
                continue
        return None

    @staticmethod
    def _clean_title(raw_title: str) -> str:
        """
        API 응답의 제목에서 HTML 태그와 엔티티를 제거합니다.

        네이버 검색 API는 검색어 매칭 부분을 <b> 태그로 감싸서 반환하며,
        일부 특수문자는 HTML 엔티티(&amp;, &quot; 등)로 인코딩됩니다.

        Args:
            raw_title: API 원본 제목

        Returns:
            str: 정제된 제목
        """
        import html
        title = html.unescape(raw_title)
        title = re.sub(r"<[^>]+>", "", title)
        return title.strip()
