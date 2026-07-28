"""
OCR microservice using Baidu's Unlimited-OCR model.

Accepts PDF or image files, runs OCR via Baidu/Unlimited-OCR (a HuggingFace
transformer model), and returns the extracted text. Designed to be called from
the browser extension's background worker to extract text from Drive catalogue
PDFs for better semantic matching.

Runs in Docker with GPU support (CUDA) or CPU fallback.
"""

import io
import os
import secrets
import tempfile
from pathlib import Path
from typing import Optional

import pypdfium2 as pdfium
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from PIL import Image
from pydantic import BaseModel

import api_keys

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
if not ADMIN_TOKEN:
    ADMIN_TOKEN = secrets.token_urlsafe(24)
    print(f"[ocr-service] ADMIN_TOKEN not set - generated one for this run: {ADMIN_TOKEN}")

# Model configuration
MODEL_NAME = os.environ.get("OCR_MODEL", "baidu/Unlimited-OCR")
USE_GPU = os.environ.get("OCR_USE_GPU", "1" if os.environ.get("CUDA_VISIBLE_DEVICES") else "0") == "1"

app = FastAPI(title="OCR Service (Baidu Unlimited-OCR)")

# Lazy-loaded model singleton
_model = None


def get_model():
    global _model
    if _model is None:
        from transformers import AutoModel
        print(f"[ocr-service] Loading model {MODEL_NAME} (GPU={USE_GPU})...")
        _model = AutoModel.from_pretrained(
            MODEL_NAME,
            trust_remote_code=True,
            device_map="auto" if USE_GPU else "cpu",
        )
        print("[ocr-service] Model loaded.")
    return _model


def require_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key or not api_keys.is_key_active(x_api_key):
        raise HTTPException(status_code=401, detail="Missing or inactive API key.")


def require_admin(x_admin_token: Optional[str] = Header(None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token.")


def pdf_to_images(pdf_bytes: bytes, dpi: int = 200) -> list:
    """Convert a PDF's pages to PIL Image objects using pypdfium2."""
    images = []
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        pdf = pdfium.PdfDocument(tmp_path)
        for page_num in range(len(pdf)):
            page = pdf[page_num]
            bitmap = page.render(scale=dpi / 72)
            pil_image = bitmap.to_pil()
            images.append(pil_image)
    finally:
        os.unlink(tmp_path)
    return images


class OcrResponse(BaseModel):
    text: str
    pages: int


@app.post("/ocr", response_model=OcrResponse, dependencies=[Depends(require_api_key)])
async def ocr(file: UploadFile = File(...)):
    """Extract text from an uploaded PDF or image file."""
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    filename = file.filename or ""
    is_pdf = filename.lower().endswith(".pdf") or contents[:4] == b"%PDF"

    model = get_model()
    all_text = []

    if is_pdf:
        images = pdf_to_images(contents)
    else:
        # Single image file
        images = [Image.open(io.BytesIO(contents))]

    for img in images:
        # Convert PIL to RGB if needed (Unlimited-OCR expects RGB)
        if img.mode != "RGB":
            img = img.convert("RGB")
        try:
            result = model.chat(img)
            # model returns text directly or as a dict
            if isinstance(result, str):
                all_text.append(result)
            elif isinstance(result, dict):
                all_text.append(result.get("text", result.get("response", "")))
            elif isinstance(result, list):
                # May return a list of [role, content] pairs
                texts = []
                for item in result:
                    if isinstance(item, dict):
                        texts.append(item.get("content", item.get("text", "")))
                    elif isinstance(item, str):
                        texts.append(item)
                all_text.append(" ".join(texts))
            else:
                all_text.append(str(result))
        except Exception as e:
            print(f"[ocr-service] Page OCR failed: {e!r}")
            all_text.append("")

    combined = "\n\n".join(
        f"[Page {i+1}] {t}" if is_pdf else t
        for i, t in enumerate(all_text) if t.strip()
    )

    return OcrResponse(text=combined, pages=len(images))


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "gpu": USE_GPU}


# --- Key management (admin only) ---

class CreateKeyRequest(BaseModel):
    label: str = ""


class SetActiveRequest(BaseModel):
    active: bool


@app.get("/admin/keys", dependencies=[Depends(require_admin)])
def admin_list_keys():
    return api_keys.list_keys()


@app.post("/admin/keys", dependencies=[Depends(require_admin)])
def admin_create_key(request: CreateKeyRequest):
    return api_keys.create_key(request.label)


@app.patch("/admin/keys/{key_id}", dependencies=[Depends(require_admin)])
def admin_set_active(key_id: str, request: SetActiveRequest):
    entry = api_keys.set_active(key_id, request.active)
    if entry is None:
        raise HTTPException(status_code=404, detail="Key not found.")
    return entry


@app.delete("/admin/keys/{key_id}", dependencies=[Depends(require_admin)])
def admin_delete_key(key_id: str):
    if not api_keys.delete_key(key_id):
        raise HTTPException(status_code=404, detail="Key not found.")
    return {"deleted": key_id}


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return (Path(__file__).parent / "admin.html").read_text() if (Path(__file__).parent / "admin.html").exists() else "<html><body><h1>OCR Service Admin</h1></body></html>"


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("OCR_PORT", "8002"))
    print(f"[ocr-service] Starting on port {port} (GPU={USE_GPU})")
    uvicorn.run(app, host="0.0.0.0", port=port)

