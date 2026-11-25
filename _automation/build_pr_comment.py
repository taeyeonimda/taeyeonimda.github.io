#!/usr/bin/env python3
"""PR 미리보기 링크 안내 댓글 마크다운 파일을 생성합니다."""

import os
from pathlib import Path


def main() -> None:
    site_root = os.environ["SITE_ROOT"]
    preview_home = os.environ["PREVIEW_HOME"]
    preview_post = os.environ["PREVIEW_POST"]
    out_path = os.environ.get("COMMENT_OUT", "/tmp/pr_comment.md")

    msg = (
        "## 🖥️ 테스트용 실제 블로그 미리보기 (나만 보기)\n\n"
        f"현재 이 글은 **진짜 메인 블로그(`{site_root}`)에는 아직 공개되지 않았습니다.** (일반 방문자에게는 보이지 않음)\n"
        "약 **40초~1분 뒤**(배경 배포 완료 후) 아래 링크를 누르면 "
        "**사이드바, 다크모드, 목차(TOC), 다이어그램까지 실제 블로그 화면 그대로** 확인하실 수 있습니다!\n\n"
        f"- 📄 **[이번 새 포스트 바로 보기 (실제 블로그 디자인)]({preview_post})**\n"
        f"- 🏠 **[테스트 블로그 홈 화면 보기]({preview_home})**\n\n"
        "---\n"
        "> ✅ **최종 배포 방법**: 화면 확인 후 마음에 드시면 아래 초록색 **[Merge pull request]** 버튼을 눌러주세요!\n"
        f"> 병합되는 즉시 진짜 블로그(`{site_root}`)에 공개되며, 위 임시 테스트 링크는 자동으로 삭제됩니다.\n"
    )
    Path(out_path).write_text(msg, encoding="utf-8")


if __name__ == "__main__":
    main()
