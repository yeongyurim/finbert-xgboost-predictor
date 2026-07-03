"""
추론 모듈 (Inference & Interface Module)

저장된 모델 파일을 로드하여 다음 날 주가를 예측합니다.
예측 결과는 API 응답으로 바로 변환 가능한 정형화된 딕셔너리 형태로 반환됩니다.

Classes:
    StockPredictor: 학습된 모델 기반 주가 예측기

Usage:
    >>> predictor = StockPredictor(model_dir="models")
    >>> result = predictor.predict(
    ...     ticker="005930",
    ...     features=latest_feature_series,
    ...     avg_sentiment=0.72
    ... )
    >>> print(result)
    {
        "ticker": "005930",
        "target_date": "2026-06-30",
        "predicted_trend": "상승",
        "predicted_price": 81200,
        ...
    }
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union

import numpy as np
import pandas as pd
import joblib

from .preprocessor import FEATURE_COLUMNS, DataPreprocessor

logger = logging.getLogger(__name__)


class StockPredictor:
    """
    학습된 모델 기반 주가 예측 클래스

    저장된 XGBoost 모델, 스케일러, 메타데이터를 로드하고,
    최신 피처 데이터를 입력받아 다음 거래일의 주가(종가) 및
    상승/하락 추세를 예측합니다.

    반환되는 예측 결과는 FastAPI 등의 웹 프레임워크에서
    JSON 응답으로 바로 직렬화 가능한 딕셔너리 형태입니다.

    Attributes:
        model_dir: 모델 파일 저장 디렉토리
        regressor: 로드된 XGBRegressor
        classifier: 로드된 XGBClassifier
        scaler: 로드된 StandardScaler
        metadata: 로드된 메타데이터 딕셔너리
        feature_columns: 학습 시 사용된 피처 컬럼 목록

    Methods:
        load_model: 저장된 모델 파일 로드
        predict: 피처 벡터로 예측 수행
        predict_from_dataframe: DataFrame의 마지막 행으로 예측 수행
    """

    def __init__(self, model_dir: str = "models"):
        """
        StockPredictor 초기화

        Args:
            model_dir: 모델 파일이 저장된 디렉토리 경로
        """
        self.model_dir = model_dir
        self.regressor = None
        self.classifier = None
        self.scaler = None
        self.metadata: Dict[str, Any] = {}
        self.feature_columns: List[str] = []

    def load_model(self, ticker: str) -> Dict[str, Any]:
        """
        지정된 종목의 학습된 모델 파일을 로드합니다.

        Args:
            ticker: 종목코드 (예: "005930")

        Returns:
            dict: 모델 메타데이터 딕셔너리

        Raises:
            FileNotFoundError: 모델 파일이 존재하지 않는 경우
        """
        logger.info(f"모델 로드 시작: {ticker}")

        # 파일 경로 설정
        reg_path = os.path.join(self.model_dir, f"{ticker}_regressor.pkl")
        clf_path = os.path.join(self.model_dir, f"{ticker}_classifier.pkl")
        scaler_path = os.path.join(self.model_dir, f"{ticker}_scaler.pkl")
        meta_path = os.path.join(self.model_dir, f"{ticker}_metadata.json")

        # 파일 존재 확인
        for path, name in [
            (reg_path, "회귀 모델"),
            (clf_path, "분류 모델"),
            (scaler_path, "스케일러"),
            (meta_path, "메타데이터"),
        ]:
            if not os.path.exists(path):
                raise FileNotFoundError(f"{name} 파일을 찾을 수 없습니다: {path}")

        # 파일 로드
        self.regressor = joblib.load(reg_path)
        self.classifier = joblib.load(clf_path)
        self.scaler = joblib.load(scaler_path)

        with open(meta_path, "r", encoding="utf-8") as f:
            self.metadata = json.load(f)

        self.feature_columns = self.metadata.get("feature_columns", FEATURE_COLUMNS)

        logger.info(
            f"모델 로드 완료: {ticker} "
            f"(학습일: {self.metadata.get('trained_at', 'N/A')}, "
            f"피처 {len(self.feature_columns)}개)"
        )
        return self.metadata

    def predict(
        self,
        ticker: str,
        features: Union[pd.Series, Dict[str, float], np.ndarray],
        avg_sentiment: float = 0.0,
        target_date: Optional[str] = None,
        stock_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        피처 벡터를 입력받아 다음 날 주가를 예측합니다.

        Args:
            ticker: 종목코드 (예: "005930")
            features: 피처 벡터. 다음 형태 중 하나:
                - pd.Series: feature_columns를 인덱스로 가진 시리즈
                - dict: {피처명: 값} 딕셔너리
                - np.ndarray: feature_columns 순서의 1D 배열
            avg_sentiment: 평균 감성 스코어 (별도 전달, -1~1)
            target_date: 예측 대상 날짜 (None이면 내일 자동 설정)
            stock_name: 종목명 (결과에 포함, None이면 생략)

        Returns:
            dict: 정형화된 예측 결과 딕셔너리
                - ticker (str): 종목코드
                - stock_name (str): 종목명 (입력 시)
                - target_date (str): 예측 대상 날짜 (YYYY-MM-DD)
                - predicted_trend (str): "상승" 또는 "하락"
                - predicted_price (int): 예측 종가 (원 단위, 정수)
                - trend_probability (float): 추세 예측 확률 (0~1)
                - avg_sentiment_score (float): 평균 감성 스코어
                - model_metrics (dict): 학습 시 성능 지표
                - predicted_at (str): 예측 수행 시각

        Raises:
            RuntimeError: 모델이 로드되지 않은 경우
        """
        if self.regressor is None or self.classifier is None:
            raise RuntimeError(
                "모델이 로드되지 않았습니다. load_model()을 먼저 호출하세요."
            )

        # 피처 벡터 변환
        feature_vector = self._prepare_feature_vector(features)

        # 스케일링
        feature_scaled = self.scaler.transform(feature_vector.reshape(1, -1))

        # 회귀 예측 (종가)
        predicted_price = float(self.regressor.predict(feature_scaled)[0])

        # 분류 예측 (상승/하락)
        predicted_class = int(self.classifier.predict(feature_scaled)[0])
        class_proba = self.classifier.predict_proba(feature_scaled)[0]
        trend_probability = float(class_proba[1])  # 상승 확률

        predicted_trend = "상승" if predicted_class == 1 else "하락"

        # 예측 대상 날짜 설정
        if target_date is None:
            target_date = self._get_next_trading_date()

        # 결과 딕셔너리 조립
        result: Dict[str, Any] = {
            "ticker": ticker,
            "target_date": target_date,
            "predicted_trend": predicted_trend,
            "predicted_price": int(round(predicted_price)),
            "trend_probability": round(trend_probability, 4),
            "avg_sentiment_score": round(avg_sentiment, 4),
            "model_metrics": {
                "regression": self.metadata.get("regression_metrics", {}),
                "classification": self.metadata.get("classification_metrics", {}),
            },
            "predicted_at": datetime.now().isoformat(),
        }

        if stock_name:
            result["stock_name"] = stock_name

        logger.info(
            f"예측 완료: {ticker} → {predicted_trend} "
            f"(종가: {int(round(predicted_price)):,}원, "
            f"상승확률: {trend_probability:.2%})"
        )

        return result

    def predict_from_dataframe(
        self,
        ticker: str,
        df: pd.DataFrame,
        stock_name: Optional[str] = None,
        target_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        전처리된 DataFrame의 마지막 행을 사용하여 예측합니다.

        학습 파이프라인 직후에 호출하여 최신 데이터 기반 예측을 수행합니다.

        Args:
            ticker: 종목코드
            df: 전처리된 DataFrame (FEATURE_COLUMNS 포함)
            stock_name: 종목명 (None이면 결과에서 생략)
            target_date: 예측 대상 날짜 (None이면 자동 계산)

        Returns:
            dict: 정형화된 예측 결과 딕셔너리
        """
        if df.empty:
            raise ValueError("예측에 사용할 데이터가 없습니다.")

        # 마지막 행의 피처 추출
        last_row = df.iloc[-1]
        available_features = [col for col in self.feature_columns if col in df.columns]
        features = last_row[available_features]

        # 감성 스코어 추출
        avg_sentiment = float(last_row.get("sentiment_score", 0.0))

        # 대상 날짜가 없으면 마지막 날짜의 다음 거래일
        if target_date is None and "Date" in df.columns:
            last_date = pd.to_datetime(df["Date"].iloc[-1])
            target_date = self._get_next_trading_date(last_date)

        return self.predict(
            ticker=ticker,
            features=features,
            avg_sentiment=avg_sentiment,
            target_date=target_date,
            stock_name=stock_name,
        )

    def _prepare_feature_vector(
        self, features: Union[pd.Series, Dict[str, float], np.ndarray]
    ) -> np.ndarray:
        """
        다양한 형태의 피처 입력을 1D numpy 배열로 변환합니다.

        Args:
            features: 피처 데이터 (Series, dict, 또는 ndarray)

        Returns:
            np.ndarray: 1D 피처 벡터 (feature_columns 순서)
        """
        if isinstance(features, np.ndarray):
            if features.ndim == 1 and len(features) == len(self.feature_columns):
                return features.astype(np.float64)
            raise ValueError(
                f"ndarray 크기가 맞지 않습니다. "
                f"기대: {len(self.feature_columns)}, 입력: {len(features)}"
            )

        if isinstance(features, dict):
            features = pd.Series(features)

        if isinstance(features, pd.Series):
            vector = []
            for col in self.feature_columns:
                if col in features.index:
                    val = features[col]
                    vector.append(float(val) if pd.notna(val) else 0.0)
                else:
                    logger.warning(f"피처 '{col}'이 입력에 없습니다. 0.0으로 대체합니다.")
                    vector.append(0.0)
            return np.array(vector, dtype=np.float64)

        raise TypeError(f"지원되지 않는 피처 타입: {type(features)}")

    @staticmethod
    def _get_next_trading_date(base_date: Optional[datetime] = None) -> str:
        """
        다음 거래일(영업일)을 계산합니다.

        주말(토/일)은 건너뛰고, 다음 월~금 중 가장 가까운 날을 반환합니다.
        (공휴일은 미반영 — 정확한 공휴일 처리는 별도 DB 필요)

        Args:
            base_date: 기준 날짜 (None이면 오늘)

        Returns:
            str: "YYYY-MM-DD" 형식의 다음 거래일
        """
        if base_date is None:
            base_date = datetime.now()

        next_date = base_date + timedelta(days=1)

        # 주말 건너뛰기 (5=토요일, 6=일요일)
        while next_date.weekday() >= 5:
            next_date += timedelta(days=1)

        return next_date.strftime("%Y-%m-%d")
