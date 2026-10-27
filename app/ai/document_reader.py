"""Isolated, hard-time-limited parser child. Reads stdin; never opens user paths."""
import base64
from io import BytesIO
import json
import sys
import warnings


def prepare(content: bytes, mime: str) -> dict:
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("size")
    if mime == "application/pdf":
        from pypdf import PdfReader
        if not content.startswith(b"%PDF-"):
            raise ValueError("signature")
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted or len(reader.pages) > 20:
            raise ValueError("pdf limits")
        parts = []
        raw_parts = []
        for number, page in enumerate(reader.pages, 1):
            # Refuse highly compressed oversized streams before text extraction.
            stream = page.get_contents()
            if stream is not None and len(stream.get_data()) > 8 * 1024 * 1024:
                raise ValueError("page stream limit")
            text = page.extract_text() or ""
            raw_parts.append(text)
            parts.append(f"Página {number}:\n{text}")
            if sum(map(len, parts)) > 24000:
                raise ValueError("text limit")
        raw = "".join(raw_parts)
        return {"text": "\n".join(parts), "manual": len(raw.strip()) < 15}
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 16_000_000
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    with Image.open(BytesIO(content)) as original:
        if original.format not in {"PNG", "JPEG"} or original.width * original.height > 16_000_000:
            raise ValueError("image limits")
        actual = {"PNG": "image/png", "JPEG": "image/jpeg"}[original.format]
        if actual != mime:
            raise ValueError("mime mismatch")
        original.load()
        derivative = ImageOps.exif_transpose(original).convert("RGB")
        derivative.thumbnail((1600, 1600))
        out = BytesIO()
        derivative.save(out, "JPEG", quality=85)
        return {"image": base64.b64encode(out.getvalue()).decode("ascii"), "width": derivative.width, "height": derivative.height}


if __name__ == "__main__":
    try:
        print(json.dumps(prepare(sys.stdin.buffer.read(10 * 1024 * 1024 + 1), sys.argv[1])))
    except Exception:
        print(json.dumps({"error": "unreadable"}))
        sys.exit(2)
