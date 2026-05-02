"""
서울과기대신문 기사 크롤러 + TF-IDF 키워드 추출
https://times.seoultech.ac.kr

사용법: python crawler.py
결과: articles.json (검색 웹사이트용 — 크롤링 후 재실행 불필요)
"""

import sys
import json
import time
import re
import os
import math
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://times.seoultech.ac.kr"

CATEGORIES = [
    {"id": 44, "name": "학내보도", "parent": "보도"},
    {"id": 43, "name": "심층",    "parent": "보도"},
    {"id":  4, "name": "기획",    "parent": "기획"},
    {"id": 30, "name": "시사",    "parent": "시사"},
    {"id":  7, "name": "문화",    "parent": "문화"},
    {"id": 34, "name": "인터뷰",  "parent": "인터뷰"},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
OUTPUT_FILE = "articles.json"
DELAY = 0.5

# 한국어 불용어
STOPWORDS = {
    '이다','있다','하다','되다','않다','없다','같다','보다','주다','받다','갖다',
    '이번','지난','올해','이후','이전','현재','최근','이날','당시','지금',
    '우리','위해','대한','통해','따라','관련','해당','이에','이로','이를',
    '대학','서울','학생','기자','씨','교수','학교','과기대','우리대학',
    '했다','됐다','있어','없어','한다','한편','또한','이미','이후','이전',
    '더욱','함께','먼저','가장','모두','바로','만약','정도','경우','이상',
    '오는','오후','오전','지난해','학번','취재','기사','신문','발행',
    '진행','개최','예정','계획','시작','완료','추진','실시','마련',
    '것이','것을','것은','것도','것과','것에','이라','이고','이며',
    '수있','수도','수가','수를','하고','하는','하여','하며','하면',
    '이와','이어','이번','이런','이같','그런','그것','그는','그가',
    '있는','있고','있지','있을','없는','없고','없이','없을',
    '말했','밝혔','전했','설명','강조','지적','제안','요구','촉구',
    '통해','위해','대해','에게','으로','에서','부터','까지','에는',
    '등을','등이','등의','등에','등도','등을','등과',
    '이라고','이라며','이라는','이라면','라고','라며','라는','라면',
    '하겠다','됩니다','합니다','있습니다','없습니다','했습니다','됩니다',
}


# ─── 크롤링 ───────────────────────────────────────────────────────────

def get_soup(url, params=None):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"  ⚠ 요청 실패: {url} — {e}", file=sys.stderr)
        return None


def get_total_pages(category_id):
    soup = get_soup(f"{BASE_URL}/reports", params={"category": category_id, "page": 1})
    if not soup:
        return 1
    bbs = soup.find("div", class_="bbs_list")
    if not bbs:
        return 1
    m = re.search(r'\((\d+)건\)', bbs.text)
    if m:
        total = int(m.group(1))
        return (total + 14) // 15
    return 1


def get_article_ids_from_page(category_id, page):
    soup = get_soup(f"{BASE_URL}/reports", params={"category": category_id, "page": page})
    if not soup:
        return []
    bbs = soup.find("div", class_="bbs_list")
    if not bbs:
        return []
    seen, unique = set(), []
    for a in bbs.find_all("a", href=True):
        m = re.search(r'idx=(\d+)', a["href"])
        if m:
            idx = int(m.group(1))
            if idx not in seen:
                seen.add(idx)
                unique.append(idx)
    return unique


def fetch_article(idx, category):
    url = f"{BASE_URL}/reports/?idx={idx}&category={category['id']}"
    soup = get_soup(url)
    if not soup:
        return None

    bbs = soup.find("div", class_="bbs_view")
    if not bbs:
        return None

    title_div = bbs.find("div", class_="title")
    text_div  = bbs.find("div", class_="text")
    if not title_div:
        return None

    lines = [l.strip() for l in title_div.get_text("\n").split("\n") if l.strip()]
    title    = lines[0] if lines else ""
    reporter = next((l.replace("기자","").strip().rstrip(",") for l in lines if "기자" in l), "")
    date     = next((m.group(0) for l in lines for m in [re.search(r'\d{4}\.\d{2}\.\d{2}', l)] if m), "")
    issue    = next((m.group(0) for l in lines for m in [re.search(r'(\d+)호', l)] if m), "")
    content  = re.sub(r'\s+', ' ', text_div.get_text(" ").strip()) if text_div else ""

    return {
        "idx":         idx,
        "url":         url,
        "category_id": category["id"],
        "category":    category["name"],
        "section":     category["parent"],
        "title":       title,
        "reporter":    reporter,
        "date":        date,
        "issue":       issue,
        "content":     content,
        "keywords":    [],  # TF-IDF 계산 후 채워짐
    }


def crawl_all():
    all_articles = []
    existing_ids = set()

    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            all_articles = json.load(f)
        existing_ids = {a["idx"] for a in all_articles}
        print(f"기존 데이터 {len(all_articles)}개 로드", file=sys.stderr)

    for cat in CATEGORIES:
        print(f"\n[{cat['name']}] 목록 수집 중...", file=sys.stderr)
        total_pages = get_total_pages(cat["id"])
        print(f"  총 {total_pages}페이지", file=sys.stderr)
        time.sleep(DELAY)

        idx_list = []
        for page in range(1, total_pages + 1):
            ids = get_article_ids_from_page(cat["id"], page)
            idx_list.extend(ids)
            time.sleep(DELAY)

        new_ids = [i for i in idx_list if i not in existing_ids]
        print(f"  신규 {len(new_ids)}개 수집 시작...", file=sys.stderr)

        for i, idx in enumerate(new_ids, 1):
            art = fetch_article(idx, cat)
            if art and art["title"]:
                all_articles.append(art)
                existing_ids.add(idx)
            if i % 20 == 0:
                print(f"  {i}/{len(new_ids)} 완료...", file=sys.stderr)
                with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                    json.dump(all_articles, f, ensure_ascii=False, indent=2)
            time.sleep(DELAY)

        print(f"  [{cat['name']}] 완료", file=sys.stderr)

    return all_articles


# ─── TF-IDF 키워드 추출 ──────────────────────────────────────────────

def tokenize(text):
    words = re.findall(r'[가-힣]{2,6}', text)
    return [w for w in words if w not in STOPWORDS and len(w) >= 2]


def compute_keywords(articles, top_n=20):
    print("\nTF-IDF 키워드 계산 중...", file=sys.stderr)

    # Document frequency
    df = Counter()
    tokenized_docs = []
    for a in articles:
        # 제목에 3배 가중치
        words = tokenize((a.get("title", "") + " ") * 3 + a.get("content", ""))
        tokenized_docs.append(words)
        df.update(set(words))

    N = len(articles)

    for i, a in enumerate(articles):
        tf = Counter(tokenized_docs[i])
        tfidf = {}
        for word, count in tf.items():
            idf = math.log((N + 1) / (df[word] + 1)) + 1
            tfidf[word] = round(count * idf, 3)

        top_kw = sorted(tfidf.items(), key=lambda x: -x[1])[:top_n]
        a["keywords"] = [{"word": w, "score": s} for w, s in top_kw]

    print(f"키워드 계산 완료 ({N}개 기사)", file=sys.stderr)
    return articles


# ─── 메인 ────────────────────────────────────────────────────────────

def main():
    articles = crawl_all()
    articles = compute_keywords(articles)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 완료! {len(articles)}개 기사 → {OUTPUT_FILE}", file=sys.stderr)
    print("이제 index.html을 서버로 열면 검색 가능합니다.", file=sys.stderr)
    print("  python -m http.server 8080", file=sys.stderr)


if __name__ == "__main__":
    main()
