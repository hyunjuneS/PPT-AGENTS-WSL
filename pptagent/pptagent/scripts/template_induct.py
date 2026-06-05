"""
Induct a single PowerPoint file into a reusable PPTAgent template.

Usage:
    python -m pptagent.scripts.template_induct \\
        --pptx my_slide.pptx \\
        --name my_template \\
        --api-base https://api.openai.com/v1 \\
        --api-key sk-... \\
        --language-model gpt-4o \\
        --vision-model gpt-4o \\
        --description "My custom template"

The script creates:
    pptagent/templates/<name>/
        source.pptx
        slide_induction.json
        image_stats.json
        description.txt
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pptagent.induct import SlideInducter
from pptagent.llms import AsyncLLM
from pptagent.model_utils import get_image_model
from pptagent.multimodal import ImageLabler
from pptagent.presentation import Presentation
from pptagent.utils import Config, package_join, ppt_to_images


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Induct a PowerPoint file into a PPTAgent template",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--pptx", required=True, help="Path to the source .pptx file")
    parser.add_argument("--name", required=True, help="Template name (folder name under templates/)")
    parser.add_argument("--api-base", required=True, help="LLM API base URL (e.g. https://api.openai.com/v1)")
    parser.add_argument("--api-key", required=True, help="LLM API key")
    parser.add_argument("--language-model", default="gpt-4o", help="Language model name")
    parser.add_argument("--vision-model", default="gpt-4o", help="Vision language model name")
    parser.add_argument("--description", default="", help="Short description of the template")
    parser.add_argument(
        "--embedding-device",
        default=None,
        help="Device for image embedding model (cuda / cpu). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run induction even if slide_induction.json already exists",
    )
    return parser.parse_args()


async def induct(args: argparse.Namespace) -> None:
    pptx_path = Path(args.pptx).resolve()
    if not pptx_path.exists():
        print(f"Error: {pptx_path} not found", file=sys.stderr)
        sys.exit(1)

    templates_dir = Path(package_join("templates"))
    template_dir = templates_dir / args.name
    template_dir.mkdir(parents=True, exist_ok=True)

    dest_pptx = template_dir / "source.pptx"
    slide_images_dir = template_dir / "slide_images"
    template_images_dir = template_dir / "template_images"
    image_stats_path = template_dir / "image_stats.json"
    slide_induction_path = template_dir / "slide_induction.json"
    description_path = template_dir / "description.txt"

    if slide_induction_path.exists() and not args.force:
        print(f"Template '{args.name}' already exists. Use --force to re-run induction.")
        sys.exit(0)

    # ── 1. Copy and normalise the source PPT ──────────────────────────────
    print(f"[1/5] Loading {pptx_path.name} ...")
    config = Config(str(template_dir))
    prs = Presentation.from_file(str(pptx_path), config)
    prs.save(str(dest_pptx))
    print(f"      Saved normalised source to {dest_pptx}")

    # ── 2. Render slide images ────────────────────────────────────────────
    print("[2/5] Rendering slide images ...")
    slide_images_dir.mkdir(exist_ok=True)
    template_images_dir.mkdir(exist_ok=True)

    prs = Presentation.from_file(str(dest_pptx), config)
    await ppt_to_images(str(dest_pptx), str(slide_images_dir))

    layout_pptx = template_dir / "template.pptx"
    prs.save(str(layout_pptx), layout_only=True)
    await ppt_to_images(str(layout_pptx), str(template_images_dir))
    print(f"      {len(prs.slides)} slides rendered")

    # ── 3. Caption images with vision model ───────────────────────────────
    print(f"[3/5] Captioning images with {args.vision_model} ...")
    language_model = AsyncLLM(
        model=args.language_model,
        base_url=args.api_base,
        api_key=args.api_key,
    )
    vision_model = AsyncLLM(
        model=args.vision_model,
        base_url=args.api_base,
        api_key=args.api_key,
    )

    prs = Presentation.from_file(str(dest_pptx), config)
    labler = ImageLabler(prs, config)

    if image_stats_path.exists() and not args.force:
        print("      image_stats.json found, skipping caption step")
        labler.apply_stats(json.loads(image_stats_path.read_text()))
    else:
        caption = await labler.caption_images_async(vision_model)
        image_stats_path.write_text(json.dumps(caption, indent=4, ensure_ascii=False))
        labler.apply_stats(caption)
        print(f"      Saved {image_stats_path.name}")

    # ── 4. Load image embedding model ─────────────────────────────────────
    print("[4/5] Loading image embedding model (google/vit-base-patch16-224-in21k) ...")
    if args.embedding_device:
        device = args.embedding_device
    else:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"      Using device: {device}")
    image_models = get_image_model(device=device)

    # ── 5. Run slide induction ─────────────────────────────────────────────
    print("[5/5] Running slide layout induction ...")
    prs = Presentation.from_file(str(dest_pptx), config)
    labler = ImageLabler(prs, config)
    labler.apply_stats(json.loads(image_stats_path.read_text()))

    inducter = SlideInducter(
        prs,
        str(slide_images_dir),
        str(template_images_dir),
        config,
        image_models,
        language_model,
        vision_model,
    )
    layout_result = await inducter.layout_induct()
    reference = await inducter.content_induct(layout_result)
    slide_induction_path.write_text(json.dumps(reference, indent=4, ensure_ascii=False))
    print(f"      Saved {slide_induction_path.name}")

    # ── Write description ──────────────────────────────────────────────────
    if args.description:
        description_path.write_text(args.description)
    elif not description_path.exists():
        description_path.write_text(f"Custom template: {args.name}")

    print(f"\nDone. Template '{args.name}' is ready at {template_dir}")
    print("Restart webui.py (or pptagent-mcp) to pick up the new template.")


def main():
    args = parse_args()
    asyncio.run(induct(args))


if __name__ == "__main__":
    main()
