#!/usr/bin/env python3
"""
블로그 포스트 Merge 시 Salesforce 실습 예제(LWC, Aura, Apex Controller 등)를
자동 생성하고 지정된 Salesforce Org("AgentForce My")에 컴파일 검증 및 배포하는 스크립트.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import xml.sax.saxutils as saxutils
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from google import genai
from google.genai import types

AUTOMATION_DIR = Path(__file__).resolve().parent
REPO_ROOT = AUTOMATION_DIR.parent
POSTS_DIR = REPO_ROOT / "_posts"
SAMPLES_ROOT = REPO_ROOT / "salesforce-samples"
MANIFEST_PATH = SAMPLES_ROOT / "deployed_demos.json"
PR_COMMENT_OUT = Path(os.environ.get("SF_PR_COMMENT_PATH", "/tmp/sf_deploy_pr_comment.md"))

KST = datetime.timezone(datetime.timedelta(hours=9))
API_VERSION = "62.0"
MAX_DEPLOY_ATTEMPTS = 3

GENERATION_SCHEMA: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "should_deploy": {
            "type": "BOOLEAN",
            "description": "Salesforce 기술 포스트로서 Org에 배포할 실습 예제(LWC, Aura, Apex 등) 생성이 적합하면 true, 일반 IT 글이거나 배포할 코드 예제가 불필요하면 false",
        },
        "skip_reason": {
            "type": "STRING",
            "description": "should_deploy가 false일 때 건너뛰는 사유 (한국어)",
        },
        "demo_title": {
            "type": "STRING",
            "description": "예제 패키지 제목 (한국어)",
        },
        "demo_type": {
            "type": "STRING",
            "description": "생성한 예제 유형 요약 (예: LWC + Apex Controller, LWC Only, Aura + Apex Controller, Apex Classes + Test 등)",
        },
        "demo_summary": {
            "type": "STRING",
            "description": "이 예제가 블로그 글의 어떤 핵심 개념을 시연하는지 2~3문장 요약 (한국어)",
        },
        "how_to_test": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "AgentForce My Org에 접속해서 배포된 예제를 바로 실행/확인하는 단계별 방법 (한국어)",
        },
        "anonymous_apex": {
            "type": "STRING",
            "description": "백엔드 Apex 테스트나 샘플 실행을 위해 Developer Console / sf apex run 에서 바로 실행 가능한 Anonymous Apex 코드 (없으면 빈 문자열)",
        },
        "files": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "SFDX 프로젝트 상대 경로 (반드시 force-app/main/default/... 하위로 작성)",
                    },
                    "content": {
                        "type": "STRING",
                        "description": "파일 전체 소스 코드",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    "required": [
        "should_deploy",
        "skip_reason",
        "demo_title",
        "demo_type",
        "demo_summary",
        "how_to_test",
        "anonymous_apex",
        "files",
    ],
}

SYSTEM_PROMPT = """당신은 Salesforce Developer Edition Org에 즉시 배포되어 100% 컴파일 및 동작하는 SFDX 실습 예제 아키텍트입니다.
주어진 기술 블로그 포스트를 분석하여, 포스트의 핵심 내용을 `"AgentForce My"` Org에서 직접 눈으로 보고 테스트할 수 있는 맞춤형 예제 메타데이터 번들을 생성합니다.

## 1. 배포 대상 판단 (`should_deploy`)
- 카테고리가 `Salesforce`이거나 본문이 Apex, LWC, Aura, SOQL, GraphQL, Wire, LMS, 비동기 처리(Queueable/Batch/Future), Flow Invocable Action, 보안(CRUD/FLS/User Mode), Agentforce Apex Action 등 Salesforce 플랫폼 기술을 다룬다면 `should_deploy: true`로 설정하세요.
- Salesforce와 무관한 순수 일반 IT/클라우드/기타 뉴스 글이라면 `should_deploy: false`로 설정하고 `files`는 빈 배열로 반환하세요.

## 2. 주제별 맞춤형 컴포넌트 구성 (경우에 따라 최적 선택)
- **LWC 관련 글**: 즉시 화면에 배치해 눌러볼 수 있는 **LWC 컴포넌트**(`force-app/main/default/lwc/<camelName>/`)를 생성하세요. 글에서 `@AuraEnabled` Apex와 비교하거나 서버 로직이 필요하면 **Apex Controller**도 세트로 생성하세요.
- **Aura 관련 글**: **Aura 컴포넌트 번들**(`force-app/main/default/aura/<PascalName>/`)과 필요 시 **Apex Controller**를 생성하세요.
- **백엔드 Apex 중심 글** (Trigger Handler/Bulkification, 비동기 Queueable/Batch, SOQL 최적화, 보안 `WITH USER_MODE` 등):
  - 블로그의 **베스트 프랙티스(Good Case)** 구조를 구현한 **Apex 클래스 + `@IsTest` 테스트 클래스**를 작성하고, 가능하면 Org 화면에서도 결과를 직관적으로 실행해볼 수 있는 간단한 **실습용 LWC 카드** 또는 즉시 실행 가능한 `anonymous_apex` 스크립트를 함께 제공하세요.
  - 주의: 블로그 본문에 설명용으로 적힌 '안티 패턴(Bad Case, 루프 내 SOQL 등)'은 별도 실패 클래스로 만들지 말고 주석이나 비교 메서드로 안전하게 표현하세요.

## 3. 100% 무결점 컴파일 & 배포를 위한 절대 규칙 (매우 중요)
1. **표준 객체 및 표준 필드만 사용 (커스텀 스키마 금지)**:
   - Org에 존재하지 않는 커스텀 객체(`__c`), 커스텀 메타데이터(`__mdt`), 플랫폼 이벤트(`__e`), Named Credential을 절대 참조하지 마세요! (컴파일 에러 원인 1순위)
   - 반드시 모든 Developer Edition에 기본 존재하는 표준 객체와 필드만 사용하세요:
     - `Account`: `Id, Name, Industry, Rating, Type, Phone, Website, AnnualRevenue, NumberOfEmployees, BillingCity, Description, CreatedDate`
     - `Contact`: `Id, FirstName, LastName, Name, Email, Phone, Title, Department, AccountId, CreatedDate`
     - `Opportunity`: `Id, Name, StageName, Amount, CloseDate, AccountId, Probability, CreatedDate`
     - `Case`: `Id, CaseNumber, Subject, Status, Priority, Origin, AccountId, CreatedDate`
   - 외부 HTTP Callout이나 Custom Metadata 스위치 예제라면, 실제 외부 설정 없이도 동작하도록 내부 Mock 분기 또는 기본값 Fallback 패턴으로 구현하세요.
2. **네이밍 및 길이 제한 준수 (이름 충돌 방지)**:
   - 주어진 `권장 네이밍 접두어(Prefix)`를 사용해 기존 Org 메타데이터와 절대 충돌하지 않게 하세요.
   - Salesforce 이름 최대 길이는 **38자 이내**, 영문+숫자만 사용하세요 (언더스코어 `_`나 하이픈 `-`을 LWC/클래스 이름에 넣지 마세요).
   - LWC 폴더명과 파일명(`.html`, `.js`, `.js-meta.xml`, 필요 시 `.css`)은 반드시 `blog...`로 시작하는 **camelCase**로 정확히 일치시키세요.
   - Apex 클래스 및 Aura 번들 이름은 `Blog...`로 시작하는 **PascalCase**로 작성하세요.
3. **안전한 Trigger 정책**:
   - 표준 객체(`Account` 등)에 활성(`Active`) 상태의 `ApexTrigger`를 직접 배포하면 Org의 다른 실습에 영향을 줍니다. 트리거 주제이더라도 **Trigger Handler / Service 클래스와 `@IsTest` 검증 클래스**로 구성하거나, 꼭 `.trigger` 파일을 포함할 경우 `.trigger-meta.xml`의 `<status>Inactive</status>`로 설정하세요.
4. **LWC 문법 엄수**:
   - LWC `.html` 템플릿 중괄호 `{...}` 안에는 삼항 연산자, 비교식(`===`, `>`), 배열 인덱스(`items[0]`), 메서드 호출을 절대 쓰지 마세요! 반드시 `.js`의 `get` 프로퍼티(getter)로 계산하세요.
   - 구버전 `if:true` 대신 `lwc:if`, `lwc:elseif`, `lwc:else`를 권장합니다.
   - `.js-meta.xml`에는 `apiVersion` `62.0`, `<isExposed>true</isExposed>`, `<masterLabel>Blog: ...</masterLabel>` 및 `lightning__AppPage`, `lightning__HomePage`, `lightning__RecordPage` 타겟을 설정하세요 (`targetConfigs`는 스키마 오류 방지를 위해 생략하세요).
5. **API 버전**: 모든 `-meta.xml`의 `<apiVersion>`은 `62.0`으로 통일하세요.
"""


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_post(post_path: Path) -> Dict[str, Any]:
    raw = post_path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$", raw)
    fm_data: Dict[str, Any] = {}
    body = raw
    if fm_match:
        try:
            fm_data = yaml.safe_load(fm_match.group(1)) or {}
        except Exception:
            fm_data = {}
        body = fm_match.group(2)

    stem = post_path.stem
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)
    return {
        "path": post_path,
        "rel_path": post_path.relative_to(REPO_ROOT).as_posix(),
        "slug": slug,
        "title": str(fm_data.get("title") or slug),
        "categories": fm_data.get("categories") or [],
        "tags": fm_data.get("tags") or [],
        "body": body,
        "raw": raw,
    }


def make_naming_prefix(slug: str) -> Tuple[str, str]:
    """포스트 슬러그로부터 고유하고 짧은 Apex(PascalCase) / LWC(camelCase) 접두어를 생성합니다."""
    words = [w for w in re.findall(r"[a-zA-Z0-9]+", slug) if w.lower() not in {"salesforce", "guide", "best", "practices", "the", "and", "for", "into", "your", "with"}]
    if not words:
        words = ["Demo"]
    short_pascal = "".join(w.capitalize()[:6] for w in words[:3])[:16]
    apex_prefix = f"Blog{short_pascal}"
    lwc_prefix = f"blog{short_pascal}"
    return apex_prefix, lwc_prefix


def discover_available_gemini_models(client: genai.Client) -> List[str]:
    excluded_keywords = (
        "embedding",
        "imagen",
        "veo",
        "tts",
        "audio",
        "vision",
        "robotics",
        "computer-use",
        "aqa",
        "bisheng",
        "learnlm",
        "gemma",
    )
    pro_models: List[str] = []
    flash_models: List[str] = []
    try:
        for m in client.models.list():
            name = (m.name or "").replace("models/", "")
            if not name.startswith("gemini-"):
                continue
            if any(kw in name.lower() for kw in excluded_keywords):
                continue
            actions = getattr(m, "supported_actions", None) or []
            if actions and "generateContent" not in actions:
                continue
            if "pro" in name.lower():
                pro_models.append(name)
            elif "flash" in name.lower():
                flash_models.append(name)
    except Exception as exc:
        print(f"[WARN] Gemini 모델 목록 조회 생략: {exc}")

    pro_models.sort(reverse=True)
    flash_models.sort(reverse=True)
    return pro_models + flash_models


def call_gemini_structured(prompt: str, preferred_model: str) -> Tuple[Dict[str, Any], str]:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 설정되어 있지 않습니다.")

    client = genai.Client(api_key=api_key)
    candidates = [preferred_model]
    for fb in ["gemini-3.1-pro-preview", "gemini-3.0-flash", "gemini-3-flash-preview"]:
        if fb not in candidates:
            candidates.append(fb)
    for disc in discover_available_gemini_models(client):
        if disc not in candidates:
            candidates.append(disc)

    last_err: Optional[Exception] = None
    for model_name in candidates:
        try:
            print(f"[AI] {model_name} 모델로 SFDX 예제 번들 생성 요청 중...")
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.3,
                    response_mime_type="application/json",
                    response_schema=GENERATION_SCHEMA,
                ),
            )
            if not resp.text:
                raise RuntimeError("빈 응답 반환")
            parsed = json.loads(resp.text)
            return parsed, model_name
        except Exception as exc:
            last_err = exc
            print(f"[WARN] {model_name} 호출 실패 ({exc}). 다음 폴백 모델 시도...")

    raise RuntimeError(f"모든 Gemini 모델 호출 실패: {last_err}")


def build_initial_prompt(post_info: Dict[str, Any]) -> str:
    apex_prefix, lwc_prefix = make_naming_prefix(post_info["slug"])
    return f"""다음은 블로그 `main` 브랜치에 병합(Merge)된 최신 기술 포스트입니다.

- **포스트 파일**: `{post_info['rel_path']}`
- **제목**: {post_info['title']}
- **카테고리**: {post_info['categories']}
- **태그**: {post_info['tags']}
- **권장 Apex/Aura 접두어**: `{apex_prefix}...` (예: `{apex_prefix}Ctrl`, `{apex_prefix}ServiceTest`)
- **권장 LWC 접두어**: `{lwc_prefix}...` (예: `{lwc_prefix}Demo`)

---
### 포스트 본문
{post_info['body'][:14000]}
---

위 포스트가 Salesforce 관련 기술 글이라면 `"AgentForce My"` Developer Edition Org에 즉시 배포하여 실습해 볼 수 있는 완결된 SFDX 메타데이터 파일들(`force-app/main/default/...`)을 설계해 반환하세요.
- 화면 컴포넌트(LWC 또는 Aura)가 어울리는 주제라면 Lightning App Builder에 바로 드래그해서 실행해 볼 수 있도록 직관적인 샘플 UI(버튼, 조회 결과 표시, 상태 안내 등)를 포함하세요.
- 표준 객체(`Account`, `Contact`, `Opportunity`, `Case`) 데이터가 Org에 적을 수도 있으므로, 조회 결과가 0건일 때 화면에서 '샘플 테스트 데이터 생성' 버튼을 누르거나 빈 상태 안내가 친절히 나오도록 구성하면 더욱 좋습니다.
"""


def build_repair_prompt(
    post_info: Dict[str, Any],
    previous_bundle: Dict[str, Any],
    deploy_error_text: str,
    attempt: int,
) -> str:
    apex_prefix, lwc_prefix = make_naming_prefix(post_info["slug"])
    files_dump = json.dumps(previous_bundle.get("files", []), ensure_ascii=False, indent=2)
    return f"""이전 시도(#{attempt})에서 생성한 SFDX 메타데이터를 `"AgentForce My"` Org에 배포(`sf project deploy start`)하던 중 아래와 같은 **Salesforce 컴파일/배포 오류**가 발생했습니다.

### 포스트 제목
{post_info['title']} (권장 접두어: Apex `{apex_prefix}`, LWC `{lwc_prefix}`)

### 발생한 배포 오류 상세 내역
```text
{deploy_error_text[:6000]}
```

### 직전에 생성했던 파일 목록
```json
{files_dump[:16000]}
```

위 컴파일/배포 오류 원인을 정확히 해결하여 **수정된 전체 파일 목록(`files`)**을 다시 반환하세요.
- 존재하지 않는 필드/객체/모듈 참조가 있었다면 표준 객체(`Account`, `Contact`, `Opportunity`, `Case`)의 기본 필드로 대체하세요.
- LWC HTML 템플릿 표현식 오류였다면 JS getter 프로퍼티로 분리하세요.
- 불필요하게 문제를 일으키는 파일은 제거하거나 단순하고 확실하게 컴파일되는 코드로 교정하세요.
"""


def default_cls_meta_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata">\n'
        f"    <apiVersion>{API_VERSION}</apiVersion>\n"
        "    <status>Active</status>\n"
        "</ApexClass>\n"
    )


def default_trigger_meta_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ApexTrigger xmlns="http://soap.sforce.com/2006/04/metadata">\n'
        f"    <apiVersion>{API_VERSION}</apiVersion>\n"
        "    <status>Inactive</status>\n"
        "</ApexTrigger>\n"
    )


def default_aura_meta_xml(desc: str) -> str:
    safe_desc = saxutils.escape(desc[:120])
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<AuraDefinitionBundle xmlns="http://soap.sforce.com/2006/04/metadata">\n'
        f"    <apiVersion>{API_VERSION}</apiVersion>\n"
        f"    <description>{safe_desc}</description>\n"
        "</AuraDefinitionBundle>\n"
    )


def default_lwc_meta_xml(comp_name: str, title: str) -> str:
    safe_label = saxutils.escape(f"Blog: {comp_name}"[:38])
    safe_desc = saxutils.escape(title[:120])
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<LightningComponentBundle xmlns="http://soap.sforce.com/2006/04/metadata">\n'
        f"    <apiVersion>{API_VERSION}</apiVersion>\n"
        "    <isExposed>true</isExposed>\n"
        f"    <masterLabel>{safe_label}</masterLabel>\n"
        f"    <description>{safe_desc}</description>\n"
        "    <targets>\n"
        "        <target>lightning__AppPage</target>\n"
        "        <target>lightning__HomePage</target>\n"
        "        <target>lightning__RecordPage</target>\n"
        "    </targets>\n"
        "</LightningComponentBundle>\n"
    )


def materialize_sfdx_project(sample_dir: Path, bundle: Dict[str, Any], post_info: Dict[str, Any]) -> List[str]:
    """생성된 번들을 SFDX 표준 폴더 구조로 기록하고 누락된 -meta.xml 및 안전장치를 자동 보정합니다."""
    force_app_dir = sample_dir / "force-app"
    if force_app_dir.exists():
        shutil.rmtree(force_app_dir)
    sample_dir.mkdir(parents=True, exist_ok=True)

    sfdx_project = {
        "packageDirectories": [{"path": "force-app", "default": True}],
        "name": f"blog-demo-{post_info['slug'][:40]}",
        "namespace": "",
        "sfdcLoginUrl": "https://login.salesforce.com",
        "sourceApiVersion": API_VERSION,
    }
    save_json(sample_dir / "sfdx-project.json", sfdx_project)

    written_paths: List[str] = []
    file_map: Dict[str, str] = {}

    for item in bundle.get("files", []):
        rel = str(item.get("path", "")).strip().replace("\\", "/").lstrip("/")
        content = str(item.get("content", ""))
        if not rel or ".." in rel.split("/"):
            continue
        if not rel.startswith("force-app/main/default/"):
            rel = "force-app/main/default/" + rel.lstrip("/")
        file_map[rel] = content

    # 필수 -meta.xml 보정 및 Trigger Inactive 강제
    extra_files: Dict[str, str] = {}
    for rel, content in list(file_map.items()):
        if rel.endswith(".cls") and f"{rel}-meta.xml" not in file_map:
            extra_files[f"{rel}-meta.xml"] = default_cls_meta_xml()
        elif rel.endswith(".trigger"):
            extra_files[f"{rel}-meta.xml"] = default_trigger_meta_xml()
        elif rel.endswith("-meta.xml") and "<ApexTrigger" in content:
            file_map[rel] = re.sub(r"<status>\s*Active\s*</status>", "<status>Inactive</status>", content)
        elif "/lwc/" in rel and rel.endswith(".js") and not rel.endswith(".test.js"):
            parts = rel.split("/")
            if len(parts) >= 2:
                comp_name = parts[-2]
                meta_rel = "/".join(parts[:-1] + [f"{comp_name}.js-meta.xml"])
                if meta_rel not in file_map:
                    extra_files[meta_rel] = default_lwc_meta_xml(comp_name, post_info["title"])
                else:
                    file_map[meta_rel] = re.sub(
                        r"<isExposed>\s*false\s*</isExposed>",
                        "<isExposed>true</isExposed>",
                        file_map[meta_rel],
                    )
        elif "/aura/" in rel and rel.endswith(".cmp"):
            if f"{rel}-meta.xml" not in file_map:
                extra_files[f"{rel}-meta.xml"] = default_aura_meta_xml(post_info["title"])

    file_map.update(extra_files)

    for rel, content in sorted(file_map.items()):
        dest = sample_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content.rstrip() + "\n", encoding="utf-8")
        written_paths.append(rel)

    anon_apex = str(bundle.get("anonymous_apex") or "").strip()
    if anon_apex:
        anon_path = sample_dir / "scripts" / "apex" / "run_demo.apex"
        anon_path.parent.mkdir(parents=True, exist_ok=True)
        anon_path.write_text(anon_apex + "\n", encoding="utf-8")
        written_paths.append("scripts/apex/run_demo.apex")

    return written_paths


def run_sf_deploy(sample_dir: Path, target_org: str) -> Tuple[bool, List[Dict[str, str]], str]:
    """sf project deploy start 실행 후 (성공 여부, 배포된 컴포넌트 리스트, 에러 메시지) 반환"""
    sf_bin = shutil.which("sf")
    if not sf_bin:
        raise RuntimeError("Salesforce CLI('sf')를 찾을 수 없습니다.")

    cmd = [
        sf_bin,
        "project",
        "deploy",
        "start",
        "--source-dir",
        "force-app",
        "--target-org",
        target_org,
        "--wait",
        "10",
        "--json",
    ]
    print(f"[SF] 배포 실행 중: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(sample_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    raw_out = (proc.stdout or "").strip()
    raw_err = (proc.stderr or "").strip()
    data: Dict[str, Any] = {}
    if raw_out:
        # sf CLI가 경고 문구를 JSON 앞에 출력하는 경우 대비하여 첫 '{'부터 파싱
        brace_idx = raw_out.find("{")
        if brace_idx != -1:
            try:
                data = json.loads(raw_out[brace_idx:])
            except Exception:
                data = {}

    if proc.returncode == 0 and data.get("status", 0) == 0:
        deployed_items: List[Dict[str, str]] = []
        details = (data.get("result") or {}).get("details") or {}
        successes = details.get("componentSuccesses") or (data.get("result") or {}).get("files") or []
        if isinstance(successes, dict):
            successes = [successes]
        seen = set()
        for comp in successes:
            c_type = str(comp.get("componentType") or comp.get("type") or "")
            c_name = str(comp.get("fullName") or comp.get("fileName") or "")
            if not c_name or c_name == "package.xml":
                continue
            key = f"{c_type}:{c_name}"
            if key not in seen:
                seen.add(key)
                deployed_items.append(
                    {
                        "type": c_type or "Metadata",
                        "name": c_name,
                        "file": str(comp.get("fileName") or comp.get("filePath") or ""),
                    }
                )
        return True, deployed_items, ""

    # 실패 상세 사유 추출
    error_lines: List[str] = []
    if data.get("message"):
        error_lines.append(f"Message: {data['message']}")
    details = (data.get("result") or {}).get("details") or {}
    failures = details.get("componentFailures") or (data.get("result") or {}).get("files") or []
    if isinstance(failures, dict):
        failures = [failures]
    for fail in failures:
        state = str(fail.get("state") or "Failed")
        problem = fail.get("problem") or fail.get("error")
        if problem or state.lower() == "failed":
            fname = fail.get("fileName") or fail.get("filePath") or fail.get("fullName") or "unknown"
            line_no = fail.get("lineNumber") or ""
            col_no = fail.get("columnNumber") or ""
            loc = f" (line {line_no}, col {col_no})" if line_no else ""
            error_lines.append(f"- [{fname}{loc}] {problem}")

    if not error_lines:
        error_lines.append(raw_out[-3000:] if raw_out else raw_err[-3000:])

    return False, [], "\n".join(error_lines)


def write_sample_readme(
    sample_dir: Path,
    post_info: Dict[str, Any],
    bundle: Dict[str, Any],
    deployed_items: List[Dict[str, str]],
    target_org: str,
    used_model: str,
    deployed_at: str,
    dry_run: bool,
) -> None:
    comp_rows = "\n".join(
        f"| `{item['type']}` | `{item['name']}` | `{item['file']}` |" for item in deployed_items
    )
    if not comp_rows:
        comp_rows = "| `(Dry-Run / Local Files)` | - | `force-app/main/default/...` |"

    steps_md = "\n".join(
        f"{idx}. {step}" for idx, step in enumerate(bundle.get("how_to_test") or [], start=1)
    )
    anon_apex = str(bundle.get("anonymous_apex") or "").strip()
    anon_section = ""
    if anon_apex:
        anon_section = (
            "\n## ⚡ Anonymous Apex 빠른 실행\n\n"
            "터미널에서 아래 명령어로 즉시 실행하거나 Developer Console에서 실행할 수 있습니다:\n\n"
            f"```bash\nsf apex run --file scripts/apex/run_demo.apex --target-org \"{target_org}\"\n```\n\n"
            f"```apex\n{anon_apex}\n```\n"
        )

    status_badge = "Dry-Run (파일만 생성)" if dry_run else f"`{target_org}` Org 배포 완료"
    readme = f"""# 🚀 {bundle.get('demo_title') or post_info['title']}

- **원본 블로그 포스트**: `{post_info['rel_path']}` ({post_info['title']})
- **예제 유형**: `{bundle.get('demo_type')}`
- **배포 상태**: {status_badge} (`{deployed_at}`)
- **생성 모델**: `{used_model}`

## 📌 예제 개요
{bundle.get('demo_summary')}

## 📦 생성 및 배포된 메타데이터
| 종류 (Type) | 메타데이터 이름 (API Name) | 경로 |
| :--- | :--- | :--- |
{comp_rows}

## 🧪 `{target_org}` Org에서 확인 및 테스트하는 방법
{steps_md}
{anon_section}
"""
    (sample_dir / "README.md").write_text(readme, encoding="utf-8")


def resolve_target_posts(args: argparse.Namespace, manifest: Dict[str, Any]) -> List[Path]:
    candidates: List[Path] = []

    if args.post:
        for p in args.post:
            path = (REPO_ROOT / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
            if path.exists():
                candidates.append(path)
    elif args.changed_files:
        raw_tokens = re.split(r"[\r\n]+", args.changed_files.strip())
        for tok in raw_tokens:
            tok = tok.strip()
            if not tok or not tok.endswith(".md"):
                continue
            path = (REPO_ROOT / tok).resolve()
            if path.exists() and POSTS_DIR in path.parents:
                candidates.append(path)
    elif args.latest:
        all_posts = sorted(POSTS_DIR.glob("*.md"))
        if all_posts:
            candidates.append(all_posts[-1])

    # 중복 제거 및 기배포 필터링
    deployed_map = manifest.get("demos", {})
    final_list: List[Path] = []
    seen = set()
    for c in candidates:
        rel = c.relative_to(REPO_ROOT).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        prev = deployed_map.get(rel)
        if prev and prev.get("status") in {"deployed", "skipped"} and not args.force and not args.dry_run:
            print(f"[SKIP] 이미 처리된 포스트입니다 ({prev.get('status')}): {rel} (재배포하려면 --force 사용)")
            continue
        final_list.append(c)

    return final_list


def write_ci_summary_and_outputs(results_md: str, outputs: Dict[str, str]) -> None:
    if results_md:
        PR_COMMENT_OUT.parent.mkdir(parents=True, exist_ok=True)
        PR_COMMENT_OUT.write_text(results_md, encoding="utf-8")

        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write(results_md + "\n")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            for k, v in outputs.items():
                safe_v = str(v).replace("\n", " ").strip()
                f.write(f"{k}={safe_v}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="병합된 Salesforce 블로그 포스트를 분석해 AgentForce My Org에 실습 예제를 생성/배포합니다."
    )
    parser.add_argument("--post", action="append", help="대상 포스트 파일 경로 (복수 지정 가능)")
    parser.add_argument("--changed-files", type=str, default="", help="줄바꿈으로 구분된 변경 파일 목록")
    parser.add_argument("--latest", action="store_true", help="가장 최신 포스트 1개를 대상으로 실행")
    parser.add_argument(
        "--target-org",
        type=str,
        default=os.environ.get("SF_TARGET_ORG", "AgentForce My"),
        help='배포 대상 Salesforce Org 별칭 또는 사용자명 (기본값: "AgentForce My")',
    )
    parser.add_argument("--force", action="store_true", help="이미 배포된 이력이 있어도 강제로 재생성 및 재배포")
    parser.add_argument("--dry-run", action="store_true", help="SFDX 예제 파일만 생성하고 실제 Org 배포는 생략")
    parser.add_argument(
        "--model",
        type=str,
        default=os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview"),
        help="우선 사용할 Gemini 모델명",
    )
    args = parser.parse_args()

    manifest = load_json(MANIFEST_PATH, {"demos": {}})
    targets = resolve_target_posts(args, manifest)

    if not targets:
        print("[INFO] 새로 배포할 대상 포스트가 없습니다.")
        write_ci_summary_and_outputs("", {"deployed_count": "0", "has_changes": "false"})
        return 0

    now_kst = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S +0900")
    summary_sections: List[str] = []
    deployed_count = 0
    has_repo_changes = False

    for post_path in targets:
        post_info = parse_post(post_path)
        print(f"\n============================================================")
        print(f"[대상 포스트] {post_info['title']} ({post_info['rel_path']})")
        print(f"============================================================")

        prompt = build_initial_prompt(post_info)
        bundle, used_model = call_gemini_structured(prompt, args.model)

        if not bundle.get("should_deploy") or not bundle.get("files"):
            reason = bundle.get("skip_reason") or "Salesforce 실습 예제 배포 대상 주제가 아님"
            print(f"[SKIP] Org 예제 생성 생략: {reason}")
            if not args.dry_run:
                manifest.setdefault("demos", {})[post_info["rel_path"]] = {
                    "title": post_info["title"],
                    "slug": post_info["slug"],
                    "status": "skipped",
                    "reason": reason,
                    "checked_at": now_kst,
                }
                save_json(MANIFEST_PATH, manifest)
                has_repo_changes = True
            summary_sections.append(
                f"### ℹ️ Salesforce Org 예제 배포 생략 (`{post_info['title']}`)\n"
                f"- **사유**: {reason}\n"
            )
            continue

        sample_dir = SAMPLES_ROOT / post_info["slug"]
        deployed_ok = False
        deployed_items: List[Dict[str, str]] = []
        last_error = ""

        for attempt in range(1, MAX_DEPLOY_ATTEMPTS + 1):
            written_files = materialize_sfdx_project(sample_dir, bundle, post_info)
            print(f"[생성 완료 - 시도 #{attempt}] 파일 {len(written_files)}개 생성됨 ({sample_dir.relative_to(REPO_ROOT).as_posix()})")

            if args.dry_run:
                deployed_ok = True
                break

            ok, items, err_text = run_sf_deploy(sample_dir, args.target_org)
            if ok:
                deployed_ok = True
                deployed_items = items
                print(f"[성공] '{args.target_org}' Org 배포 성공! (컴포넌트 {len(deployed_items)}개)")
                break

            last_error = err_text
            print(f"[WARN] 배포 실패 (시도 #{attempt}/{MAX_DEPLOY_ATTEMPTS}):\n{err_text}")
            if attempt < MAX_DEPLOY_ATTEMPTS:
                print("[AI 자가 복구] 컴파일 오류 로그를 바탕으로 코드 자동 수정을 요청합니다...")
                repair_prompt = build_repair_prompt(post_info, bundle, err_text, attempt)
                bundle, used_model = call_gemini_structured(repair_prompt, args.model)

        if not deployed_ok:
            raise RuntimeError(
                f"'{post_info['title']}' 예제 Org 배포가 {MAX_DEPLOY_ATTEMPTS}회 시도 후 최종 실패했습니다:\n{last_error}"
            )

        write_sample_readme(
            sample_dir=sample_dir,
            post_info=post_info,
            bundle=bundle,
            deployed_items=deployed_items,
            target_org=args.target_org,
            used_model=used_model,
            deployed_at=now_kst,
            dry_run=args.dry_run,
        )

        if not args.dry_run:
            manifest.setdefault("demos", {})[post_info["rel_path"]] = {
                "title": post_info["title"],
                "slug": post_info["slug"],
                "demo_title": bundle.get("demo_title"),
                "demo_type": bundle.get("demo_type"),
                "sample_dir": f"salesforce-samples/{post_info['slug']}",
                "target_org": args.target_org,
                "components": deployed_items,
                "status": "deployed",
                "deployed_at": now_kst,
            }
            save_json(MANIFEST_PATH, manifest)

        deployed_count += 1
        has_repo_changes = True

        comp_bullets = "\n".join(
            f"  - `{c['type']}`: **`{c['name']}`**" for c in deployed_items
        ) or "  - `(Dry-run 모드: 로컬 파일 생성만 수행됨)`"
        how_to_bullets = "\n".join(
            f"  {i}. {step}" for i, step in enumerate(bundle.get("how_to_test") or [], start=1)
        )
        repo_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/" + os.environ.get(
            "GITHUB_REPOSITORY", "taeyeonimda/taeyeonimda.github.io"
        )
        folder_link = f"{repo_url}/tree/main/salesforce-samples/{post_info['slug']}"

        summary_sections.append(
            f"""## ☁️ `{args.target_org}` Salesforce Org 실습 예제 자동 배포 완료!

- **대상 포스트**: **{post_info['title']}**
- **예제 구성**: `{bundle.get('demo_type')}` — {bundle.get('demo_title')}
- **저장된 소스 경로**: [`salesforce-samples/{post_info['slug']}`]({folder_link})
- **배포된 메타데이터**:
{comp_bullets}

### 🧪 Org에서 바로 확인하는 방법
{how_to_bullets}
"""
        )

    final_summary = "\n---\n".join(summary_sections)
    write_ci_summary_and_outputs(
        results_md=final_summary,
        outputs={
            "deployed_count": str(deployed_count),
            "has_changes": "true" if has_repo_changes and not args.dry_run else "false",
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
