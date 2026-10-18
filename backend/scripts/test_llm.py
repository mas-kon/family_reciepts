"""Compare LLM models on real receipt photos without touching the database.

    uv run python scripts/test_llm.py photo1.jpg [photo2.jpg ...] [--models a,b,c]

Prints recognised JSON, time and a sum check for each model, so you can pick the best one
for LLM_MODELS in .env.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from app.config import get_settings
from app.db.seed import DEFAULT_CATEGORIES
from app.llm.client import LLMClient, LLMError
from app.llm.prompt import receipt_system
from app.receipts.qr import find_fiscal_qr

register_heif_opener()


def category_paths() -> list[str]:
    out = []
    for parent, children in DEFAULT_CATEGORIES.items():
        out += [f"{parent} / {c}" for c in children] if children else [parent]
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photos", nargs="+", type=Path)
    ap.add_argument("--models", help="comma-separated; default LLM_MODELS from .env")
    ap.add_argument("--quiet", action="store_true", help="do not print full JSON")
    args = ap.parse_args()

    models = args.models.split(",") if args.models else get_settings().models
    client = LLMClient()
    system = receipt_system(category_paths())

    for photo in args.photos:
        image = ImageOps.exif_transpose(Image.open(photo))
        image.load()
        qr, raw, rotation = find_fiscal_qr(image)
        if rotation:
            image = image.rotate(rotation, expand=True)
        print(f"\n=== {photo.name} ===")
        print(f"QR: {qr or raw or 'не найден'}")
        for model in models:
            t0 = time.monotonic()
            try:
                res = await client.parse_receipt(image, system, [model])
            except LLMError as e:
                print(f"\n--- {model}: ОШИБКА за {time.monotonic() - t0:.1f}s\n{e}")
                continue
            d = res.data
            items_sum = sum(i.total for i in d.items)
            ok = d.total is not None and abs(items_sum - d.total) <= 0.05
            qr_ok = "" if not qr else (" QR ✓" if d.total and abs(d.total - qr.amount) <= 0.05 else " QR ✗")
            print(
                f"\n--- {model}: {time.monotonic() - t0:.1f}s, {d.store}, {d.purchased_at}, "
                f"итог {d.total} €, позиций {len(d.items)}, сумма позиций {items_sum:.2f} "
                f"{'✓' if ok else '✗'}{qr_ok}"
            )
            if not args.quiet:
                print(json.dumps(res.raw, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
