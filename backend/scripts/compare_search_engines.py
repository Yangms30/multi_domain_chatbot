"""
A/B comparison: TF-IDF vs BM25+ search engine.

Usage:
    cd backend
    python -m scripts.compare_search_engines
"""

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from services.tfidf_engine import TfidfEngine
from services.bm25_engine import Bm25Engine

# Test queries: (query, expected_title_substring_or_None)
# These are generic queries that work regardless of specific movie data
TEST_QUERIES = [
    # Genre keywords (content에 장르 포함)
    ("액션 영화", None),
    ("코미디 영화", None),
    ("공포 영화", None),
    ("드라마 영화", None),
    ("SF 영화", None),
    ("로맨스 영화", None),
    ("스릴러 영화", None),
    ("애니메이션", None),

    # Mood based
    ("무서운 영화", None),
    ("웃긴 영화", None),
    ("감동적인 영화", None),
    ("슬픈 영화", None),

    # Keywords that appear in content
    ("감독 영화", None),
    ("한국 영화", None),

    # Short/general queries
    ("영화 추천", None),
    ("재밌는 영화", None),
]

DOMAIN = "movie"


def run_comparison():
    print("=" * 80)
    print("  TF-IDF vs BM25+ Search Engine Comparison")
    print("=" * 80)

    # Build indices
    print("\n[1/4] Building indices...")
    tfidf = TfidfEngine()
    bm25 = Bm25Engine()

    t0 = time.time()
    tfidf_counts = tfidf.build_all_indices()
    tfidf_build_time = time.time() - t0

    t0 = time.time()
    bm25_counts = bm25.build_all_indices()
    bm25_build_time = time.time() - t0

    print(f"  TF-IDF: {tfidf_counts} ({tfidf_build_time:.2f}s)")
    print(f"  BM25+:  {bm25_counts} ({bm25_build_time:.2f}s)")

    if DOMAIN not in tfidf_counts or DOMAIN not in bm25_counts:
        print(f"\n  ERROR: No '{DOMAIN}' domain data found. Run kobis_collector first.")
        return

    # Add dynamic title-based queries from actual data
    print("\n[2/4] Adding dynamic queries from indexed data...")
    dynamic_queries = []
    if DOMAIN in tfidf._indices:
        docs = tfidf._indices[DOMAIN]["documents"]
        korean_docs = [d for d in docs if any('\uac00' <= c <= '\ud7a3' for c in d["title"])]
        import random
        random.seed(42)
        sample = random.sample(korean_docs, min(8, len(korean_docs)))
        for d in sample:
            dynamic_queries.append((d["title"], d["title"]))
        # Also add partial title queries
        for d in sample[:3]:
            if len(d["title"]) > 3:
                dynamic_queries.append((d["title"][:3], d["title"]))
        print(f"  Added {len(dynamic_queries)} queries from {len(korean_docs)} Korean titles")

    all_queries = list(TEST_QUERIES) + dynamic_queries

    # Run queries
    print(f"\n[3/4] Running {len(all_queries)} queries...\n")

    tfidf_times = []
    bm25_times = []
    tfidf_exact_hits = 0
    bm25_exact_hits = 0
    tfidf_total_scores = []
    bm25_total_scores = []
    exact_count = 0

    header = f"{'Query':<25} | {'TF-IDF Top 3':<40} | {'BM25+ Top 3':<40}"
    sep = "-" * 25 + "-+-" + "-" * 40 + "-+-" + "-" * 40
    print(header)
    print(sep)

    for query, expected in all_queries:
        # TF-IDF
        t0 = time.time()
        tfidf_results = tfidf.search(query, DOMAIN) or []
        tfidf_time = (time.time() - t0) * 1000
        tfidf_times.append(tfidf_time)

        # BM25+
        t0 = time.time()
        bm25_results = bm25.search(query, DOMAIN) or []
        bm25_time = (time.time() - t0) * 1000
        bm25_times.append(bm25_time)

        # Format results
        def fmt_results(results, max_items=3):
            if not results:
                return "(no results)"
            parts = []
            for r in results[:max_items]:
                title = r["title"][:15]
                parts.append(f"{title} ({r['score']:.2f})")
            return " | ".join(parts)

        tfidf_str = fmt_results(tfidf_results)
        bm25_str = fmt_results(bm25_results)

        # Track top scores
        if tfidf_results:
            tfidf_total_scores.append(tfidf_results[0]["score"])
        if bm25_results:
            bm25_total_scores.append(bm25_results[0]["score"])

        # Exact match check
        if expected:
            exact_count += 1
            if tfidf_results and expected in tfidf_results[0]["title"]:
                tfidf_exact_hits += 1
            if bm25_results and expected in bm25_results[0]["title"]:
                bm25_exact_hits += 1

        q_display = query[:23] + ".." if len(query) > 25 else query
        print(f"{q_display:<25} | {tfidf_str:<40} | {bm25_str:<40}")

    # Summary
    print("\n" + "=" * 80)
    print("  Summary")
    print("=" * 80)

    avg_tfidf_score = sum(tfidf_total_scores) / len(tfidf_total_scores) if tfidf_total_scores else 0
    avg_bm25_score = sum(bm25_total_scores) / len(bm25_total_scores) if bm25_total_scores else 0
    avg_tfidf_time = sum(tfidf_times) / len(tfidf_times) if tfidf_times else 0
    avg_bm25_time = sum(bm25_times) / len(bm25_times) if bm25_times else 0

    print(f"\n  {'Metric':<30} {'TF-IDF':>12} {'BM25+':>12} {'Winner':>10}")
    print(f"  {'-' * 30} {'-' * 12} {'-' * 12} {'-' * 10}")

    w = "BM25+" if avg_bm25_score > avg_tfidf_score else "TF-IDF"
    print(f"  {'Avg top score':<30} {avg_tfidf_score:>12.3f} {avg_bm25_score:>12.3f} {w:>10}")

    w = "BM25+" if avg_bm25_time < avg_tfidf_time else "TF-IDF"
    print(f"  {'Avg query time (ms)':<30} {avg_tfidf_time:>12.2f} {avg_bm25_time:>12.2f} {w:>10}")

    w = "BM25+" if bm25_exact_hits > tfidf_exact_hits else ("TF-IDF" if tfidf_exact_hits > bm25_exact_hits else "Tie")
    print(f"  {'Exact title match':<30} {tfidf_exact_hits:>9}/{exact_count:>2} {bm25_exact_hits:>9}/{exact_count:>2} {w:>10}")

    print(f"  {'Index build time (s)':<30} {tfidf_build_time:>12.2f} {bm25_build_time:>12.2f}")
    print(f"  {'Results with hits':<30} {len(tfidf_total_scores):>9}/{len(all_queries):>2} {len(bm25_total_scores):>9}/{len(all_queries):>2}")

    print()


if __name__ == "__main__":
    run_comparison()
