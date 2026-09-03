from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.requests import Confirm, Create, ProfileChange, Review, Revision

router = APIRouter()


def service(request):
    return request.app.state.backend


@router.post("/applications", tags=["applications"])
def create_application(
    body: Create,
    request: Request,
    idempotency_key: str | None = Header(default=None),
):
    return service(request).create(body.rule_version_id, idempotency_key)


@router.get("/applications", tags=["applications"])
def list_applications(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return service(request).list(limit, offset)


@router.get("/applications/{application_id}", tags=["applications"])
def get_application(application_id: str, request: Request):
    return service(request).get(application_id)


@router.post("/applications/{application_id}/documents", tags=["documents"])
def upload_document(
    application_id: str,
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    expected_revision: int = Form(...),
    idempotency_key: str | None = Header(default=None),
):
    backend = service(request)
    try:
        content = file.file.read(backend.settings.max_upload_bytes + 1)
    finally:
        file.file.close()
    return backend.upload(
        application_id,
        document_type,
        content,
        expected_revision,
        idempotency_key,
    )


@router.post("/documents/{version_id}/process", tags=["documents"])
def process_document(
    version_id: str,
    body: Revision,
    request: Request,
    idempotency_key: str | None = Header(default=None),
):
    return service(request).process(
        version_id, body.expected_revision, idempotency_key
    )


@router.get("/process-runs/{run_id}", tags=["documents"])
def get_process_run(run_id: str, request: Request):
    return service(request).get_run(run_id)


@router.get("/documents/{version_id}/content", tags=["documents"])
def document_content(version_id: str, request: Request):
    return FileResponse(
        service(request).content(version_id),
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/documents/{version_id}/extraction", tags=["documents"])
def document_extraction(version_id: str, request: Request):
    return service(request).extraction(version_id)


@router.post("/applications/{application_id}/evaluate", tags=["applications"])
def evaluate_application(application_id: str, body: Revision, request: Request):
    return service(request).evaluate(application_id, body.expected_revision)


@router.post("/applications/{application_id}/reviews", tags=["reviews"])
def submit_review(
    application_id: str,
    body: Review,
    request: Request,
    idempotency_key: str | None = Header(default=None),
):
    return service(request).review(
        application_id,
        body.document_version_id,
        body.action,
        body.corrections,
        body.reason,
        body.expected_revision,
        body.reviewed_page,
        idempotency_key,
    )


@router.post("/applications/{application_id}/confirm-ineligible", tags=["reviews"])
def confirm_ineligible(application_id: str, body: Confirm, request: Request):
    return service(request).confirm(
        application_id,
        body.evaluation_id,
        body.reason,
        body.expected_revision,
    )


@router.post("/applications/{application_id}/profile", tags=["reviews"])
def change_profile(application_id: str, body: ProfileChange, request: Request):
    return service(request).change_profile(
        application_id,
        body.rule_version_id,
        body.expected_revision,
        body.reason,
    )


@router.get("/applications/{application_id}/history", tags=["reviews"])
def history(application_id: str, request: Request):
    return service(request).history(application_id)
