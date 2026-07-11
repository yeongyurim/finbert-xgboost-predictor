"""
데이터 전처리 모듈 (Preprocessing Module)

주가 데이터와 뉴스 감성 스코어를 병합하고,
기술적 분석 지표를 생성하며, 결측치를 처리하여
머신러닝 학습에 적합한 형태로 변환합니다.

Classes:
    DataPreprocessor: 데이터 병합, 기술적 지표 생성, 타겟 변수 생성

Usage:
    >>> preprocessor = DataPreprocessor()
    >>> merged_df = preprocessor.preprocess(stock_df, sentiment_df)
"""

import logging
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 모델 학습에 사용되는 피처 컬럼 목록
FEATURE_COLUMNS = [
    # 기본 주가 데이터
    "Open", "High", "Low", "Close", "Volume", "Change",
    # 이동평균
    "MA5", "MA20",
    # 기술적 지표
    "RSI",
    "MACD", "MACD_Signal", "MACD_Hist",
    "BB_Upper", "BB_Lower", "BB_Width",
    # 거래량 파생
    "Volume_Change", "Volume_MA5",
    # 가격 파생
    "Price_Range", "Price_Range_Pct",
    # 감성 지표
    "sentiment_score", "positive", "negative", "neutral",
]

# 타겟 변수명
TARGET_REGRESSION = "next_day_close"
TARGET_CLASSIFICATION = "next_day_trend"


class DataPreprocessor:
    """
    데이터 전처리 클래스

    주가 데이터와 감성 분석 결과를 병합하고, 기술적 분석 지표를 추가하여
    머신러닝 모델 학습에 바로 사용할 수 있는 정제된 DataFrame을 생성합니다.

    생성되는 기술적 지표:
        - MA5, MA20: 5일/20일 이동평균선
        - RSI: 상대강도지수 (14일)
        - MACD, MACD_Signal, MACD_Hist: MACD 관련 지표
        - BB_Upper, BB_Lower, BB_Width: 볼린저 밴드
        - Volume_Change, Volume_MA5: 거래량 파생 지표
        - Price_Range, Price_Range_Pct: 가격 변동폭

    Methods:
        preprocess: 주가+감성 데이터 병합 및 전처리 수행
        add_technical_indicators: 기술적 분석 지표 추가
        create_targets: 예측 타겟 변수 생성
    """

    def __init__(self):
        """DataPreprocessor 초기화"""
        pass

    def preprocess(
        self,
        stock_df: pd.DataFrame,
        sentiment_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        주가 데이터와 감성 데이터를 병합·전처리하여 학습용 DataFrame을 생성합니다.

        처리 순서:
            1. 기술적 지표 추가 (이동평균, RSI, MACD, 볼린저 밴드 등)
            2. 감성 데이터와 날짜 기준 병합 (left join)
            3. 결측치 처리 (뉴스 없는 날 → 중립 감성)
            4. 타겟 변수 생성 (다음 날 종가 및 상승/하락 여부)
            5. 결측 행 제거 (기술적 지표 계산 초기 구간)

        Args:
            stock_df: 주가 데이터 DataFrame
                필수 컬럼: Date, Open, High, Low, Close, Volume, Change
            sentiment_df: 감성 분석 결과 DataFrame
                필수 컬럼: date, positive, negative, neutral, sentiment_score

        Returns:
            pd.DataFrame: 전처리 완료된 학습용 데이터
                피처 컬럼(FEATURE_COLUMNS) + 타겟 컬럼 + Date 포함
        """
        logger.info(f"데이터 전처리 시작: 주가 {len(stock_df)}행, 감성 {len(sentiment_df)}행")

        # 1. 기술적 지표 추가
        df = self.add_technical_indicators(stock_df.copy())

        # 2. 감성 데이터 병합 (날짜 기준 left join)
        df = self._merge_sentiment(df, sentiment_df)

        # 3. 결측치 처리
        df = self._handle_missing_values(df)

        # 4. 타겟 변수 생성
        df = self.create_targets(df)

        # 5. 기술적 지표 계산에 의한 초기 NaN 행 제거 (마지막 타겟 행은 유지)
        initial_len = len(df)
        df = df.dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)

        logger.info(
            f"전처리 완료: {initial_len}행 → {len(df)}행 "
            f"(피처 {len(FEATURE_COLUMNS)}개, 타겟 2개)"
        )
        return df

    def add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        주가 데이터에 기술적 분석 지표를 추가합니다.

        순수 pandas 연산으로 구현하여 외부 기술적 분석 라이브러리(ta, ta-lib 등)
        의존성이 없습니다.

        Args:
            df: 주가 데이터 DataFrame
                필수 컬럼: Close, High, Low, Volume

        Returns:
            pd.DataFrame: 기술적 지표가 추가된 DataFrame
        """
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        # ---- 이동평균선 (Moving Averages) ----
        df["MA5"] = close.rolling(window=5, min_periods=1).mean()
        df["MA20"] = close.rolling(window=20, min_periods=1).mean()

        # ---- RSI (Relative Strength Index, 14일) ----
        df["RSI"] = self._calculate_rsi(close, period=14)

        # ---- MACD (Moving Average Convergence Divergence) ----
        macd, signal, hist = self._calculate_macd(close)
        df["MACD"] = macd
        df["MACD_Signal"] = signal
        df["MACD_Hist"] = hist

        # ---- 볼린저 밴드 (Bollinger Bands, 20일) ----
        bb_upper, bb_lower = self._calculate_bollinger_bands(close, period=20)
        df["BB_Upper"] = bb_upper
        df["BB_Lower"] = bb_lower
        df["BB_Width"] = bb_upper - bb_lower

        # ---- 거래량 파생 지표 ----
        df["Volume_Change"] = volume.pct_change()
        df["Volume_MA5"] = volume.rolling(window=5, min_periods=1).mean()

        # ---- 가격 변동폭 ----
        df["Price_Range"] = high - low
        df["Price_Range_Pct"] = df["Price_Range"] / close

        logger.debug(f"기술적 지표 {10}개 추가 완료")
        return df

    def create_targets(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        예측 타겟 변수를 생성합니다.

        - next_day_close: 다음 거래일의 종가 (회귀 타겟)
        - next_day_trend: 다음 거래일 상승=1, 하락=0 (분류 타겟)

        Args:
            df: 기술적 지표가 포함된 DataFrame (Close 컬럼 필수)

        Returns:
            pd.DataFrame: 타겟 변수가 추가된 DataFrame
                마지막 행은 다음 날 데이터가 없으므로 NaN
        """
        df[TARGET_REGRESSION] = df["Close"].shift(-1)
        df[TARGET_CLASSIFICATION] = (df["Close"].shift(-1) > df["Close"]).astype(float)

        # 마지막 행은 타겟 없음 → NaN으로 유지 (train 시 제거됨)
        return df

    def _merge_sentiment(
        self, stock_df: pd.DataFrame, sentiment_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        주가 데이터와 감성 데이터를 날짜 기준으로 병합합니다.

        Args:
            stock_df: 주가 데이터 (Date 컬럼)
            sentiment_df: 감성 데이터 (date 컬럼)

        Returns:
            pd.DataFrame: 병합된 DataFrame
        """
        if sentiment_df.empty:
            # 감성 데이터가 없으면 기본 컬럼만 추가
            for col in ["positive", "negative", "neutral", "sentiment_score"]:
                stock_df[col] = 0.0
            return stock_df

        # 날짜 컬럼 통일
        stock_df["_merge_date"] = pd.to_datetime(stock_df["Date"]).dt.date
        sentiment_copy = sentiment_df.copy()
        sentiment_copy["_merge_date"] = pd.to_datetime(sentiment_copy["date"]).dt.date

        # 필요한 감성 컬럼만 선택
        sentiment_cols = ["_merge_date", "positive", "negative", "neutral", "sentiment_score"]
        available_cols = [c for c in sentiment_cols if c in sentiment_copy.columns]
        sentiment_subset = sentiment_copy[available_cols]

        # Left join: 주가 데이터 기준, 뉴스 없는 날은 NaN
        merged = stock_df.merge(sentiment_subset, on="_merge_date", how="left")
        merged = merged.drop(columns=["_merge_date"])

        return merged

    @staticmethod
    def _handle_missing_values(df: pd.DataFrame) -> pd.DataFrame:
        """
        결측치를 처리합니다.

        - 감성 관련 컬럼: 뉴스가 없는 날은 중립(0.0)으로 채움
        - 거래량 변화율: 0으로 채움
        - 기타 숫자 컬럼: forward fill → backward fill

        Args:
            df: 결측치가 포함된 DataFrame

        Returns:
            pd.DataFrame: 결측치 처리된 DataFrame
        """
        # 감성 관련 컬럼은 중립으로 채움
        sentiment_fill = {
            "positive": 0.33,
            "negative": 0.33,
            "neutral": 0.34,
            "sentiment_score": 0.0,
        }
        for col, fill_val in sentiment_fill.items():
            if col in df.columns:
                df[col] = df[col].fillna(fill_val)

        # 거래량 변화율 결측 처리
        if "Volume_Change" in df.columns:
            df["Volume_Change"] = df["Volume_Change"].fillna(0.0)

        # inf 값 처리
        df = df.replace([np.inf, -np.inf], np.nan)

        return df

    @staticmethod
    def _calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """
        상대강도지수(RSI)를 계산합니다.

        RSI = 100 - (100 / (1 + RS))
        RS = 평균 상승폭 / 평균 하락폭

        Args:
            series: 종가 시리즈
            period: 계산 기간 (기본: 14일)

        Returns:
            pd.Series: RSI 값 (0~100 범위)
        """
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(window=period, min_periods=1).mean()
        avg_loss = loss.rolling(window=period, min_periods=1).mean()

        # 0으로 나누는 경우 방지
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        return rsi.fillna(50.0)  # 초기 NaN은 중립값(50)으로

    @staticmethod
    def _calculate_macd(
        series: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        MACD (이동평균 수렴·발산) 지표를 계산합니다.

        MACD Line = EMA(12) - EMA(26)
        Signal Line = EMA(MACD, 9)
        Histogram = MACD - Signal

        Args:
            series: 종가 시리즈
            fast: 단기 EMA 기간 (기본: 12)
            slow: 장기 EMA 기간 (기본: 26)
            signal: 시그널 EMA 기간 (기본: 9)

        Returns:
            tuple[pd.Series, pd.Series, pd.Series]: MACD, Signal, Histogram
        """
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    @staticmethod
    def _calculate_bollinger_bands(
        series: pd.Series, period: int = 20, std_dev: float = 2.0
    ) -> Tuple[pd.Series, pd.Series]:
        """
        볼린저 밴드(Bollinger Bands)를 계산합니다.

        Upper Band = MA(20) + 2 × σ
        Lower Band = MA(20) - 2 × σ

        Args:
            series: 종가 시리즈
            period: 이동평균 기간 (기본: 20)
            std_dev: 표준편차 배수 (기본: 2.0)

        Returns:
            tuple[pd.Series, pd.Series]: (Upper Band, Lower Band)
        """
        ma = series.rolling(window=period, min_periods=1).mean()
        std = series.rolling(window=period, min_periods=1).std()

        upper = ma + (std * std_dev)
        lower = ma - (std * std_dev)

        return upper, lower

    @staticmethod
    def get_feature_columns() -> List[str]:
        """학습에 사용되는 피처 컬럼 목록을 반환합니다."""
        return FEATURE_COLUMNS.copy()

    @staticmethod
    def get_target_columns() -> Tuple[str, str]:
        """타겟 변수명을 반환합니다. (회귀, 분류)"""
        return TARGET_REGRESSION, TARGET_CLASSIFICATION
