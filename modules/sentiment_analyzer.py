"""
금융 감성 분석 모듈 (NLP Sentiment Analysis Module)

Hugging Face의 한국어 금융 특화 사전학습 모델(KR-FinBert-SC)을 활용하여
뉴스 텍스트의 긍정/부정/중립 감성 스코어를 산출합니다.

Classes:
    SentimentAnalyzer: 한국어 금융 뉴스 감성 분석기

Usage:
    >>> analyzer = SentimentAnalyzer()
    >>> sentiment_df = analyzer.analyze(news_df)
    >>> # sentiment_df: date, positive, negative, neutral, sentiment_score
"""

import logging
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 감성 레이블 정규화 매핑 (다양한 모델 출력 대응)
LABEL_MAP_POSITIVE = {"positive", "긍정", "pos", "label_2", "2"}
LABEL_MAP_NEGATIVE = {"negative", "부정", "neg", "label_0", "0"}
LABEL_MAP_NEUTRAL = {"neutral", "중립", "neu", "label_1", "1"}


class SentimentAnalyzer:
    """
    한국어 금융 뉴스 감성 분석 클래스

    Hugging Face의 사전 학습된 한국어 금융 특화 모델을 로드하여
    뉴스 텍스트를 긍정(positive), 부정(negative), 중립(neutral)으로
    분류하고 일자별 평균 감성 스코어를 산출합니다.

    Attributes:
        model_name: Hugging Face 모델 이름
        pipeline: 로드된 감성 분류 파이프라인
        batch_size: 배치 처리 크기

    Methods:
        analyze: 뉴스 DataFrame을 입력받아 일자별 감성 스코어 DataFrame 반환
        analyze_texts: 텍스트 리스트의 감성 스코어 리스트 반환
    """

    # 모델 우선순위 (첫 번째 실패 시 다음 모델 시도)
    DEFAULT_MODELS = [
        "snunlp/KR-FinBert-SC",
        "nlp04/korean_sentiment_analysis_kcelectra",
    ]

    def __init__(
        self,
        model_name: Optional[str] = None,
        batch_size: int = 32,
        device: Optional[str] = None,
    ):
        """
        SentimentAnalyzer 초기화

        Args:
            model_name: Hugging Face 모델 이름.
                None이면 DEFAULT_MODELS 리스트에서 순차 시도.
            batch_size: 배치 처리 크기 (기본: 32).
                GPU 메모리에 따라 조정 가능.
            device: 추론 디바이스. None이면 자동 감지
                (CUDA 가용 시 GPU, 아니면 CPU).
        """
        self.batch_size = batch_size
        self.model_name = model_name
        self.pipeline = None

        self._load_model(model_name, device)

    def _load_model(self, model_name: Optional[str], device: Optional[str]) -> None:
        """
        감성 분류 모델을 로드합니다.

        지정된 모델이 없으면 DEFAULT_MODELS 리스트에서 순차적으로 시도합니다.
        모든 모델 로드가 실패하면 RuntimeError를 발생시킵니다.

        Args:
            model_name: 로드할 모델 이름 (None이면 기본 목록에서 시도)
            device: 추론 디바이스
        """
        try:
            from transformers import pipeline as hf_pipeline
        except ImportError:
            raise ImportError(
                "transformers 라이브러리가 설치되지 않았습니다. "
                "pip install transformers torch 로 설치해주세요."
            )

        # 디바이스 설정
        if device is None:
            try:
                import torch
                device_idx = 0 if torch.cuda.is_available() else -1
            except ImportError:
                device_idx = -1
        else:
            device_idx = int(device) if device.isdigit() else -1

        models_to_try = [model_name] if model_name else self.DEFAULT_MODELS

        for name in models_to_try:
            try:
                logger.info(f"감성 분석 모델 로드 시도: {name}")
                self.pipeline = hf_pipeline(
                    "text-classification",
                    model=name,
                    top_k=None,         # 모든 레이블 스코어 반환
                    device=device_idx,
                    truncation=True,
                    max_length=512,
                )
                self.model_name = name
                logger.info(f"감성 분석 모델 로드 성공: {name}")
                return
            except Exception as e:
                logger.warning(f"모델 '{name}' 로드 실패: {e}")
                continue

        raise RuntimeError(
            f"감성 분석 모델을 로드할 수 없습니다. 시도한 모델: {models_to_try}"
        )

    def analyze(self, news_df: pd.DataFrame) -> pd.DataFrame:
        """
        뉴스 DataFrame을 입력받아 일자별 감성 스코어를 산출합니다.

        개별 뉴스 기사의 감성을 분석한 후, 같은 날짜의 뉴스들을
        평균하여 일별 감성 스코어를 계산합니다.

        Args:
            news_df: 뉴스 데이터 DataFrame
                필수 컬럼: date (datetime), title (str)

        Returns:
            pd.DataFrame: 일자별 감성 스코어
                컬럼:
                - date (datetime): 날짜
                - positive (float): 긍정 확률 평균 (0~1)
                - negative (float): 부정 확률 평균 (0~1)
                - neutral (float): 중립 확률 평균 (0~1)
                - sentiment_score (float): 순감성 지수 (positive - negative, -1~1)
                - news_count (int): 해당 일자의 뉴스 건수
        """
        if news_df.empty:
            logger.warning("분석할 뉴스가 없습니다. 빈 DataFrame을 반환합니다.")
            return pd.DataFrame(
                columns=["date", "positive", "negative", "neutral", "sentiment_score", "news_count"]
            )

        logger.info(f"감성 분석 시작: {len(news_df)}건의 뉴스")

        # 개별 뉴스 감성 분석
        texts = news_df["title"].tolist()
        scores = self.analyze_texts(texts)

        # 결과를 원본 DataFrame에 병합
        analysis_df = news_df[["date"]].copy()
        analysis_df["positive"] = [s["positive"] for s in scores]
        analysis_df["negative"] = [s["negative"] for s in scores]
        analysis_df["neutral"] = [s["neutral"] for s in scores]
        analysis_df["sentiment_score"] = [s["sentiment_score"] for s in scores]

        # 일자별 평균 집계
        daily_sentiment = (
            analysis_df.groupby(analysis_df["date"].dt.date)
            .agg(
                positive=("positive", "mean"),
                negative=("negative", "mean"),
                neutral=("neutral", "mean"),
                sentiment_score=("sentiment_score", "mean"),
                news_count=("positive", "count"),
            )
            .reset_index()
        )
        daily_sentiment["date"] = pd.to_datetime(daily_sentiment["date"])

        logger.info(
            f"감성 분석 완료: {len(daily_sentiment)}일 분석 "
            f"(평균 sentiment_score: {daily_sentiment['sentiment_score'].mean():.3f})"
        )
        return daily_sentiment

    def analyze_texts(self, texts: List[str]) -> List[Dict[str, float]]:
        """
        텍스트 리스트의 감성 스코어를 분석합니다.

        배치 단위로 모델에 입력하여 효율적으로 처리합니다.

        Args:
            texts: 분석할 텍스트 리스트

        Returns:
            list[dict]: 각 텍스트의 감성 스코어 딕셔너리 리스트
                각 딕셔너리 키: positive, negative, neutral, sentiment_score
        """
        results: List[Dict[str, float]] = []

        # 빈 텍스트 또는 None 전처리
        cleaned_texts = [
            str(t).strip() if t and str(t).strip() else "중립"
            for t in texts
        ]

        # 배치 처리
        for i in range(0, len(cleaned_texts), self.batch_size):
            batch = cleaned_texts[i : i + self.batch_size]

            try:
                batch_results = self.pipeline(batch)

                for item_scores in batch_results:
                    parsed = self._parse_scores(item_scores)
                    results.append(parsed)

            except Exception as e:
                logger.warning(f"배치 처리 오류 (인덱스 {i}~{i+len(batch)}): {e}")
                # 오류 발생 시 중립 스코어로 대체
                for _ in batch:
                    results.append(
                        {"positive": 0.33, "negative": 0.33, "neutral": 0.34, "sentiment_score": 0.0}
                    )

        return results

    @staticmethod
    def _parse_scores(scores: list) -> Dict[str, float]:
        """
        모델 출력 스코어를 정규화된 딕셔너리로 변환합니다.

        다양한 모델의 출력 레이블 형식을 통일된 형태로 변환합니다.
        (예: "LABEL_0"→"negative", "긍정"→"positive" 등)

        Args:
            scores: 모델 출력 레이블-스코어 리스트
                예: [{'label': 'positive', 'score': 0.8}, ...]

        Returns:
            dict: {positive, negative, neutral, sentiment_score}
        """
        result = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}

        for item in scores:
            label = str(item["label"]).lower().strip()
            score = float(item["score"])

            if label in LABEL_MAP_POSITIVE:
                result["positive"] = score
            elif label in LABEL_MAP_NEGATIVE:
                result["negative"] = score
            elif label in LABEL_MAP_NEUTRAL:
                result["neutral"] = score
            else:
                logger.debug(f"알 수 없는 레이블: {label}")

        # 순감성 지수: 긍정 - 부정 (범위: -1.0 ~ 1.0)
        result["sentiment_score"] = result["positive"] - result["negative"]

        return result
