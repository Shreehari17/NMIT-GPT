import uuid

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from backend.auth_utils import require_admin

router = APIRouter(prefix="/admin", tags=["Admin"])

ALLOWED_EXCEL_EXTENSIONS = {"xlsx", "xls"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB - biodata sheets don't need more


def process_excel(file_path: str):
    pass


@router.post("/upload/biodata-excel", dependencies=[require_admin()])
async def upload_excel(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    # The original filename was written straight into the path, so a name
    # like "../../etc/cron.d/x" would escape /tmp. Validate the extension
    # and generate our own filename instead of trusting user input.
    suffix = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if suffix not in ALLOWED_EXCEL_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Only {'/'.join(sorted(ALLOWED_EXCEL_EXTENSIONS))} files are accepted.",
        )

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB).")
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    file_path = f"/tmp/{uuid.uuid4().hex}.{suffix}"
    with open(file_path, "wb") as f:
        f.write(contents)

    background_tasks.add_task(process_excel, file_path)

    return {"status": "processing"}