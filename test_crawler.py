#!/usr/bin/env python3
"""
NaverNewsCrawler 수정 후 검증 테스트
2024년 1월 삼성전자 뉴스를 단독 크롤링하여 결과를 확인합니다.
"""

import sys
import os
import logging

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 로깅 설정 (DEBUG 레벨로 상세 출력)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("urllib3").setLevel(logging.WARNING)

from modules.data_collector import NaverNewsCrawler

print("=" * 70)
print("🧪 NaverNewsCrawler 수정 후 검증 테스트")
print("=" * 70)

# ── 테스트 1: 단일 기간 크롤링 (2024년 1월) ──────────────────
print("\n📋 테스트 1: _crawl_period('삼성전자', '2024.01.01', '2024.01.31')")
print("-" * 50)

crawler = NaverNewsCrawler(max_pages_per_month=3)
news_items = crawler._crawl_period("삼성전자", "2024.01.01", "2024.01.31")

print(f"\n✅ 수집 결과: {len(news_items)}건")
if news_items:
    print("\n📰 수집된 뉴스 (처음 10건):")
    for i, item in enumerate(news_items[:10]):
        print(f"  [{i+1}] {item['date']} | {item['title'][:60]}...")
else:
    print("❌ 뉴스 0건 — 문제가 여전히 존재합니다!")

# ── 테스트 2: crawl_news 전체 호출 (1월만 빠르게) ─────────────
print("\n" + "=" * 70)
print("📋 테스트 2: crawl_news 단축 테스트 (1~2월만)")
print("-" * 50)

# 빠른 테스트를 위해 2개월만 크롤링하는 커스텀 실행
import time
import random
from datetime import datetime, timedelta

all_news = []
for month in [1, 2]:
    start_date = f"2024.{month:02d}.01"
    if month == 12:
        end_date = "2024.12.31"
    else:
        last_day = datetime(2024, month + 1, 1) - timedelta(days=1)
        end_date = last_day.strftime("%Y.%m.%d")

    print(f"\n  📅 크롤링: {start_date} ~ {end_date}")
    monthly = crawler._crawl_period("삼성전자", start_date, end_date)
    print(f"     → {len(monthly)}건 수집")
    all_news.extend(monthly)
    time.sleep(random.uniform(1.0, 2.0))

print(f"\n✅ 총 수집 결과: {len(all_news)}건")

# DataFrame으로 변환
import pandas as pd

if all_news:
    df = pd.DataFrame(all_news)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = df.drop_duplicates(subset=["title"], keep="first").reset_index(drop=True)

    print(f"   (중복 제거 후: {len(df)}건)")
    print(f"\n📊 날짜 분포:")
    print(df["date"].dt.to_period("M").value_counts().sort_index().to_string())

    print(f"\n📰 전체 수집 뉴스 목록 (최대 20건):")
    for i, row in df.head(20).iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        title = row["title"][:65]
        print(f"  [{i+1:2d}] {date_str} | {title}")
else:
    print("❌ 뉴스 0건 수집!")

print("\n" + "=" * 70)
print("🏁 검증 테스트 완료")
print("=" * 70)
