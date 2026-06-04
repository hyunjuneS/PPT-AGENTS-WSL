"""
HTML → PPTX 일괄 변환 스크립트
사용법: python html_to_pptx.py <html_폴더_경로> [--output <출력파일.pptx>] [--layout 16:9]
"""

import argparse
import asyncio
import sys
from pathlib import Path


async def convert(html_dir: Path, output: Path, layout: str) -> None:
    # html2pptx_cli.js 위치 찾기 (이 스크립트 기준 상대 경로)
    script_path = Path(__file__).parent / "pptagent" / "deeppresenter" / "html2pptx" / "html2pptx_cli.js"
    if not script_path.exists():
        # 현재 위치가 pptagent 안인 경우
        script_path = Path(__file__).parent / "deeppresenter" / "html2pptx" / "html2pptx_cli.js"
    if not script_path.exists():
        print(f"ERROR: html2pptx_cli.js 를 찾을 수 없습니다. 스크립트 위치를 확인하세요.")
        sys.exit(1)

    html_files = sorted(html_dir.glob("*.html"))
    if not html_files:
        print(f"ERROR: {html_dir} 안에 HTML 파일이 없습니다.")
        sys.exit(1)

    print(f"변환할 HTML 파일 {len(html_files)}개:")
    for f in html_files:
        print(f"  {f.name}")

    cmd = ["node", str(script_path), "--layout", layout]
    cmd.extend(["--html_dir", str(html_dir.resolve())])
    cmd.extend(["--output", str(output.resolve())])

    print(f"\n변환 중... → {output}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(script_path.parent),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        details = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()
        print(f"ERROR: 변환 실패\n{details}")
        sys.exit(1)

    print(f"완료! 저장됨: {output.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="HTML 폴더 → PPTX 변환")
    parser.add_argument("html_dir", help="HTML 파일이 있는 폴더 경로")
    parser.add_argument("--output", "-o", default=None, help="출력 PPTX 파일명 (기본: html_dir이름.pptx)")
    parser.add_argument("--layout", "-l", default="16:9", help="슬라이드 비율 (기본: 16:9, 옵션: 4:3, A4 등)")
    args = parser.parse_args()

    html_dir = Path(args.html_dir).expanduser().resolve()
    if not html_dir.is_dir():
        print(f"ERROR: {html_dir} 는 존재하지 않는 폴더입니다.")
        sys.exit(1)

    output = Path(args.output).expanduser() if args.output else html_dir.parent / f"{html_dir.name}.pptx"

    asyncio.run(convert(html_dir, output, args.layout))


if __name__ == "__main__":
    main()
