# 🚀 Salesforce & IT 기술 블로그 AI 자동화 구축 기획서 (핸드오프 문서)

이 문서는 `C:\vsspace\taeyeonimda.github.io` 프로젝트를 워크스페이스로 추가한 뒤, **다음 대화에서 바로 복사해서 전달하거나 참고할 수 있도록** 지금까지 나눈 대화의 핵심 설계 내용을 정리한 문서입니다.

---

## 1. 프로젝트 기본 정보
- **로컬 경로**: `C:\vsspace\taeyeonimda.github.io`
- **GitHub 저장소**: `https://github.com/taeyeonimda/taeyeonimda.github.io.git`
- **블로그 프레임워크 & 테마**: **Jekyll (`jekyll-theme-chirpy` 테마)**
  - *참고*: Chirpy 테마는 다크모드, 카테고리/태그 계층 구조, 코드 하이라이팅, 목차(TOC), SEO, Google Analytics 및 AdSense 연동이 가장 잘 되어 있는 개발자용 인기 테마입니다.

---

## 2. 핵심 목표 및 콘텐츠 전략

단순히 AI에게 얕은 글을 쓰게 하는 양산형 방식(저품질 위험)을 피하고, **검색엔진 최적화(Google SEO)와 향후 구글 애드센스(Google AdSense) 승인**까지 통과할 수 있는 고품질의 **투트랙(Two-Track) 하이브리드 자동화**로 구축합니다.

### 📌 주요 다루는 분야
1. **Salesforce 개발 (메인)**
   - Apex, LWC (Lightning Web Components), SOQL/SOSL, Flow, Governor Limits, 아키텍처 및 디자인 패턴, 최신 Release Notes, 통합(Integration) 등
2. **일반 IT & 개발 기술 (서브)**
   - 클라우드/아키텍처, Git/CI·CD, AI 활용 개발 트렌드, 백엔드/프론트엔드 핵심 기술 등

### 📌 투트랙(Two-Track) 글 생성 방식
1. **[Track A] 해외 최신 아티클 큐레이션 & 실무 해설형**
   - **방식**: 해외 유수의 Salesforce 영문 블로그(Salesforce Developers Blog, Salesforce Ben 등) 및 IT 기술 RSS(GeekNews, Dev.to 등)에서 최신 아티클을 수집.
   - **가공**: 단순 번역이 아닌 **"핵심 요약 + 한국 Salesforce/IT 개발자 관점의 실무 적용 팁 + 추가 예제 코드 및 주의사항"** 형태로 재구성하여 고유 가치 창출.
2. **[Track B] 체계적인 시리즈 연재형 (커리큘럼 기반)**
   - **방식**: 미리 세분화해 둔 커리큘럼(`curriculum.json`, 예: *Apex 비동기 처리 1~4편*, *LWC 성능 최적화 시리즈* 등)에서 순차적으로 주제를 선택.
   - **가공**: 시니어 아키텍트 페르소나를 적용해 **"실무 문제 시나리오 → 안티 패턴(나쁜 코드) vs 베스트 프랙티스(좋은 코드) → Governor Limits 및 성능 고려사항"**을 포함한 심층 강좌 포스팅 생성.

---

## 3. 시스템 아키텍처 및 구축할 파일 구조

GitHub Actions를 이용해 별도 서버 없이 매일 정해진 시간(예: 하루 1~2회) 자동으로 실행되며, `_posts/` 폴더에 Chirpy 테마 규격에 맞는 마크다운(`YYYY-MM-DD-title.md`)을 생성하고 자동 Commit & Push 합니다.

```text
taeyeonimda.github.io/
├── _posts/                      # AI가 생성한 마크다운 포스트가 저장될 폴더
├── _automation/                 # 새로 구축할 AI 자동화 봇 폴더
│   ├── generate_post.py         # 메인 파이썬 스크립트 (RSS 크롤링 + 커리큘럼 로드 + AI 프롬프팅 + 파일 생성)
│   ├── curriculum.json          # [Track B] 시리즈 연재용 주제 리스트 및 완료 여부 상태 관리
│   ├── posted_history.json      # [Track A] 이미 포스팅한 RSS 아티클 URL 중복 방지 기록
│   ├── prompts.py               # Chirpy 테마 Front Matter 규격 및 고품질 글 작성용 시스템 프롬프트
│   └── requirements.txt         # google-genai (또는 openai), feedparser, beautifulsoup4, PyYAML 등
└── .github/
    └── workflows/
        └── ai_auto_post.yml     # 매일 정해진 스케줄(cron)에 스크립트를 실행하고 자동 커밋/배포하는 워크플로우
```

---

## 4. 수익화 (Google AdSense) 로드맵
- **1단계 (기반 구축 & SEO 세팅)**: `_config.yml` 기본 블로그 정보 설정, Google Search Console 연동용 `sitemap.xml` 및 `robots.txt` 확인.
- **2단계 (콘텐츠 축적)**: 자동화 봇을 통해 고품질 포스트 20~30개 이상 누적.
- **3단계 (애드센스 승인 및 장착)**: Google AdSense 승인 신청 후 `_includes/head.html` (또는 Chirpy 설정) 및 루트 경로의 `ads.txt` 추가.

---

## 💬 다음 대화에서 바로 복사해서 붙여넣을 프롬프트

워크스페이스로 `C:\vsspace\taeyeonimda.github.io` 폴더를 여신 뒤, 새 대화창에 아래 내용을 그대로 복사해서 보내주시면 바로 코드 구현을 시작할 수 있습니다!

```markdown
현재 워크스페이스(`C:\vsspace\taeyeonimda.github.io`)에 있는 `AI_BLOG_AUTOMATION_PLAN.md` 파일을 먼저 읽어줘.

기존에 논의했던 내용대로 Jekyll(Chirpy 테마) 기반의 Salesforce & IT 기술 블로그 AI 자동 포스팅 시스템을 구축하려고 해.

다음 순서대로 진행해줘:
1. 현재 레포지토리의 `_config.yml`과 `.github/workflows` 상태를 점검해서 Chirpy 테마 초기 설정(타임존, 사이트 제목, 빌드 워크플로우 등)에 수정할 부분이 있는지 확인
2. `_automation/` 폴더에 투트랙(1. 해외 RSS 아티클 큐레이션 & 실무 해설 / 2. 커리큘럼 기반 시리즈 연재) 자동 포스팅 파이썬 스크립트와 초기 Salesforce/IT 커리큘럼(`curriculum.json`) 작성
3. GitHub Actions를 통해 매일 자동으로 글이 생성되고 커밋/배포되는 `.github/workflows/ai_auto_post.yml` 작성
4. 내가 GitHub Secrets에 API 키만 등록하면 바로 동작할 수 있도록 설정 방법 안내 (사용할 AI는 Gemini API 기준으로 작성해줘)
```
