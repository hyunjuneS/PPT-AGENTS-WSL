#!/bin/bash
# PPTAgent + DeepPresenter 폐쇄망 WSL 오프라인 셋업 스크립트
# git pull 후 최초 1회 실행

set -e
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OFFLINE_DIR="$REPO_DIR/offline_resources"
PLAYWRIGHT_DIR="$OFFLINE_DIR/ms-playwright"

echo "=== PPTAgent 오프라인 환경 설정 ==="

# 1. Playwright Chromium 재조립 및 설치
CHROMIUM_ZIP="$PLAYWRIGHT_DIR/chromium-linux64.zip"
if [ ! -f "$CHROMIUM_ZIP" ] && ls "$PLAYWRIGHT_DIR"/chromium-linux64.zip.part* &>/dev/null 2>&1; then
    echo "[1/5] Playwright Chromium 청크 파일 재조립 중..."
    cat "$PLAYWRIGHT_DIR"/chromium-linux64.zip.part* > "$CHROMIUM_ZIP"
    echo "✓ 재조립 완료"
fi

CHROMIUM_EXTRACTED="$PLAYWRIGHT_DIR/chromium-1223/chrome-linux64/chrome"
if [ -f "$CHROMIUM_ZIP" ] && [ ! -f "$CHROMIUM_EXTRACTED" ]; then
    echo "[2/5] Playwright Chromium 압축 해제 중..."
    mkdir -p "$PLAYWRIGHT_DIR/chromium-1223"
    python3 -c "import zipfile; zipfile.ZipFile('$CHROMIUM_ZIP').extractall('$PLAYWRIGHT_DIR/chromium-1223/')"
    chmod +x "$CHROMIUM_EXTRACTED"
    echo "✓ 압축 해제 완료: $CHROMIUM_EXTRACTED"
else
    echo "[2/5] Playwright Chromium 이미 준비됨"
fi

# 2. playwright install-deps (시스템 의존성 - apt 가 필요하면 실행)
echo "[3/5] Playwright 시스템 의존성 확인 중..."
if python3 -m playwright install-deps chromium 2>/dev/null; then
    echo "✓ 시스템 의존성 OK"
else
    echo "⚠ playwright install-deps 실패 (apt 접근 불가). 내부 apt 미러가 있다면 수동으로 실행:"
    echo "  sudo apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxrandr2 libxfixes3 libxdamage1"
fi

# 3. npm 패키지 오프라인 설치
echo "[4/5] Node.js html2pptx 패키지 설치 중..."
CACHE_DIR="$HOME/.cache/deeppresenter/html2pptx"
TARBALLS_DIR="$OFFLINE_DIR/html2pptx"
mkdir -p "$CACHE_DIR"
if ls "$TARBALLS_DIR"/*.tgz &>/dev/null 2>&1; then
    npm install --prefix "$CACHE_DIR" "$TARBALLS_DIR"/*.tgz 2>&1 | tail -3
    echo "✓ npm 패키지 설치 완료"
else
    echo "⚠ $TARBALLS_DIR 에 .tgz 파일이 없습니다"
fi

# 4. pip 패키지 (langid 폴백)
echo "[5/5] pip 패키지 (langid) 설치 중..."
PIP_PKG_DIR="$OFFLINE_DIR/pip_packages"
if ls "$PIP_PKG_DIR"/*.tar.gz &>/dev/null 2>&1 || ls "$PIP_PKG_DIR"/*.whl &>/dev/null 2>&1; then
    pip install --no-index --find-links="$PIP_PKG_DIR" langid 2>&1 | tail -3
    echo "✓ langid 설치 완료 (fasttext 폴백용)"
else
    pip install langid -q 2>&1 | tail -2
    echo "✓ langid 설치 완료 (온라인)"
fi

# 5. 환경변수 설정 파일 생성
ENV_FILE="$REPO_DIR/.env.offline"
cat > "$ENV_FILE" << EOF
# PPTAgent 오프라인 환경변수 - source .env.offline 으로 로드
export PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_DIR"
export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="$PLAYWRIGHT_DIR/chromium-1223/chrome-linux64/chrome"
export PLAYWRIGHT_OFFLINE=1
export OFFLINE_NODE_MODULES="$OFFLINE_DIR/html2pptx"
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export FASTTEXT_MODEL_PATH="$OFFLINE_DIR/fasttext/lid.176.bin"
EOF
echo ""
echo "=== 설정 완료 ==="
echo ""
echo "매 세션마다 아래 명령으로 환경변수를 로드하거나 ~/.bashrc 에 추가하세요:"
echo "  source $ENV_FILE"
echo ""
echo "FastText 언어감지 모델이 없으면 langid 폴백이 자동으로 사용됩니다."
echo "lid.176.bin 이 있다면 다음 위치에 배치하세요:"
echo "  $OFFLINE_DIR/fasttext/lid.176.bin"
echo "  또는 FASTTEXT_MODEL_PATH 환경변수로 경로 지정"
