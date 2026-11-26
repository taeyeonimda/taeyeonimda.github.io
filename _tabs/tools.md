---
title: Tools
icon: fas fa-wrench
order: 4
---

실무 개발 및 문서 작업 중 자주 사용하는 웹 유틸리티 모음입니다. 입력한 데이터는 서버로 전송되지 않으며 브라우저 내에서만 안전하게 처리됩니다.

---

### 🧹 HTML 태그 및 엔티티 제거기

HTML 태그(`<b>`, `<span>`, `<div>` 등)와 특수 엔티티(`&nbsp;`, `&lt;`, `&gt;`, `&quot;` 등)가 섞인 문자열에서 순수 텍스트만 깔끔하게 추출합니다.

<style>
  .tool-card {
    background: var(--card-bg, rgba(128, 128, 128, 0.06));
    border: 1px solid var(--main-border-color, rgba(128, 128, 128, 0.25));
    border-radius: 10px;
    padding: 1.25rem;
    margin-top: 1rem;
    margin-bottom: 2rem;
  }
  .tool-label-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
    font-weight: 600;
    font-size: 0.95rem;
  }
  .tool-char-count {
    font-size: 0.82rem;
    font-weight: 400;
    opacity: 0.75;
  }
  .tool-textarea {
    width: 100%;
    min-height: 160px;
    padding: 0.75rem;
    border-radius: 8px;
    border: 1px solid var(--main-border-color, rgba(128, 128, 128, 0.35));
    background: var(--main-bg, transparent);
    color: var(--text-color, inherit);
    font-family: inherit;
    font-size: 0.92rem;
    line-height: 1.55;
    resize: vertical;
  }
  .tool-textarea:focus {
    outline: none;
    border-color: var(--link-color, #4dabf7);
  }
  .tool-controls {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: center;
    margin: 1rem 0;
  }
  .tool-btn {
    padding: 0.45rem 1rem;
    border-radius: 6px;
    border: 1px solid var(--main-border-color, rgba(128, 128, 128, 0.35));
    background: var(--button-bg, transparent);
    color: var(--text-color, inherit);
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
    transition: opacity 0.15s ease;
  }
  .tool-btn:hover {
    opacity: 0.85;
  }
  .tool-btn-primary {
    background: #2b6cb0;
    border-color: #2b6cb0;
    color: #ffffff;
  }
  .tool-checkbox-label {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.88rem;
    margin-left: auto;
    cursor: pointer;
    user-select: none;
  }
  .tool-toast {
    font-size: 0.85rem;
    color: #38a169;
    font-weight: 600;
    margin-left: 0.4rem;
    display: none;
  }
</style>

<div class="tool-card">
  <div class="tool-label-row">
    <span>원본 HTML 입력</span>
    <span id="inputCount" class="tool-char-count">0자</span>
  </div>
  <textarea
    id="myTextarea"
    class="tool-textarea"
    placeholder="여기에 HTML 태그가 포함된 텍스트를 붙여넣으세요."
  >여기에 &lt;b&gt;HTML&lt;/b&gt; 태그가 &lt;span style="color: red;"&gt;포함된&lt;/span&gt; 텍스트를 입력하세요.</textarea>

  <div class="tool-controls">
    <button type="button" class="tool-btn tool-btn-primary" id="btnStripHtml">
      ✨ HTML 태그 제거
    </button>
    <button type="button" class="tool-btn" id="btnCopyResult">
      📋 결과 복사
    </button>
    <button type="button" class="tool-btn" id="btnClearAll">
      🗑️ 초기화
    </button>
    <span id="copyToast" class="tool-toast">복사되었습니다!</span>

    <label class="tool-checkbox-label">
      <input type="checkbox" id="chkKeepLineBreaks" checked>
      <span>줄바꿈 태그 유지</span>
    </label>
  </div>

  <div class="tool-label-row">
    <span>태그 제거 결과</span>
    <span id="outputCount" class="tool-char-count">0자</span>
  </div>
  <textarea
    id="resultTextarea"
    class="tool-textarea"
    readonly
    placeholder="태그가 제거된 순수 텍스트가 여기에 표시됩니다."
  ></textarea>
</div>

<script>
  (function () {
    const inputEl = document.getElementById('myTextarea');
    const outputEl = document.getElementById('resultTextarea');
    const inputCountEl = document.getElementById('inputCount');
    const outputCountEl = document.getElementById('outputCount');
    const keepLineBreaksEl = document.getElementById('chkKeepLineBreaks');
    const copyToastEl = document.getElementById('copyToast');

    const entityMap = {
      '&gt;': '>',
      '&lt;': '<',
      '&amp;': '&',
      '&quot;': '"',
      '&apos;': "'",
      '&#39;': "'",
      '&nbsp;': ' '
    };

    function removeHtmlTags(html, keepBreaks) {
      let text = html || '';

      if (keepBreaks) {
        text = text
          .replace(/<\s*br\s*\/?>/gi, '\n')
          .replace(/<\/\s*(p|div|li|tr|h[1-6])\s*>/gi, '\n');
      }

      text = text.replace(/<[^>]*>/g, '');

      for (const entity in entityMap) {
        const regex = new RegExp(entity, 'gi');
        text = text.replace(regex, entityMap[entity]);
      }

      text = text.replace(/&#(\d+);/g, function (_, dec) {
        return String.fromCharCode(Number(dec));
      });

      return text.trim();
    }

    function processTextarea() {
      const htmlContent = inputEl.value;
      const cleanText = removeHtmlTags(htmlContent, keepLineBreaksEl.checked);
      outputEl.value = cleanText;
      inputCountEl.textContent = htmlContent.length.toLocaleString() + '자';
      outputCountEl.textContent = cleanText.length.toLocaleString() + '자';
    }

    document.getElementById('btnStripHtml').addEventListener('click', processTextarea);
    inputEl.addEventListener('input', processTextarea);
    keepLineBreaksEl.addEventListener('change', processTextarea);

    document.getElementById('btnClearAll').addEventListener('click', function () {
      inputEl.value = '';
      outputEl.value = '';
      inputCountEl.textContent = '0자';
      outputCountEl.textContent = '0자';
      inputEl.focus();
    });

    document.getElementById('btnCopyResult').addEventListener('click', function () {
      if (!outputEl.value) return;
      navigator.clipboard.writeText(outputEl.value).then(function () {
        copyToastEl.style.display = 'inline';
        setTimeout(function () {
          copyToastEl.style.display = 'none';
        }, 1800);
      });
    });

    processTextarea();
  })();
</script>
