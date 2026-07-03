#!/usr/bin/env python3
"""
주가 예측 프로그램 (Stock Predictor) — 메인 진입점

종목명과 연도를 입력받아 네이버 뉴스 감성 분석 + 기술적 지표를 결합한
XGBoost 모델로 다음 날 주가를 예측합니다.

파이프라인:
    1. 데이터 수집 (주가 + 네이버 뉴스)
    2. 감성 분석 (KR-FinBert-SC)
    3. 전처리 (기술적 지표 생성, 데이터 병합)
    4. 모델 학습 (XGBoost 회귀 + 분류)
    5. 예측 (다음 거래일 종가 및 추세)

사용법:
    # 전체 파이프라인 실행 (학습 + 예측)
    python stock_predictor.py --stock "삼성전자" --year 2024

    # 종목코드로 실행
    python stock_predictor.py --stock "005930" --year 2024

    # 기존 모델로 예측만 수행 (학습 스킵)
    python stock_predictor.py --stock "005930" --year 2024 --skip-train

    # 커스텀 모델 저장 경로 지정
    python stock_predictor.py --stock "삼성전자" --year 2024 --model-dir ./my_models

Author: Stock Predictor Team
Version: 1.0.0
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd

# 프로젝트 루트 디렉토리를 sys.path에 추가 (모듈 임포트 보장)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.data_collector import StockDataCollector, NaverNewsCrawler
from modules.sentiment_analyzer import SentimentAnalyzer
from modules.preprocessor import DataPreprocessor
from modules.trainer import ModelTrainer
from modules.predictor import StockPredictor

# ─── 로깅 설정 ────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(verbose: bool = False) -> None:
    """
    로깅 시스템을 초기화합니다.

    Args:
        verbose: True이면 DEBUG 레벨, False이면 INFO 레벨
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # 외부 라이브러리 로깅 레벨 조정 (너무 많은 로그 방지)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)
    logging.getLogger("xgboost").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ─── 메인 오케스트레이션 ─────────────────────────────────────


class StockPredictionPipeline:
    """
    주가 예측 전체 파이프라인 오케스트레이터

    데이터 수집 → 감성 분석 → 전처리 → 학습 → 예측의
    전체 흐름을 관리합니다.

    각 단계는 독립적인 모듈 클래스에 위임되며,
    이 클래스는 흐름 제어와 에러 핸들링만 담당합니다.

    향후 FastAPI 서버에서 이 클래스를 직접 인스턴스화하여
    파이프라인을 실행할 수 있도록 설계되었습니다.

    Attributes:
        model_dir: 모델 저장 디렉토리
        max_news_pages: 월별 최대 크롤링 페이지 수
        collector: StockDataCollector 인스턴스
        crawler: NaverNewsCrawler 인스턴스
        analyzer: SentimentAnalyzer 인스턴스 (lazy init)
        preprocessor: DataPreprocessor 인스턴스
        trainer: ModelTrainer 인스턴스
        predictor: StockPredictor 인스턴스
    """

    def __init__(
        self,
        model_dir: str = "models",
        max_news_pages: int = 5,
    ):
        """
        StockPredictionPipeline 초기화

        Args:
            model_dir: 모델 파일 저장 디렉토리 (기본: "models")
            max_news_pages: 월별 최대 크롤링 페이지 수 (기본: 5)
        """
        self.model_dir = os.path.join(PROJECT_ROOT, model_dir)
        self.max_news_pages = max_news_pages

        # 모듈 인스턴스 초기화
        self.collector = StockDataCollector()
        self.crawler = NaverNewsCrawler(max_pages_per_month=max_news_pages)
        self.analyzer: Optional[SentimentAnalyzer] = None  # 필요 시 초기화 (무거운 모델)
        self.preprocessor = DataPreprocessor()
        self.trainer = ModelTrainer(model_dir=self.model_dir)
        self.predictor = StockPredictor(model_dir=self.model_dir)

    def run(
        self,
        stock_input: str,
        year: int,
        skip_train: bool = False,
    ) -> Dict[str, Any]:
        """
        전체 예측 파이프라인을 실행합니다.

        Args:
            stock_input: 종목명 또는 종목코드 (예: "삼성전자", "005930")
            year: 학습 대상 연도 (예: 2024)
            skip_train: True이면 기존 모델 사용, 학습 스킵

        Returns:
            dict: 최종 예측 결과 딕셔너리
                - ticker, target_date, predicted_trend, predicted_price,
                  avg_sentiment_score, model_metrics 등
        """
        logger.info("=" * 60)
        logger.info(f"주가 예측 파이프라인 시작: {stock_input} ({year}년)")
        logger.info("=" * 60)

        # ── Step 1: 종목 정보 해석 ──
        logger.info("\n[Step 1/6] 종목 정보 해석")
        stock_info = self.collector.resolve_ticker(stock_input)
        ticker = stock_info["ticker"]
        stock_name = stock_info["name"]
        logger.info(f"  종목: {stock_name} ({ticker}) / {stock_info['market']}")

        # ── 기존 모델 사용 (skip_train) ──
        if skip_train and self.trainer.is_model_saved(ticker):
            logger.info("\n기존 학습 모델이 존재합니다. 학습을 건너뜁니다.")
            return self._predict_with_saved_model(ticker, stock_name, year)

        # ── Step 2: 주가 데이터 수집 ──
        logger.info("\n[Step 2/6] 주가 데이터 수집")
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        stock_df = self.collector.fetch_stock_data(ticker, start_date, end_date)

        if stock_df.empty:
            raise ValueError(f"주가 데이터를 수집할 수 없습니다: {ticker} ({year}년)")

        logger.info(f"  수집 완료: {len(stock_df)} 거래일")

        # ── Step 3: 뉴스 크롤링 ──
        logger.info("\n[Step 3/6] 네이버 뉴스 크롤링")
        news_df = self.crawler.crawl_news(stock_name, year)
        logger.info(f"  크롤링 완료: {len(news_df)}건")

        # ── Step 4: 감성 분석 ──
        logger.info("\n[Step 4/6] 뉴스 감성 분석")
        if news_df.empty:
            logger.warning("  뉴스가 없어 감성 분석을 건너뜁니다.")
            sentiment_df = pd.DataFrame(
                columns=["date", "positive", "negative", "neutral", "sentiment_score"]
            )
        else:
            if self.analyzer is None:
                logger.info("  감성 분석 모델 초기화 중... (최초 1회 시 모델 다운로드)")
                self.analyzer = SentimentAnalyzer()
            sentiment_df = self.analyzer.analyze(news_df)
            logger.info(
                f"  분석 완료: {len(sentiment_df)}일, "
                f"평균 감성: {sentiment_df['sentiment_score'].mean():.3f}"
            )

        # ── Step 5: 전처리 + 학습 ──
        logger.info("\n[Step 5/6] 데이터 전처리 및 모델 학습")
        preprocessed_df = self.preprocessor.preprocess(stock_df, sentiment_df)

        if len(preprocessed_df) < 30:
            raise ValueError(
                f"학습 데이터가 부족합니다 ({len(preprocessed_df)}행). "
                f"최소 30개 이상의 거래일 데이터가 필요합니다."
            )

        train_result = self.trainer.train(preprocessed_df, ticker)
        logger.info(f"  학습 완료 — 모델 저장: {train_result['model_files']}")

        # ── Step 6: 예측 ──
        logger.info("\n[Step 6/6] 다음 거래일 주가 예측")
        self.predictor.load_model(ticker)
        prediction = self.predictor.predict_from_dataframe(
            ticker=ticker,
            df=preprocessed_df,
            stock_name=stock_name,
        )

        logger.info("\n" + "=" * 60)
        logger.info("예측 완료!")
        logger.info("=" * 60)

        return prediction

    def _predict_with_saved_model(
        self, ticker: str, stock_name: str, year: int
    ) -> Dict[str, Any]:
        """
        저장된 모델을 로드하여 최신 데이터로 예측을 수행합니다.

        skip_train 옵션 사용 시 호출됩니다.
        최근 60 거래일의 주가 데이터를 수집하여 기술적 지표를 계산하고,
        최신 뉴스의 감성 분석 결과와 함께 예측을 수행합니다.

        Args:
            ticker: 종목코드
            stock_name: 종목명
            year: 원래 요청된 연도

        Returns:
            dict: 예측 결과 딕셔너리
        """
        # 모델 로드
        self.predictor.load_model(ticker)

        # 최근 데이터 수집 (기술적 지표 계산을 위해 최근 60거래일)
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date_dt = datetime.now() - pd.Timedelta(days=90)
        start_date = start_date_dt.strftime("%Y-%m-%d")

        logger.info(f"최근 주가 데이터 수집: {start_date} ~ {end_date}")
        stock_df = self.collector.fetch_stock_data(ticker, start_date, end_date)

        if stock_df.empty:
            raise ValueError(f"최근 주가 데이터를 수집할 수 없습니다: {ticker}")

        # 감성 데이터 (빈 DataFrame으로 처리)
        sentiment_df = pd.DataFrame(
            columns=["date", "positive", "negative", "neutral", "sentiment_score"]
        )

        # 전처리 (타겟 없이 피처만 계산)
        preprocessed_df = self.preprocessor.preprocess(stock_df, sentiment_df)

        # 예측
        prediction = self.predictor.predict_from_dataframe(
            ticker=ticker,
            df=preprocessed_df,
            stock_name=stock_name,
        )

        return prediction


# ─── CLI 인터페이스 ────────────────────────────────────────


def parse_arguments() -> argparse.Namespace:
    """
    CLI 인자를 파싱합니다.

    Returns:
        argparse.Namespace: 파싱된 인자
            - stock: 종목명 또는 종목코드
            - year: 학습 대상 연도
            - skip_train: 기존 모델 사용 여부
            - model_dir: 모델 저장 디렉토리
            - max_pages: 월별 최대 크롤링 페이지 수
            - verbose: 상세 로깅 활성화
            - output: 결과 JSON 저장 경로
    """
    parser = argparse.ArgumentParser(
        prog="stock_predictor",
        description=(
            "뉴스 감성 분석 + 기술적 지표 기반 주가 예측 프로그램\n"
            "KR-FinBert-SC 감성 분석 모델과 XGBoost를 활용하여\n"
            "다음 거래일의 주가를 예측합니다."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "사용 예시:\n"
            '  python stock_predictor.py --stock "삼성전자" --year 2024\n'
            '  python stock_predictor.py --stock "005930" --year 2024 --skip-train\n'
            '  python stock_predictor.py --stock "카카오" --year 2024 --output result.json'
        ),
    )

    parser.add_argument(
        "--stock", "-s",
        type=str,
        required=True,
        help='종목명 또는 종목코드 (예: "삼성전자" 또는 "005930")',
    )
    parser.add_argument(
        "--year", "-y",
        type=int,
        default=datetime.now().year,
        help="학습 대상 연도 (예: 2026, 기본값: 현재 연도)",
    )
    parser.add_argument(
        "--skip-train",
        action="store_true",
        default=False,
        help="기존에 학습된 모델이 있으면 학습을 건너뛰고 예측만 수행",
    )
    parser.add_argument(
        "--model-dir",
        type=str,
        default="models",
        help="모델 파일 저장 디렉토리 (기본: ./models)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="월별 최대 뉴스 크롤링 페이지 수 (기본: 5, 페이지당 ~10건)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="상세 디버그 로그 출력",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="예측 결과를 JSON 파일로 저장할 경로 (기본: stdout에 출력)",
    )

    return parser.parse_args()


def print_prediction_result(result: Dict[str, Any]) -> None:
    """
    예측 결과를 보기 좋은 형식으로 출력합니다.

    Args:
        result: 예측 결과 딕셔너리
    """
    print("\n" + "━" * 50)
    print("  📊 주가 예측 결과")
    print("━" * 50)

    stock_name = result.get("stock_name", "")
    ticker = result["ticker"]
    header = f"  종목: {stock_name} ({ticker})" if stock_name else f"  종목: {ticker}"
    print(header)

    print(f"  예측 대상일: {result['target_date']}")
    print(f"  예측 추세:   {result['predicted_trend']}")
    print(f"  예측 종가:   {result['predicted_price']:,}원")
    print(f"  추세 확률:   {result.get('trend_probability', 0):.2%}")
    print(f"  감성 스코어: {result['avg_sentiment_score']:.4f}")

    # 모델 성능 요약
    metrics = result.get("model_metrics", {})
    reg_m = metrics.get("regression", {})
    clf_m = metrics.get("classification", {})

    if reg_m or clf_m:
        print("\n  📈 모델 성능 지표")
        print("  " + "─" * 40)
        if reg_m:
            print(f"  회귀 MAE:     {reg_m.get('mae', 'N/A')}")
            print(f"  회귀 RMSE:    {reg_m.get('rmse', 'N/A')}")
        if clf_m:
            print(f"  분류 Accuracy: {clf_m.get('accuracy', 'N/A')}")
            print(f"  분류 F1:       {clf_m.get('f1', 'N/A')}")

    print("━" * 50)

    # JSON 형식으로도 출력
    print("\n📋 JSON 형식:")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    """
    프로그램 메인 함수.

    CLI 인자를 파싱하고 예측 파이프라인을 실행합니다.
    """
    args = parse_arguments()

    # 로깅 설정
    setup_logging(verbose=args.verbose)

    logger.info(f"Stock Predictor v1.0.0 — 시작")

    try:
        # 파이프라인 초기화 및 실행
        pipeline = StockPredictionPipeline(
            model_dir=args.model_dir,
            max_news_pages=args.max_pages,
        )

        result = pipeline.run(
            stock_input=args.stock,
            year=args.year,
            skip_train=args.skip_train,
        )

        # 결과 출력
        print_prediction_result(result)

        # JSON 파일 저장 (--output 옵션 사용 시)
        if args.output:
            output_path = os.path.join(PROJECT_ROOT, args.output)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"예측 결과 저장 완료: {output_path}")

    except KeyboardInterrupt:
        logger.info("\n사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except FileNotFoundError as e:
        logger.error(f"파일 오류: {e}")
        logger.error("--skip-train 옵션 사용 시 먼저 학습을 수행해주세요.")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"입력 오류: {e}")
        sys.exit(1)
    except ImportError as e:
        logger.error(f"의존성 오류: {e}")
        logger.error("pip install -r requirements.txt 로 필요 패키지를 설치해주세요.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"예상치 못한 오류: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
