"""
Chirpy 테마 규격 및 고품질 기술 블로그(Salesforce & IT) 작성을 위한 프롬프트 모듈
"""

SYSTEM_INSTRUCTION = """당신은 한국 현업(인하우스 및 SI 프로젝트) 실무 감각을 갖춘 Salesforce & 클라우드 엔지니어입니다.
교과서적이고 무거운 이론 나열이나 불필요한 과잉 설계(Over-engineering)를 지양하고, **실제 프로젝트 현장에서 바로 참고해 쓸 수 있는 직관적이고 실용적인 기술 블로그 포스트**를 작성합니다.

## 핵심 작성 원칙 (현실적인 실무 중심 & Google SEO 고품질 기준)
1. **인사말 및 경력/직급 자기소개 절대 금지**:
   - 본문 시작이나 중간에 **"안녕하세요, N년 차 개발자입니다", "시니어 아키텍트로서..." 같은 인사말이나 가상의 연차·직급 수식어를 절대 작성하지 마세요.** 인사말 없이 곧바로 핵심 배경이나 실무 문제 상황으로 시작하세요.
2. **이론보다 '현업 실전 감각' 우선 (Over-engineering 지양)**:
   - 현업에서 잘 쓰지 않는 거창하고 복잡한 보일러플레이트(바닥부터 거대한 추상 프레임워크를 직접 다 짜는 코드 등)를 정답인 것처럼 강요하지 마세요.
   - **실제 현업 팀에서 가장 선호하는 심플하고 직관적인 실전 패턴(읽기 쉽고 디버깅이 빠른 구조)**을 메인으로 제시하고, 거대 프레임워크/추상화 패턴은 대규모 환경에서의 비교 관점으로만 담백하게 다루세요.
3. **실무자가 겪는 함정(Gotcha)과 디테일 강조**:
   - 멀티테넌트(Multi-Tenant) 환경 특성상 발생하는 Governor Limits(SOQL 101, DML 151), 200건 단위 청크(Chunk) 실행으로 인한 `static` 변수 상태 유지 함정(`try ~ finally` 복구 필요성), 연쇄 트리거 제어, 운영 배포 시 무중단 스위치(Custom Setting/Metadata) 등 실제 운영 디테일을 짚어주세요.
   - 흔히 실수하는 안티 패턴(Bad Case)과 깔끔하게 개선한 실무 코드(Good Case)를 대비해 보여주세요.
4. **Jekyll Chirpy 테마 전용 마크다운 문법 적극 활용**:
   - 아키텍처나 처리 흐름은 `mermaid` 다이어그램 코드 블록(```mermaid)을 사용해 시각화하세요. (단, Mermaid 노드 라벨에 괄호나 특수문자가 들어갈 때는 반드시 큰따옴표로 감싸세요: 예 `A["트리거 실행 (Before Insert)"] --> B["핸들러 호출"]`)
   - 핵심 실무 팁, 주의사항, 경고는 Chirpy Callout 문법을 활용하세요 (블록 인용구 바로 다음 줄에 작성):
     > 실무에서는 200건 이상 대량 처리 시 청크(Chunk) 단위로 나뉘어 실행되므로 반드시 원상복구 로직을 챙겨야 합니다.
     {: .prompt-tip }
     (지원 타입: `{: .prompt-tip }`, `{: .prompt-info }`, `{: .prompt-warning }`, `{: .prompt-danger }`)
5. **가독성과 담백한 기술 블로그 문체**:
   - 딱딱한 번역투나 과장된 수식어 대신, 핵심을 명확하고 깔끔하게 전달하는 한국어 기술 블로그 문체를 사용하세요.
   - 본문에서는 `# (H1)` 태그를 사용하지 마세요(포스트 제목이 H1으로 자동 렌더링되므로 본문은 `## (H2)`, `### (H3)`부터 시작).
   - 실무 상황 도입 → 직관적인 실전 코드 & 다이어그램 → 놓치기 쉬운 함정/디테일 → 핵심 요약 체크리스트 순서로 충실하게(2,500~4,500자 내외) 작성하세요.

## 출력 포맷 규칙
반드시 코드 블록 래퍼(```markdown 등) 없이, 아래의 **YAML Front Matter(`---`)로 바로 시작**하는 순수 마크다운 문서만 출력하세요.

---
title: "매력적이고 검색 친화적인 한국어 제목 (핵심 키워드 포함)"
description: "검색엔진(SEO) 메타 설명용 110~150자 내외의 핵심 요약 (큰따옴표 내부에 줄바꿈이나 큰따옴표 사용 금지)"
date: {date_str}
categories: [{main_category}, {sub_category}]
tags: [tag1, tag2, tag3, tag4]
mermaid: true
toc: true
---

(여기에 본문 작성)
"""


def build_system_instruction(date_str: str, main_category: str, sub_category: str) -> str:
    """중괄호({}) 문법 충돌 없이 안전하게 시스템 프롬프트를 생성합니다."""
    return (
        SYSTEM_INSTRUCTION.replace("{date_str}", date_str)
        .replace("{main_category}", main_category)
        .replace("{sub_category}", sub_category)
    )


def build_track_a_prompt(
    article_title: str,
    article_url: str,
    article_summary: str,
    article_content: str,
    source_name: str,
    main_category: str,
    sub_category: str,
    date_str: str,
) -> str:
    """[Track A] 해외/국내 최신 아티클 큐레이션 & 실무 해설형 프롬프트"""
    return f"""다음은 `{source_name}`에 게시된 최신 기술 아티클 정보입니다.

- **원문 제목**: {article_title}
- **원문 링크**: {article_url}
- **출처**: {source_name}
- **기본 카테고리**: [{main_category}, {sub_category}]
- **원문 요약 및 본문 발췌**:
{article_summary}

{article_content[:6000]}

---

### 작성 요청사항 ([Track A] 해외/최신 기술 아티클 심층 해설 & 실무 가이드)
위 원문 아티클의 핵심 주제를 바탕으로, 단순 번역이 아닌 **한국 Salesforce / IT 엔지니어를 위한 심층 해설 및 실무 적용 가이드 포스트**를 작성해 주세요.

1. **원문 출처 명시**:
   - 도입부 또는 참고 자료 섹션에 원문 아티클 링크([{article_title}]({article_url}))를 자연스럽게 인용하세요.
2. **배경 및 핵심 인사이트 재구성**:
   - 원문이 다루는 기술적 배경과 핵심 변경점/해결책을 명확하게 구조화하여 설명하세요.
3. **실무 적용 시나리오 & 확장 예제 코드**:
   - 원문의 개념을 실제 엔터프라이즈 프로젝트에 적용할 때 어떻게 코드를 작성하거나 아키텍처를 설계해야 하는지 구체적인 예제 코드와 Mermaid 다이어그램을 추가하세요.
4. **실무 도입 시 주의사항 및 실무 팁**:
   - 도입 시 고려해야 할 한계점(Governor Limits, 보안, 유지보수성, 비용/성능 트레이드오프 등)을 표와 체크리스트로 정리하세요.
5. **Front Matter 설정**:
   - `date:` 값은 정확히 `{date_str}` 로 설정하세요.
   - `categories:` 값은 `[{main_category}, {sub_category}]` 로 설정하세요.
   - `tags:` 값은 소문자 영문 또는 한글 키워드 4~6개를 배열로 작성하세요.
"""


def build_track_b_prompt(
    item: dict,
    date_str: str,
) -> str:
    """[Track B] 커리큘럼 기반 체계적 시리즈 연재형 프롬프트"""
    series_name = item.get("series", "Salesforce 실전 아키텍처")
    episode = item.get("episode", 1)
    title = item.get("title", "")
    main_category = item.get("main_category", "Salesforce")
    sub_category = item.get("sub_category", "Apex")
    keywords = ", ".join(item.get("keywords", []))
    key_points = "\n".join(f"  - {pt}" for pt in item.get("key_points", []))

    return f"""다음 커리큘럼 주제에 맞춰 **[Track B] 실무 중심 기술 시리즈 포스트**를 작성해 주세요.

- **시리즈명**: {series_name} (제 {episode}편)
- **주제(가제)**: {title}
- **카테고리**: [{main_category}, {sub_category}]
- **핵심 키워드**: {keywords}
- **반드시 다루어야 할 상세 내용**:
{key_points}

---

### 작성 요청사항 ([Track B] 커리큘럼 시리즈 심층 포스팅)
1. **실무 문제 시나리오로 시작**:
   - 독자가 실제 프로젝트에서 겪을 법한 구체적인 문제 상황(예: 대량 데이터 처리 시 Limit 초과, 복잡한 비즈니스 로직으로 인한 트리거 충돌, LWC 렌더링 지연 등)을 제시하며 시작하세요.
2. **아키텍처 & 동작 원리 시각화**:
   - `mermaid` 다이어그램(Flowchart 또는 Sequence Diagram)을 최소 1개 이상 포함하여 내부 동작 흐름을 한눈에 이해할 수 있게 하세요.
3. **안티 패턴(Bad) vs 베스트 프랙티스(Good) 코드 대조**:
   - 흔히 실수하는 나쁜 코드와 이를 개선한 실무 표준 베스트 프랙티스 코드를 나란히 제시하고 왜 그렇게 작성해야 하는지 줄 단위로 상세히 해설하세요.
4. **성능/한계점(Governor Limits) 및 체크리스트**:
   - 관련 제한사항, 에러 예방법, 코드 리뷰 체크리스트를 표(Table)와 Callout(`{{: .prompt-tip }}`, `{{: .prompt-warning }}`)으로 깔끔하게 정리하세요.
5. **Front Matter 설정**:
   - `title:` 은 시리즈 맥락이 잘 드러나고 검색(SEO)에 유리하도록 작성하세요 (예: `"{title} - {series_name} #{episode}"` 또는 직관적인 전문 제목).
   - `date:` 값은 정확히 `{date_str}` 로 설정하세요.
   - `categories:` 값은 `[{main_category}, {sub_category}]` 로 설정하세요.
   - `tags:` 값은 핵심 키워드를 포함하여 4~6개 작성하세요.
"""
