"""
stock_predictor.modules 패키지

주가 예측 프로그램의 핵심 모듈들을 제공합니다.

Modules:
    data_collector: 주가 데이터 수집 및 네이버 뉴스 크롤링
    sentiment_analyzer: 한국어 금융 감성 분석 (KR-FinBert-SC)
    preprocessor: 데이터 병합, 기술적 지표 생성, 전처리
    trainer: XGBoost 모델 학습 및 직렬화
    predictor: 학습된 모델 기반 추론
"""

from .data_collector import StockDataCollector, NaverNewsCrawler
from .sentiment_analyzer import SentimentAnalyzer
from .preprocessor import DataPreprocessor
from .trainer import ModelTrainer
from .predictor import StockPredictor

__all__ = [
    "StockDataCollector",
    "NaverNewsCrawler",
    "SentimentAnalyzer",
    "DataPreprocessor",
    "ModelTrainer",
    "StockPredictor",
]
