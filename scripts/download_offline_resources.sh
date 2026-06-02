#!/bin/bash
# 이 스크립트는 인터넷이 되는 환경에서 실행하세요.
# 오프라인 리소스를 다운로드하여 offline_resources/ 폴더에 저장합니다.

set -e
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OFFLINE_DIR="$REPO_DIR/offline_resources"

echo "=== 오프라인 리소스 다운로드 ==="
mkdir -p "$OFFLINE_DIR"/{ms-playwright,fasttext,html2pptx,pip_packages}

# 1. Playwright Chromium (Linux) 버전 확인 및 다운로드
echo "[1/4] Playwright Chromium (Linux) 다운로드 중..."
pip install playwright -q
REVISION=$(python3 -c "
import json, pathlib, playwright
for p in pathlib.Path(playwright.__file__).parent.rglob('browsers.json'):
    d = json.loads(p.read_text())
    if 'browsers' in d:
        for b in d['browsers']:
            if b['name'] == 'chromium':
                print(b['revision']); exit()
" 2>/dev/null)
BROWSER_VER=$(python3 -c "
import json, pathlib, playwright
for p in pathlib.Path(playwright.__file__).parent.rglob('browsers.json'):
    d = json.loads(p.read_text())
    if 'browsers' in d:
        for b in d['browsers']:
            if b['name'] == 'chromium':
                print(b['browserVersion']); exit()
" 2>/dev/null)
echo "  Playwright revision: $REVISION, Chrome version: $BROWSER_VER"

CHROMIUM_ZIP="$OFFLINE_DIR/ms-playwright/chromium-linux64.zip"
if [ ! -f "$CHROMIUM_ZIP" ]; then
    wget -q --show-progress \
        "https://storage.googleapis.com/chrome-for-testing-public/${BROWSER_VER}/linux64/chrome-linux64.zip" \
        -O "$CHROMIUM_ZIP"
fi

# 청크로 분할 (git 100MB 제한 대비)
cd "$OFFLINE_DIR/ms-playwright"
if [ -f "chromium-linux64.zip" ]; then
    split -b 50m chromium-linux64.zip chromium-linux64.zip.part
    rm chromium-linux64.zip
    echo "✓ Chromium 청크 분할 완료"
fi

# 2. FastText 언어인식 모델
echo "[2/4] FastText 모델 (lid.176.bin) 다운로드 중..."
echo "  주의: lid.176.bin 은 약 917MB입니다."
python3 -c "
from huggingface_hub import hf_hub_download
import shutil, pathlib
dest = pathlib.Path('$OFFLINE_DIR/fasttext/lid.176.bin')
if not dest.exists():
    p = hf_hub_download('julien-c/fasttext-language-id', 'lid.176.bin')
    shutil.copy2(p, dest)
    print(f'✓ FastText model: {dest.stat().st_size//1024//1024}MB')
else:
    print('✓ FastText model already exists')
" 2>/dev/null || echo "⚠ FastText 다운로드 실패 (HuggingFace 접근 불가). langid 폴백이 사용됩니다."

# 3. npm 패키지 tarball
echo "[3/4] npm 패키지 tarball 다운로드 중..."
cd "$OFFLINE_DIR/html2pptx"
npm pack fast-glob minimist playwright pptxgenjs sharp 2>&1 | grep "\.tgz$"
echo "✓ npm 패키지 다운로드 완료"

# 4. pip 패키지 (langid + numpy)
echo "[4/4] pip 패키지 다운로드 중..."
pip download langid -d "$OFFLINE_DIR/pip_packages" -q
echo "✓ pip 패키지 다운로드 완료"

echo ""
echo "=== 완료 ==="
du -sh "$OFFLINE_DIR"/*/
