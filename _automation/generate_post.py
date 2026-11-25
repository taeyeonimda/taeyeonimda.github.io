#!/usr/bin/env python3
"""
Salesforce & IT 기술 블로그 투트랙(Two-Track) AI 자동 포스팅 스크립트
- Track A: 해외/국내 최신 기술 RSS 아티클 큐레이션 & 실무 해설
- Track B: 커리큘럼(curriculum.json) 기반 체계적 시리즈 강좌 연재
"""

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

from prompts import SYSTEM_INSTRUCTION, build_track_a_prompt, build_track_b_prompt

# 경로 설정
AUTOMATION_DIR = Path(__file__).resolve().parent
REPO_ROOT = AUTOMATION_DIR.parent
POSTS_DIR = REPO_ROOT / "_posts"
DRAFTS_DIR = REPO_ROOT / "_drafts"
CURRICULUM_PATH = AUTOMATION_DIR / "curriculum.json"
HISTORY_PATH = AUTOMATION_DIR / "posted_history.json"
SUMMARY_PATH = AUTOMATION_DIR / "last_run_summary.md"

KST = datetime.timezone(datetime.timedelta(hours=9))

# [Track A] 수집 대상 RSS 피드 목록 (우선순위 순)
RSS_FEEDS = [
    {
        "name": "Salesforce Developers Blog",
        "url": "https://developer.salesforce.com/blogs/feed",
        "main_category": "Salesforce",
        "sub_category": "Tech Insights",
    },
    {
        "name": "Salesforce Ben (Developer)",
        "url": "https://www.salesforceben.com/category/developer/feed/",
        "main_category": "Salesforce",
        "sub_category": "Best Practices",
    },
    {
        "name": "DEV Community - Salesforce",
        "url": "https://dev.to/feed/tag/salesforce",
        "main_category": "Salesforce",
        "sub_category": "Community Insights",
    },
    {
        "name": "GeekNews (긱뉴스 - IT/개발 트렌드)",
        "url": "https://feeds.feedburner.com/geeknews-feed",
        "main_category": "IT & Cloud",
        "sub_category": "Tech Trends",
    },
    {
        "name": "DEV Community - Architecture",
        "url": "https://dev.to/feed/tag/architecture",
        "main_category": "IT & Cloud",
        "sub_category": "Architecture",
    },
]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def clean_html_text(html_content: str) -> str:
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def fetch_article_body(url: str) -> str:
    """원문 URL에서 본문 텍스트를 추가로 추출합니다 (실패 시 빈 문자열 반환)."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        return clean_html_text(resp.text)[:6000]
    except Exception as exc:
        print(f"[WARN] 원문 추가 크롤링 생략 ({url}): {exc}")
        return ""


def select_track_a_article(history: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """RSS 피드를 순회하며 아직 포스팅하지 않은 최신 아티클 1개를 선택합니다."""
    posted_urls = set(history.get("posted_urls", []))

    for feed_info in RSS_FEEDS:
        feed_url = feed_info["url"]
        print(f"[Track A] RSS 확인 중: {feed_info['name']} ({feed_url})")
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:8]:
                link = entry.get("link", "").strip()
                title = entry.get("title", "").strip()
                if not link or not title or link in posted_urls:
                    continue

                summary_html = entry.get("summary", "") or entry.get("description", "")
                content_html = ""
                if "content" in entry and entry.content:
                    content_html = entry.content[0].get("value", "")

                summary_text = clean_html_text(summary_html)
                body_text = clean_html_text(content_html)
                if len(body_text) < 500:
                    fetched = fetch_article_body(link)
                    if fetched:
                        body_text = fetched

                return {
                    "title": title,
                    "url": link,
                    "summary": summary_text[:2000],
                    "content": body_text[:6000],
                    "source_name": feed_info["name"],
                    "main_category": feed_info["main_category"],
                    "sub_category": feed_info["sub_category"],
                }
        except Exception as exc:
            print(f"[WARN] RSS 파싱 실패 ({feed_info['name']}): {exc}")
            continue

    return None


def select_track_b_item(curriculum: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """curriculum.json에서 아직 완료되지 않은(completed == False) 첫 번째 주제를 선택합니다."""
    for item in curriculum:
        if not item.get("completed", False):
            return item
    return None


def make_slug(text: str, fallback: str = "tech-post") -> str:
    """파일명용 영문/숫자 슬러그를 생성합니다."""
    # 영문/숫자 단어만 추출
    ascii_words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    if ascii_words:
        slug = "-".join(ascii_words[:8])
        if len(slug) >= 4:
            return slug[:65].strip("-")
    return fallback


def sanitize_liquid_syntax(markdown_text: str) -> str:
    """
    Jekyll(Liquid) 빌드 오류 방지:
    코드 블록(``` ... ```) 내부에 `{{` 또는 `{%`가 포함되어 있으면
    해당 코드 블록을 `{% raw %}` ... `{% endraw %}`로 감싸서 Liquid 파서 충돌을 방지합니다.
    """
    if "{% raw %}" in markdown_text:
        return markdown_text

    pattern = re.compile(r"(```[\w-]*\n[\s\S]*?```)", re.MULTILINE)

    def replacer(match: re.Match) -> str:
        block = match.group(1)
        if "{{" in block or "{%" in block:
            return f"{{% raw %}}\n{block}\n{{% endraw %}}"
        return block

    return pattern.sub(replacer, markdown_text)


def strip_outer_code_fence(text: str) -> str:
    """AI 응답이 ```markdown ... ``` 으로 감싸져 있을 경우 바깥 코드 펜스를 제거합니다."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # 첫 줄 제거 (```markdown 등)
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def ensure_valid_front_matter(
    raw_md: str,
    default_title: str,
    default_categories: List[str],
    date_str: str,
) -> Tuple[str, str]:
    """
    생성된 마크다운의 YAML Front Matter를 검증 및 보정하고 (보정된 마크다운, 최종 제목)을 반환합니다.
    """
    cleaned = strip_outer_code_fence(raw_md)

    fm_match = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$", cleaned)
    if fm_match:
        fm_raw, body = fm_match.group(1), fm_match.group(2)
        try:
            fm_data = yaml.safe_load(fm_raw) or {}
        except Exception as exc:
            print(f"[WARN] Front Matter YAML 파싱 보정 실행: {exc}")
            fm_data = {}
    else:
        fm_data = {}
        body = cleaned

    title = str(fm_data.get("title") or default_title).strip().replace('"', "'")
    description = (
        str(
            fm_data.get("description")
            or f"{title}에 대한 아키텍처 분석, 실전 코드 예제 및 실무 적용 가이드입니다."
        )
        .strip()
        .replace('"', "'")
        .replace("\n", " ")
    )
    categories = fm_data.get("categories")
    if not isinstance(categories, list) or len(categories) == 0:
        categories = default_categories

    tags = fm_data.get("tags")
    if not isinstance(tags, list) or len(tags) == 0:
        tags = [c.lower().replace(" ", "-") for c in default_categories] + ["salesforce", "tech-blog"]
    tags = [str(t).strip().lower() for t in tags if str(t).strip()][:6]

    # Front Matter 재조립 (안전한 직렬화)
    cats_str = ", ".join(f'"{c}"' for c in categories[:2])
    tags_str = ", ".join(f'"{t}"' for t in tags)

    front_matter = (
        "---\n"
        f'title: "{title}"\n'
        f'description: "{description[:155]}"\n'
        f"date: {date_str}\n"
        f"categories: [{cats_str}]\n"
        f"tags: [{tags_str}]\n"
        "mermaid: true\n"
        "toc: true\n"
        "---\n\n"
    )

    safe_body = sanitize_liquid_syntax(body.strip())
    return front_matter + safe_body + "\n", title


def call_gemini(
    prompt: str,
    date_str: str,
    main_category: str,
    sub_category: str,
    model_name: str,
) -> Tuple[str, str]:
    """
    Gemini API를 호출하여 블로그 포스트 마크다운을 생성합니다.
    기본적으로 gemini-2.5-pro를 우선 시도하고, 할당량(Quota) 초과나 일시적 오류 발생 시
    gemini-2.5-flash로 자동 폴백(Fallback)하여 안정적으로 글을 생성합니다.
    반환값: (생성된 마크다운 텍스트, 실제 사용된 모델명)
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY 환경변수가 설정되어 있지 않습니다. "
            "GitHub Secrets 또는 로컬 환경변수에 GEMINI_API_KEY를 설정해 주세요."
        )

    client = genai.Client(api_key=api_key)
    system_instruction = SYSTEM_INSTRUCTION.format(
        date_str=date_str,
        main_category=main_category,
        sub_category=sub_category,
    )

    # 우선 시도할 모델 리스트 구성 (기본: gemini-2.5-pro -> gemini-2.5-flash 폴백)
    candidate_models = [model_name]
    if model_name == "gemini-2.5-pro":
        candidate_models.append("gemini-2.5-flash")

    last_error: Optional[Exception] = None
    for current_model in candidate_models:
        try:
            print(f"[AI] Gemini 모델({current_model})로 포스트 작성 시도 중...")
            response = client.models.generate_content(
                model=current_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.65,
                ),
            )
            if response.text:
                print(f"[AI] {current_model} 모델로 포스트 생성 성공!")
                return response.text, current_model
            raise RuntimeError(f"{current_model} 모델로부터 빈 응답을 받았습니다.")
        except Exception as exc:
            last_error = exc
            print(f"[WARN] {current_model} 호출 실패 ({exc}). 다음 폴백 모델로 전환을 시도합니다...")

    raise RuntimeError(f"모든 Gemini 모델 호출에 실패했습니다: {last_error}")


def write_github_outputs(outputs: Dict[str, str], summary_md: str) -> None:
    """GitHub Actions 워크플로우와 연동하기 위해 GITHUB_OUTPUT 및 GITHUB_STEP_SUMMARY를 기록합니다."""
    SUMMARY_PATH.write_text(summary_md, encoding="utf-8")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            for k, v in outputs.items():
                safe_val = str(v).replace("\n", " ").strip()
                f.write(f"{k}={safe_val}\n")

    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as f:
            f.write(summary_md + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Salesforce & IT 기술 블로그 AI 자동 포스팅 생성기")
    parser.add_argument(
        "--track",
        choices=["auto", "a", "b", "track_a", "track_b"],
        default="auto",
        help="실행할 트랙 선택: auto(자동 교차), a(해외/최신 RSS 해설), b(커리큘럼 시리즈 연재)",
    )
    parser.add_argument(
        "--topic",
        type=str,
        default="",
        help="직접 지정한 주제로 즉시 글 생성 (지정 시 커리큘럼/RSS 대신 해당 주제로 작성)",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="_posts 대신 _drafts 폴더에 초안으로 생성 (로컬 미리보기 테스트용)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API 호출 및 파일 저장 없이 선택될 주제와 프롬프트만 확인",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=os.environ.get("GEMINI_MODEL", "gemini-2.5-pro"),
        help="우선 사용할 Gemini 모델명 (기본값: gemini-2.5-pro, 한도 초과 시 gemini-2.5-flash로 자동 폴백)",
    )
    args = parser.parse_args()

    now_kst = datetime.datetime.now(KST)
    date_str = now_kst.strftime("%Y-%m-%d %H:%M:%S +0900")
    date_prefix = now_kst.strftime("%Y-%m-%d")

    history = load_json(HISTORY_PATH, {"last_track": "b", "posted_urls": [], "history": []})
    curriculum = load_json(CURRICULUM_PATH, [])

    # 트랙 결정
    track = args.track.lower().replace("track_", "")
    if track == "auto":
        # 직전 트랙과 교차 실행 (기본값: 커리큘럼 Track B 먼저 시작)
        last_track = history.get("last_track", "a")
        track = "b" if last_track == "a" else "a"

    selected_article = None
    selected_curriculum = None
    track_label = ""
    slug_hint = ""
    default_title = ""
    main_cat = "Salesforce"
    sub_cat = "Architecture"

    if args.topic.strip():
        track_label = "Custom Topic (사용자 지정 주제)"
        default_title = args.topic.strip()
        slug_hint = make_slug(default_title, f"custom-topic-{now_kst.strftime('%H%M')}")
        custom_item = {
            "series": "Special Deep Dive",
            "episode": 1,
            "title": default_title,
            "main_category": "Salesforce",
            "sub_category": "Tech Insights",
            "keywords": ["salesforce", "architecture", "best-practices"],
            "key_points": [
                f"'{default_title}'의 핵심 개념과 아키텍처 원리",
                "실무 구현 예제 코드 (Anti-Pattern vs Best Practice)",
                "성능 및 보안/Governor Limits 고려사항",
            ],
        }
        prompt = build_track_b_prompt(custom_item, date_str)
    else:
        if track == "a":
            selected_article = select_track_a_article(history)
            if not selected_article:
                print("[INFO] 새로운 RSS 아티클을 찾지 못해 Track B(커리큘럼 연재)로 자동 전환합니다.")
                track = "b"

        if track == "b":
            selected_curriculum = select_track_b_item(curriculum)
            if not selected_curriculum and not selected_article:
                print("[INFO] 남은 커리큘럼이 없어 Track A(RSS 아티클) 탐색을 시도합니다.")
                selected_article = select_track_a_article(history)
                if selected_article:
                    track = "a"

        if track == "a" and selected_article:
            track_label = f"Track A (최신 아티클 큐레이션 - {selected_article['source_name']})"
            default_title = selected_article["title"]
            main_cat = selected_article["main_category"]
            sub_cat = selected_article["sub_category"]
            slug_hint = make_slug(selected_article["title"], "tech-curation")
            prompt = build_track_a_prompt(
                article_title=selected_article["title"],
                article_url=selected_article["url"],
                article_summary=selected_article["summary"],
                article_content=selected_article["content"],
                source_name=selected_article["source_name"],
                main_category=main_cat,
                sub_category=sub_cat,
                date_str=date_str,
            )
        elif track == "b" and selected_curriculum:
            track_label = (
                f"Track B (커리큘럼 시리즈 - {selected_curriculum.get('series')} "
                f"#{selected_curriculum.get('episode')})"
            )
            default_title = selected_curriculum["title"]
            main_cat = selected_curriculum.get("main_category", "Salesforce")
            sub_cat = selected_curriculum.get("sub_category", "Apex")
            slug_hint = selected_curriculum.get("slug") or make_slug(
                selected_curriculum["title"], f"series-{selected_curriculum.get('id', 'post')}"
            )
            prompt = build_track_b_prompt(selected_curriculum, date_str)
        else:
            print("[ERROR] 생성할 수 있는 RSS 아티클이나 미완료 커리큘럼이 없습니다.")
            return 1

    print(f"[선택된 트랙] {track_label}")
    print(f"[기본 주제] {default_title}")

    if args.dry_run:
        print("\n--- [DRY RUN: 생성될 프롬프트 미리보기] ---")
        print(prompt[:1500] + "\n...(생략)...")
        return 0

    # Gemini 호출 및 마크다운 생성 (gemini-2.5-pro 우선 -> gemini-2.5-flash 폴백)
    raw_markdown, used_model = call_gemini(prompt, date_str, main_cat, sub_cat, args.model)
    final_markdown, final_title = ensure_valid_front_matter(
        raw_md=raw_markdown,
        default_title=default_title,
        default_categories=[main_cat, sub_cat],
        date_str=date_str,
    )

    # 저장 폴더 및 파일명 결정
    target_dir = DRAFTS_DIR if args.draft else POSTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{date_prefix}-{slug_hint}.md"
    target_path = target_dir / filename
    if target_path.exists():
        filename = f"{date_prefix}-{slug_hint}-{now_kst.strftime('%H%M%S')}.md"
        target_path = target_dir / filename

    target_path.write_text(final_markdown, encoding="utf-8")
    rel_path = target_path.relative_to(REPO_ROOT).as_posix()
    print(f"[완료] 포스트 파일 생성됨: {rel_path}")

    # 상태 파일 업데이트
    history["last_track"] = track
    if selected_article:
        history.setdefault("posted_urls", []).append(selected_article["url"])
    history.setdefault("history", []).append(
        {
            "date": date_str,
            "track": track_label,
            "title": final_title,
            "file": rel_path,
            "source_url": selected_article["url"] if selected_article else None,
            "curriculum_id": selected_curriculum.get("id") if selected_curriculum else None,
        }
    )
    save_json(HISTORY_PATH, history)

    if selected_curriculum:
        selected_curriculum["completed"] = True
        selected_curriculum["completed_at"] = date_str
        selected_curriculum["post_file"] = rel_path
        save_json(CURRICULUM_PATH, curriculum)

    # PR 본문 및 GitHub Step Summary용 요약 마크다운 작성
    preview_lines = final_markdown.splitlines()[:45]
    preview_snippet = "\n".join(preview_lines)
    source_info = (
        f"- **원문 출처**: [{selected_article['title']}]({selected_article['url']})\n"
        if selected_article
        else f"- **커리큘럼 ID**: `{selected_curriculum.get('id')}` ({selected_curriculum.get('series')})\n"
        if selected_curriculum
        else ""
    )

    summary_md = f"""## 🤖 AI 기술 블로그 포스트 생성 완료 (검수 대기)

- **제목**: **{final_title}**
- **트랙**: {track_label}
- **작성 AI 모델**: `{used_model}`
- **카테고리**: `{main_cat}` > `{sub_cat}`
- **생성 파일**: `{rel_path}`
- **생성 시각(KST)**: `{date_str}`
{source_info}
---

### 👀 어떻게 확인하고 배포하나요?
1. 이 PR의 **[Files changed]** 탭을 클릭하면 생성된 마크다운 전문(렌더링 뷰 포함)을 바로 읽고 수정할 수 있습니다.
2. 또한 GitHub Actions의 **`Build and Deploy` (PR 빌드 테스트)**가 자동으로 실행되어 Jekyll 빌드 오류가 없는지 검증합니다.
3. 글 내용이 마음에 들면 아래 **[Merge pull request]** 버튼을 누르세요! 병합되는 즉시 블로그(`https://taeyeonimda.github.io`)에 최종 공개 배포됩니다.

<details>
<summary>📄 생성된 포스트 앞부분 미리보기 (클릭하여 펼치기)</summary>

````markdown
{preview_snippet}
... (이하 생략 - 전체 내용은 Files changed 탭에서 확인하세요)
````

</details>
"""

    write_github_outputs(
        outputs={
            "post_path": rel_path,
            "post_title": final_title,
            "post_track": track_label,
            "post_category": f"{main_cat}/{sub_cat}",
            "post_slug": slug_hint,
        },
        summary_md=summary_md,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
