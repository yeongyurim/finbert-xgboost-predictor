"""
데이터 수집 모듈 (Data Collection Module)

yfinance를 활용한 주가 데이터 수집과
네이버 뉴스 검색 기반 크롤링 기능을 제공합니다.

Classes:
    StockDataCollector: 종목 코드 해석 및 일별 주가 데이터 수집 (yfinance 기반)
    NaverNewsCrawler: 네이버 뉴스 검색 결과 크롤링 (차단 방지 포함)

Usage:
    >>> collector = StockDataCollector()
    >>> info = collector.resolve_ticker("삼성전자")
    >>> stock_df = collector.fetch_stock_data("005930.KS", "2024-01-01", "2024-12-31")

    >>> crawler = NaverNewsCrawler(max_pages_per_month=5)
    >>> news_df = crawler.crawl_news("삼성전자", 2024)
"""

import time
import random
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import pandas as pd
import requests
from bs4 import BeautifulSoup

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
    네이버 뉴스 크롤링 클래스

    네이버 검색 뉴스 탭을 활용하여 특정 종목의 연간 뉴스 기사 제목을 수집합니다.
    월별로 분할 크롤링하며, 차단 방지를 위해 User-Agent 설정과
    랜덤 딜레이(time.sleep)를 적용합니다.

    Attributes:
        max_pages_per_month: 월별 최대 크롤링 페이지 수 (기본값: 5, 페이지당 10건)

    Methods:
        crawl_news: 연간 뉴스 기사 제목 수집
    """

    # 차단 방지를 위한 User-Agent 목록
    USER_AGENTS = [
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Safari/605.1.15"
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    ]

    def __init__(self, max_pages_per_month: int = 5):
        """
        NaverNewsCrawler 초기화

        Args:
            max_pages_per_month: 월별 최대 크롤링 페이지 수 (기본: 5)
                각 페이지는 약 10개의 뉴스 항목을 포함합니다.
                5페이지 × 12개월 = 최대 약 600건의 뉴스 수집 가능
        """
        self.max_pages_per_month = max_pages_per_month
        self.session = requests.Session()

    def crawl_news(self, stock_name: str, year: int) -> pd.DataFrame:
        """
        특정 종목의 연간 뉴스 기사 제목을 수집합니다.

        월별로 분할하여 크롤링하며, 각 월의 시작일~말일 범위에서
        뉴스 기사 제목과 게재 일자를 수집합니다.

        Args:
            stock_name: 종목명 (예: "삼성전자")
            year: 대상 연도 (예: 2024)

        Returns:
            pd.DataFrame: 수집된 뉴스 데이터
                컬럼: date (datetime), title (str)
        """
        logger.info(f"뉴스 크롤링 시작: '{stock_name}' {year}년")
        all_news: List[Dict[str, str]] = []

        for month in range(1, 13):
            start_date = f"{year}.{month:02d}.01"

            # 해당 월의 마지막 날 계산
            if month == 12:
                end_date = f"{year}.12.31"
            else:
                last_day = datetime(year, month + 1, 1) - timedelta(days=1)
                end_date = last_day.strftime("%Y.%m.%d")

            logger.info(f"  크롤링 중: {start_date} ~ {end_date}")
            monthly_news = self._crawl_period(stock_name, start_date, end_date)
            all_news.extend(monthly_news)

            # 월별 크롤링 사이에 랜덤 대기
            time.sleep(random.uniform(1.0, 2.5))

        if not all_news:
            logger.warning("수집된 뉴스가 없습니다.")
            return pd.DataFrame(columns=["date", "title"])

        df = pd.DataFrame(all_news)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        df = df.drop_duplicates(subset=["title"], keep="first").reset_index(drop=True)

        logger.info(f"뉴스 크롤링 완료: 총 {len(df)}건 수집")
        return df

    def _crawl_period(
        self, query: str, start_date: str, end_date: str
    ) -> List[Dict[str, str]]:
        """
        특정 기간의 뉴스를 크롤링합니다 (내부 메서드).

        네이버 검색 뉴스 탭에서 날짜 범위 필터를 적용하여
        페이지별로 뉴스 기사 제목과 일자를 추출합니다.

        Args:
            query: 검색어 (종목명)
            start_date: 시작일 (형식: "YYYY.MM.DD")
            end_date: 종료일 (형식: "YYYY.MM.DD")

        Returns:
            list[dict]: 뉴스 항목 리스트 (각 항목은 {'date': ..., 'title': ...})
        """
        news_list: List[Dict[str, str]] = []

        for page_idx in range(self.max_pages_per_month):
            start_offset = page_idx * 10 + 1

            params = {
                "where": "news",
                "query": query,
                "sm": "tab_opt",
                "sort": "1",       # 최신순 정렬
                "photo": "0",
                "field": "0",
                "pd": "3",         # 기간 직접 입력
                "ds": start_date,
                "de": end_date,
                "start": str(start_offset),
            }

            headers = {
                "User-Agent": random.choice(self.USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                "Referer": "https://search.naver.com/",
            }

            try:
                resp = self.session.get(
                    "https://search.naver.com/search.naver",
                    params=params,
                    headers=headers,
                    timeout=15,
                )
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "lxml")
                items = self._extract_news_items(soup)

                if not items:
                    logger.debug(f"  페이지 {page_idx + 1}: 뉴스 항목 없음, 중단")
                    break

                for item in items:
                    parsed = self._parse_news_item(item, start_date)
                    if parsed:
                        news_list.append(parsed)

                # 페이지 간 랜덤 대기 (차단 방지)
                time.sleep(random.uniform(0.5, 1.5))

            except requests.exceptions.HTTPError as e:
                logger.warning(f"  HTTP 오류 (page {page_idx + 1}): {e}")
                if e.response is not None and e.response.status_code == 429:
                    logger.warning("  요청 제한 감지, 10초 대기 후 재시도")
                    time.sleep(10)
                continue
            except requests.exceptions.RequestException as e:
                logger.warning(f"  요청 오류 (page {page_idx + 1}): {e}")
                continue
            except Exception as e:
                logger.warning(f"  파싱 오류 (page {page_idx + 1}): {e}")
                continue

        return news_list

    @staticmethod
    def _extract_news_items(soup: BeautifulSoup) -> list:
        """
        BeautifulSoup 객체에서 뉴스 항목 요소들을 추출합니다.
        네이버 검색 결과의 다양한 HTML 구조를 순차적으로 시도합니다.

        2026년 기준 네이버 뉴스 검색은 SDS 컴포넌트 기반 UI로 개편되어
        div.api_subject_bx 가 개별 뉴스 아이템의 최상위 컨테이너입니다.

        Args:
            soup: 파싱된 HTML

        Returns:
            list: BeautifulSoup Tag 객체 리스트
        """
        # 네이버 검색 결과의 뉴스 아이템 셀렉터 (우선순위 순)
        # 2026년 현재: div.api_subject_bx가 개별 뉴스 카드
        selectors = [
            "div.api_subject_bx",
            "div.news_area",
            "div.news_wrap",
            "li.bx",
            "div.news_contents",
        ]
        for selector in selectors:
            items = soup.select(selector)
            if items:
                logger.debug(f"    셀렉터 '{selector}'로 {len(items)}건 추출")
                return items
        return []

    @staticmethod
    def _parse_news_item(item, fallback_date: str) -> Optional[Dict[str, str]]:
        """
        개별 뉴스 항목에서 제목과 날짜를 추출합니다.

        2026년 기준 네이버 뉴스 검색 결과의 제목은:
        - <span class="...sds-comps-text-type-headline1"> 에 있거나
        - <a class="...EqVldlKiXvspTtpN"> (기사 제목 링크, 해시 클래스) 에 존재합니다.
        해시 클래스는 빌드마다 변경될 수 있으므로 여러 전략을 폴백으로 사용합니다.

        Args:
            item: BeautifulSoup Tag 객체 (개별 뉴스 항목)
            fallback_date: 날짜 파싱 실패 시 대체 날짜 (형식: "YYYY.MM.DD")

        Returns:
            dict: {'date': 'YYYY-MM-DD', 'title': '뉴스 제목'} 또는 None
        """
        title = None

        # ── 제목 추출 전략 (우선순위 순) ──

        # 전략 1: headline 클래스가 포함된 span (2026 SDS UI)
        headline_tag = item.select_one("span[class*='headline']")
        if headline_tag:
            title = headline_tag.get_text(strip=True)

        # 전략 2: 기존 레거시 셀렉터
        if not title:
            for sel in ["a.news_tit", "a.api_txt_lines", "a[class*='tit']"]:
                tag = item.select_one(sel)
                if tag:
                    title = tag.get_text(strip=True)
                    break

        # 전략 3: 외부 뉴스 링크 중 본문 미리보기가 아닌 제목 링크 추출
        # api_subject_bx 내부에서 뉴스 제목 링크는 보통 첫 번째
        # 외부 도메인(naver.com이 아닌) href를 가진 <a> 태그
        if not title:
            for a_tag in item.select("a[href]"):
                href = a_tag.get("href", "")
                text = a_tag.get_text(strip=True)
                # 뉴스 제목 후보 필터링:
                # - 외부 URL (naver.com 도메인 제외)
                # - 텍스트 길이 15~100자 (너무 짧으면 UI 요소, 너무 길면 본문 snippet)
                # - 광고/UI 키워드 제외
                if (
                    href.startswith("http")
                    and "naver.com" not in href
                    and "naver.net" not in href
                    and 15 < len(text) <= 100
                    and not any(kw in text for kw in ["클립", "Keep에", "포인트", "구독"])
                ):
                    title = text
                    break

        if not title:
            return None

        # 날짜 추출
        date_str = NaverNewsCrawler._extract_date(item, fallback_date)

        return {"date": date_str, "title": title}

    @staticmethod
    def _extract_date(item, fallback_date: str) -> str:
        """
        뉴스 항목에서 날짜를 추출하고 표준 형식(YYYY-MM-DD)으로 변환합니다.

        상대 날짜("3일 전", "2시간 전" 등)와 절대 날짜("2024.01.15.")를
        모두 처리합니다.

        2026년 기준 네이버 뉴스 검색의 날짜 정보는:
        - <span class="...sds-comps-profile-info-subtext"> 에 "2024.01.31." 형태로 표시
        - 기존 <span class="info"> 는 더 이상 사용되지 않음

        Args:
            item: BeautifulSoup Tag 객체
            fallback_date: 대체 날짜

        Returns:
            str: "YYYY-MM-DD" 형식의 날짜 문자열
        """
        # ── 날짜가 포함될 수 있는 태그 후보 수집 ──
        # 2026 SDS UI: span.sds-comps-profile-info-subtext
        # 레거시: span.info
        date_tags = item.select("span[class*='profile-info-subtext']")
        if not date_tags:
            date_tags = item.select("span.info")
        if not date_tags:
            # 최후 폴백: 아이템 내 모든 span에서 날짜 패턴 탐색
            date_tags = item.select("span")

        for tag in date_tags:
            text = tag.get_text(strip=True)

            # 빈 텍스트 스킵
            if not text:
                continue

            # 언론사 이름 필터 (숫자나 '전'이 포함되지 않으면 스킵)
            if not re.search(r"[\d전]", text):
                continue

            # 상대 날짜 처리
            now = datetime.now()

            minute_match = re.search(r"(\d+)분\s*전", text)
            if minute_match:
                return now.strftime("%Y-%m-%d")

            hour_match = re.search(r"(\d+)시간\s*전", text)
            if hour_match:
                return now.strftime("%Y-%m-%d")

            day_match = re.search(r"(\d+)일\s*전", text)
            if day_match:
                days = int(day_match.group(1))
                return (now - timedelta(days=days)).strftime("%Y-%m-%d")

            week_match = re.search(r"(\d+)주\s*전", text)
            if week_match:
                weeks = int(week_match.group(1))
                return (now - timedelta(weeks=weeks)).strftime("%Y-%m-%d")

            # 절대 날짜 파싱 (다양한 형식 시도)
            # "2024.01.31." 또는 "2024.1.31" 등
            date_patterns = [
                r"(\d{4})\.(\d{1,2})\.(\d{1,2})",
            ]
            for pattern in date_patterns:
                m = re.search(pattern, text)
                if m:
                    try:
                        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                        return datetime(y, mo, d).strftime("%Y-%m-%d")
                    except ValueError:
                        continue

        # 모든 시도 실패 시 fallback 날짜 사용
        return fallback_date.replace(".", "-")
