"""
ex_template_builder.py

ex_templates/ 폴더에 있는 PPT 파일을 분석해 pptagent/templates/ 형식으로 변환합니다.
ViT(이미지 임베딩 모델) 없이 동작합니다.

실행 방법 (pptagent 디렉토리에서):
    cd pptagent
    uv run python ../ex_template_builder.py

또는 venv Python으로 직접:
    pptagent/.venv/bin/python ex_template_builder.py

설정은 아래 CONFIG 블록을 직접 수정하세요.
"""

import os as _os
_BASE = _os.path.dirname(_os.path.abspath(__file__))

# ======= CONFIG: 여기를 수정하세요 =======
API_BASE_URL   = "https://api.openai.com/v1"   # OpenAI 호환 API 엔드포인트
API_KEY        = "sk-..."                        # API 키
LANGUAGE_MODEL = "gpt-4.1"                      # 텍스트 분석용 모델
VISION_MODEL   = "gpt-4.1"                      # 이미지 분석용 모델 (비전 지원 필요)

# 분석할 .pptx 파일이 있는 폴더 (스크립트 기준 상대 경로)
INPUT_DIR  = _os.path.join(_BASE, "ex_templates")
# 결과를 저장할 폴더
OUTPUT_DIR = _os.path.join(_BASE, "pptagent", "pptagent", "templates")
# =========================================

import asyncio
import json
import tempfile
from collections import defaultdict
from glob import glob
from os.path import basename, join, splitext

from pptagent.induct import ASK_CATEGORY_PROMPT, CATEGORY_SPLIT_TEMPLATE, SlideInducter
from pptagent.llms import AsyncLLM
from pptagent.model_utils import language_id
from pptagent.multimodal import ImageLabler
from pptagent.presentation import Picture, Presentation, SlidePage
from pptagent.utils import Config, ppt_to_images

DESCRIBE_TEMPLATE_PROMPT = (
    "You are given a PowerPoint presentation. "
    "Write a single concise sentence (under 20 words) describing the visual style and theme of this template. "
    "Focus on color scheme and overall aesthetic. Do not use line breaks."
)


def _layout_features(slide: SlidePage, slide_area_pt: float) -> tuple:
    """Bucket visual layout properties into discrete groups.

    Returns a tuple of (image_ratio_bucket, shape_count_bucket, para_count_bucket)
    so slides that look structurally similar end up in the same group.
    """
    image_area = sum(s.width * s.height for s in slide.shape_filter(Picture))
    image_bucket = round(min(image_area / slide_area_pt, 1.0) * 4) / 4   # 0, 0.25, 0.5, 0.75, 1.0
    shape_bucket = min(len(slide.shapes) // 3, 3)                         # 0(0-2), 1(3-5), 2(6-8), 3(9+)
    para_bucket  = min(len(list(slide.iter_paragraphs())) // 4, 3)        # 0(0-3), 1(4-7), 2(8-11), 3(12+)
    return (image_bucket, shape_bucket, para_bucket)


async def layout_split_no_vit(
    prs: Presentation,
    content_slides_index: set[int],
    layout_induction: dict,
    vision_model: AsyncLLM,
    ppt_image_folder: str,
) -> None:
    """Group slides by layout name + visual feature buckets (no ViT needed).

    Original pipeline uses ViT embeddings to sub-cluster slides with the same
    (layout_name, content_type). Here we approximate that with three bucketed
    shape-level features: image area ratio, shape count, paragraph count.
    This separates table-heavy slides from text-heavy slides even when they
    share the same PPTX layout name.
    """
    slide_area_pt = prs.slides[0].slide_width * prs.slides[0].slide_height
    content_split: dict[tuple, list[int]] = defaultdict(list)
    for slide_idx in content_slides_index:
        slide = prs.slides[slide_idx - 1]
        content_type = slide.get_content_type()
        layout_name = slide.slide_layout_name or "unnamed"
        features = _layout_features(slide, slide_area_pt)
        # If image shapes exist but occupy negligible area (decorative/icons),
        # treat the slide as text so it groups with other text slides.
        if features[0] == 0.0 and content_type == "image":
            content_type = "text"
        content_split[(layout_name, content_type) + features].append(slide_idx)

    async with asyncio.TaskGroup() as tg:
        for group_key, slides in content_split.items():
            content_type = group_key[1]
            template_id = max(slides, key=lambda x: len(prs.slides[x - 1].shapes))
            img_path = join(ppt_image_folder, f"slide_{template_id:04d}.jpg")

            tg.create_task(vision_model(ASK_CATEGORY_PROMPT, img_path)).add_done_callback(
                lambda f, tid=template_id, sidxs=slides, ctype=content_type: (
                    layout_induction[f.result() + ":" + ctype].update(
                        {"template_id": tid, "slides": sidxs}
                    )
                )
            )


async def build_template(pptx_path: str, template_name: str) -> None:
    output_dir = join(OUTPUT_DIR, template_name)
    _os.makedirs(output_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as work_dir:
        config = Config(rundir=work_dir)
        ppt_image_folder = join(work_dir, "slide_images")
        template_image_folder = join(work_dir, "template_images")
        source_pptx = join(output_dir, "source.pptx")

        language_model = AsyncLLM(LANGUAGE_MODEL, API_BASE_URL, API_KEY)
        vision_model   = AsyncLLM(VISION_MODEL,   API_BASE_URL, API_KEY)

        # 1. 파싱 및 source.pptx 저장
        print(f"[{template_name}] Parsing PPTX...")
        prs = Presentation.from_file(pptx_path, config)
        prs.save(source_pptx)

        # 2. 슬라이드 이미지 생성 (LibreOffice/soffice 필요)
        print(f"[{template_name}] Generating slide images...")
        try:
            await ppt_to_images(source_pptx, ppt_image_folder)
        except Exception as e:
            print(
                f"\n[ERROR] 슬라이드 이미지 생성 실패: {e}\n"
                "LibreOffice(soffice)가 설치되어 있는지 확인하세요.\n"
                "Ubuntu: sudo apt install libreoffice\n"
            )
            return

        # layout_only 이미지 (배경 레이아웃만)
        prs.save(join(work_dir, "template.pptx"), layout_only=True)
        await ppt_to_images(join(work_dir, "template.pptx"), template_image_folder)

        # pptx 다시 로드 (이미지 경로 등 재설정)
        prs = Presentation.from_file(source_pptx, config)

        # 3. 이미지 캡션 생성 → image_stats.json
        image_stats_path = join(output_dir, "image_stats.json")
        if _os.path.exists(image_stats_path):
            print(f"[{template_name}] image_stats.json already exists, skipping captioning.")
            labler = ImageLabler(prs, config)
            labler.apply_stats(json.load(open(image_stats_path, encoding="utf-8")))
        else:
            print(f"[{template_name}] Captioning images...")
            labler = ImageLabler(prs, config)
            image_stats = await labler.caption_images_async(vision_model)
            with open(image_stats_path, "w", encoding="utf-8") as f:
                json.dump(image_stats, f, indent=4, ensure_ascii=False)

        # 4. 기능 슬라이드 분류 (category_split)
        print(f"[{template_name}] Classifying functional slides...")
        inducter = SlideInducter(
            prs,
            ppt_image_folder,
            template_image_folder,
            config,
            image_models=[],       # ViT 미사용
            language_model=language_model,
            vision_model=vision_model,
            use_assert=False,      # 이미지 수 불일치 무시
        )
        content_slides_index, functional_cluster = await inducter.category_split()

        # 5. 레이아웃 분류 (ViT 없는 버전)
        print(f"[{template_name}] Grouping layouts (no ViT)...")
        layout_induction: dict = defaultdict(lambda: defaultdict(list))
        for layout_name, cluster in functional_cluster.items():
            layout_induction[layout_name]["slides"] = cluster
            layout_induction[layout_name]["template_id"] = cluster[0]
        functional_keys = list(layout_induction.keys())

        # 미분류 슬라이드를 content_slides_index에 추가
        function_slides = set(sum(functional_cluster.values(), []))
        for i in range(len(prs.slides)):
            if i + 1 not in function_slides and i + 1 not in content_slides_index:
                content_slides_index.add(i + 1)

        await layout_split_no_vit(
            prs, content_slides_index, layout_induction, vision_model, ppt_image_folder
        )
        layout_induction["functional_keys"] = functional_keys

        # 6. 콘텐츠 스키마 추출 (content_induct)
        print(f"[{template_name}] Extracting content schemas...")
        inducter.prs = prs
        layout_induction = await inducter.content_induct(layout_induction)

        # 7. slide_induction.json 저장
        with open(join(output_dir, "slide_induction.json"), "w", encoding="utf-8") as f:
            json.dump(layout_induction, f, indent=4, ensure_ascii=False)
        print(f"[{template_name}] Saved slide_induction.json")

        # 8. description.txt 생성
        desc_path = join(output_dir, "description.txt")
        if not _os.path.exists(desc_path):
            print(f"[{template_name}] Generating description...")
            slide_text = prs.to_text()[:3000]
            description = await language_model(
                DESCRIBE_TEMPLATE_PROMPT + "\n\nPresentation text:\n" + slide_text
            )
            with open(desc_path, "w", encoding="utf-8") as f:
                f.write(description.strip())
            print(f"[{template_name}] Saved description.txt")

    print(f"[{template_name}] Done → {output_dir}")


async def main() -> None:
    _os.makedirs(INPUT_DIR, exist_ok=True)
    pptx_files = glob(join(INPUT_DIR, "*.pptx")) + glob(join(INPUT_DIR, "*.ppt"))
    if not pptx_files:
        print(f"'{INPUT_DIR}/' 폴더에 .pptx 파일이 없습니다.")
        return

    print(f"발견된 파일: {len(pptx_files)}개")
    for pptx_path in pptx_files:
        template_name = splitext(basename(pptx_path))[0]
        print(f"\n{'=' * 50}")
        print(f"처리 중: {pptx_path} → templates/{template_name}/")
        print(f"{'=' * 50}")
        await build_template(pptx_path, template_name)

    print("\n모든 템플릿 변환 완료.")


if __name__ == "__main__":
    asyncio.run(main())
