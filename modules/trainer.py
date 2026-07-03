"""
모델 학습 모듈 (Modeling & Training Module)

전처리된 데이터를 기반으로 XGBoost 회귀(종가 예측) 및
분류(상승/하락 예측) 모델을 학습하고, 학습된 모델을 파일로 직렬화합니다.

Classes:
    ModelTrainer: XGBoost 모델 학습, 평가, 저장

Usage:
    >>> trainer = ModelTrainer(model_dir="models")
    >>> metrics = trainer.train(preprocessed_df, ticker="005930")
    >>> # 모델 파일 저장: models/005930_regressor.pkl, ...
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
import joblib
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
)
from xgboost import XGBRegressor, XGBClassifier

from .preprocessor import FEATURE_COLUMNS, TARGET_REGRESSION, TARGET_CLASSIFICATION

logger = logging.getLogger(__name__)


class ModelTrainer:
    """
    XGBoost 모델 학습 클래스

    전처리된 DataFrame을 입력받아 회귀 모델(종가 예측)과
    분류 모델(상승/하락 예측)을 학습하고, 학습 결과를 직렬화하여
    로컬 파일로 저장합니다.

    데이터 분할은 시계열 특성을 고려하여 시간순 분할(앞쪽 80% 학습,
    뒤쪽 20% 검증)을 적용합니다.

    저장 파일:
        - {ticker}_regressor.pkl: 종가 예측 회귀 모델
        - {ticker}_classifier.pkl: 상승/하락 분류 모델
        - {ticker}_scaler.pkl: 피처 스케일러
        - {ticker}_metadata.json: 학습 메타데이터 (피처 목록, 성능 등)

    Attributes:
        model_dir: 모델 저장 디렉토리 경로
        train_ratio: 학습 데이터 비율 (기본: 0.8)
        regressor: 학습된 XGBRegressor 인스턴스
        classifier: 학습된 XGBClassifier 인스턴스
        scaler: 학습된 StandardScaler 인스턴스
        feature_columns: 실제 학습에 사용된 피처 목록
        metrics: 학습 결과 성능 지표 딕셔너리
    """

    # XGBoost 기본 하이퍼파라미터
    DEFAULT_REG_PARAMS = {
        "n_estimators": 200,
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "random_state": 42,
        "objective": "reg:squarederror",
        "n_jobs": -1,
    }

    DEFAULT_CLF_PARAMS = {
        "n_estimators": 200,
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "random_state": 42,
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "n_jobs": -1,
    }

    def __init__(
        self,
        model_dir: str = "models",
        train_ratio: float = 0.8,
        reg_params: Optional[Dict] = None,
        clf_params: Optional[Dict] = None,
    ):
        """
        ModelTrainer 초기화

        Args:
            model_dir: 모델 파일 저장 디렉토리 (기본: "models")
            train_ratio: 학습 데이터 비율 (기본: 0.8, 나머지는 검증)
            reg_params: XGBRegressor 커스텀 하이퍼파라미터 (None이면 기본값 사용)
            clf_params: XGBClassifier 커스텀 하이퍼파라미터 (None이면 기본값 사용)
        """
        self.model_dir = model_dir
        self.train_ratio = train_ratio
        self.reg_params = reg_params or self.DEFAULT_REG_PARAMS.copy()
        self.clf_params = clf_params or self.DEFAULT_CLF_PARAMS.copy()

        # 학습 결과 상태
        self.regressor: Optional[XGBRegressor] = None
        self.classifier: Optional[XGBClassifier] = None
        self.scaler: Optional[StandardScaler] = None
        self.feature_columns: List[str] = []
        self.metrics: Dict[str, Any] = {}

        # 모델 저장 디렉토리 생성
        os.makedirs(self.model_dir, exist_ok=True)

    def train(self, df: pd.DataFrame, ticker: str) -> Dict[str, Any]:
        """
        모델 학습 전체 파이프라인을 실행합니다.

        1. 피처/타겟 분리
        2. 시간순 Train/Test 분할
        3. 피처 스케일링
        4. 회귀 모델 학습 (종가 예측)
        5. 분류 모델 학습 (상승/하락 예측)
        6. 성능 평가
        7. 모델 파일 저장

        Args:
            df: 전처리 완료된 DataFrame (FEATURE_COLUMNS + TARGET 컬럼 포함)
            ticker: 종목코드 (파일명에 사용)

        Returns:
            dict: 학습 결과 딕셔너리
                - ticker: 종목코드
                - train_size: 학습 데이터 수
                - test_size: 검증 데이터 수
                - regression_metrics: 회귀 모델 성능 (MAE, RMSE, MAPE)
                - classification_metrics: 분류 모델 성능 (Accuracy, Precision, Recall, F1)
                - feature_importance: 피처 중요도 상위 10개
                - model_files: 저장된 모델 파일 경로 목록
        """
        logger.info(f"모델 학습 시작: {ticker} ({len(df)}행)")

        # 1. 사용 가능한 피처 컬럼 확인 (데이터에 없는 피처 제외)
        self.feature_columns = [col for col in FEATURE_COLUMNS if col in df.columns]
        if len(self.feature_columns) < 3:
            raise ValueError(
                f"학습 가능한 피처가 부족합니다 ({len(self.feature_columns)}개). "
                f"최소 3개 이상의 피처가 필요합니다."
            )

        logger.info(f"사용 피처: {len(self.feature_columns)}개")

        # 2. 피처/타겟 분리
        X = df[self.feature_columns].values
        y_reg = df[TARGET_REGRESSION].values
        y_clf = df[TARGET_CLASSIFICATION].values

        # 3. 시간순 Train/Test 분할 (데이터 누수 방지)
        split_idx = int(len(X) * self.train_ratio)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_reg_train, y_reg_test = y_reg[:split_idx], y_reg[split_idx:]
        y_clf_train, y_clf_test = y_clf[:split_idx], y_clf[split_idx:]

        logger.info(f"데이터 분할: Train {len(X_train)}행, Test {len(X_test)}행")

        # 4. 피처 스케일링
        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        # 5. 회귀 모델 학습 (종가 예측)
        logger.info("회귀 모델(XGBRegressor) 학습 중...")
        self.regressor = XGBRegressor(**self.reg_params)
        self.regressor.fit(
            X_train_scaled, y_reg_train,
            eval_set=[(X_test_scaled, y_reg_test)],
            verbose=False,
        )

        # 6. 분류 모델 학습 (상승/하락 예측)
        logger.info("분류 모델(XGBClassifier) 학습 중...")
        self.classifier = XGBClassifier(**self.clf_params)
        self.classifier.fit(
            X_train_scaled, y_clf_train,
            eval_set=[(X_test_scaled, y_clf_test)],
            verbose=False,
        )

        # 7. 성능 평가
        reg_metrics = self._evaluate_regression(X_test_scaled, y_reg_test)
        clf_metrics = self._evaluate_classification(X_test_scaled, y_clf_test)

        # 피처 중요도
        importance = self._get_feature_importance()

        # 8. 모델 파일 저장
        saved_files = self._save_models(ticker, reg_metrics, clf_metrics, importance)

        # 결과 딕셔너리 조립
        self.metrics = {
            "ticker": ticker,
            "train_size": len(X_train),
            "test_size": len(X_test),
            "train_date_range": {
                "start": str(df["Date"].iloc[0].date()),
                "end": str(df["Date"].iloc[split_idx - 1].date()),
            },
            "test_date_range": {
                "start": str(df["Date"].iloc[split_idx].date()),
                "end": str(df["Date"].iloc[-1].date()),
            },
            "regression_metrics": reg_metrics,
            "classification_metrics": clf_metrics,
            "feature_importance": importance,
            "model_files": saved_files,
        }

        logger.info(
            f"모델 학습 완료: "
            f"MAE={reg_metrics['mae']:.2f}, "
            f"RMSE={reg_metrics['rmse']:.2f}, "
            f"Accuracy={clf_metrics['accuracy']:.4f}"
        )

        return self.metrics

    def _evaluate_regression(
        self, X_test: np.ndarray, y_test: np.ndarray
    ) -> Dict[str, float]:
        """
        회귀 모델 성능을 평가합니다.

        Args:
            X_test: 검증 피처 배열
            y_test: 검증 타겟 배열 (실제 종가)

        Returns:
            dict: 성능 지표
                - mae: 평균 절대 오차
                - rmse: 평균 제곱근 오차
                - mape: 평균 절대 백분율 오차 (%)
        """
        y_pred = self.regressor.predict(X_test)

        mae = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))

        # MAPE 계산 (0에 가까운 값은 제외하여 무한대 방지)
        mask = np.abs(y_test) > 1e-8
        if mask.any():
            mape = np.mean(np.abs((y_test[mask] - y_pred[mask]) / y_test[mask])) * 100
        else:
            mape = 0.0

        metrics = {"mae": round(float(mae), 2), "rmse": round(float(rmse), 2), "mape": round(float(mape), 2)}
        logger.info(f"  회귀 성능 - MAE: {mae:.2f}, RMSE: {rmse:.2f}, MAPE: {mape:.2f}%")
        return metrics

    def _evaluate_classification(
        self, X_test: np.ndarray, y_test: np.ndarray
    ) -> Dict[str, float]:
        """
        분류 모델 성능을 평가합니다.

        Args:
            X_test: 검증 피처 배열
            y_test: 검증 타겟 배열 (1=상승, 0=하락)

        Returns:
            dict: 성능 지표
                - accuracy: 정확도
                - precision: 정밀도
                - recall: 재현율
                - f1: F1 스코어
        """
        y_pred = self.classifier.predict(X_test)

        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)

        metrics = {
            "accuracy": round(float(acc), 4),
            "precision": round(float(prec), 4),
            "recall": round(float(rec), 4),
            "f1": round(float(f1), 4),
        }
        logger.info(
            f"  분류 성능 - Accuracy: {acc:.4f}, Precision: {prec:.4f}, "
            f"Recall: {rec:.4f}, F1: {f1:.4f}"
        )
        return metrics

    def _get_feature_importance(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """
        회귀 모델의 피처 중요도 상위 N개를 반환합니다.

        Args:
            top_n: 반환할 상위 피처 수 (기본: 10)

        Returns:
            list[dict]: 피처 중요도 리스트 (내림차순)
                각 항목: {"feature": str, "importance": float}
        """
        if self.regressor is None:
            return []

        importances = self.regressor.feature_importances_
        indices = np.argsort(importances)[::-1][:top_n]

        result = []
        for idx in indices:
            if idx < len(self.feature_columns):
                result.append({
                    "feature": self.feature_columns[idx],
                    "importance": round(float(importances[idx]), 4),
                })

        return result

    def _save_models(
        self,
        ticker: str,
        reg_metrics: Dict,
        clf_metrics: Dict,
        importance: List,
    ) -> List[str]:
        """
        학습된 모델, 스케일러, 메타데이터를 파일로 저장합니다.

        Args:
            ticker: 종목코드
            reg_metrics: 회귀 모델 성능 지표
            clf_metrics: 분류 모델 성능 지표
            importance: 피처 중요도

        Returns:
            list[str]: 저장된 파일 경로 리스트
        """
        saved_files = []

        # 회귀 모델 저장
        reg_path = os.path.join(self.model_dir, f"{ticker}_regressor.pkl")
        joblib.dump(self.regressor, reg_path)
        saved_files.append(reg_path)
        logger.info(f"  회귀 모델 저장: {reg_path}")

        # 분류 모델 저장
        clf_path = os.path.join(self.model_dir, f"{ticker}_classifier.pkl")
        joblib.dump(self.classifier, clf_path)
        saved_files.append(clf_path)
        logger.info(f"  분류 모델 저장: {clf_path}")

        # 스케일러 저장
        scaler_path = os.path.join(self.model_dir, f"{ticker}_scaler.pkl")
        joblib.dump(self.scaler, scaler_path)
        saved_files.append(scaler_path)
        logger.info(f"  스케일러 저장: {scaler_path}")

        # 메타데이터 저장
        metadata = {
            "ticker": ticker,
            "trained_at": datetime.now().isoformat(),
            "feature_columns": self.feature_columns,
            "n_features": len(self.feature_columns),
            "regression_params": {k: str(v) for k, v in self.reg_params.items()},
            "classification_params": {k: str(v) for k, v in self.clf_params.items()},
            "regression_metrics": reg_metrics,
            "classification_metrics": clf_metrics,
            "feature_importance": importance,
        }
        meta_path = os.path.join(self.model_dir, f"{ticker}_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        saved_files.append(meta_path)
        logger.info(f"  메타데이터 저장: {meta_path}")

        return saved_files

    def is_model_saved(self, ticker: str) -> bool:
        """
        지정된 종목의 학습된 모델 파일이 존재하는지 확인합니다.

        Args:
            ticker: 종목코드

        Returns:
            bool: 모든 필수 파일(regressor, classifier, scaler, metadata)이 존재하면 True
        """
        required_files = [
            f"{ticker}_regressor.pkl",
            f"{ticker}_classifier.pkl",
            f"{ticker}_scaler.pkl",
            f"{ticker}_metadata.json",
        ]
        return all(
            os.path.exists(os.path.join(self.model_dir, f))
            for f in required_files
        )
