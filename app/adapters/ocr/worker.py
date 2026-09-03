import json
import sys
from pathlib import Path


def main():
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        device="cpu",
        lang="en",
        ocr_version="PP-OCRv5",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    blocks = []
    for result in ocr.predict(sys.argv[1]):
        for index, text in enumerate(result["rec_texts"]):
            blocks.append(
                {
                    "block_id": f"b{len(blocks) + 1}",
                    "page_number": 1,
                    "text": str(text),
                    "confidence": float(result["rec_scores"][index]),
                    "polygon": result["rec_polys"][index].tolist(),
                }
            )
    Path(sys.argv[2]).write_text(
        json.dumps(blocks, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
