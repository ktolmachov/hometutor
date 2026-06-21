from __future__ import annotations

from fastapi import APIRouter, HTTPException

import app.api_services as services
from app.api_helpers import record_api_error
from app.path_safety import validate_data_relative_path

router = APIRouter(tags=["files"])


@router.get("/explain/file")
def explain_file_endpoint(relative_path: str):
    try:
        relative_path = validate_data_relative_path(relative_path)
        return services.explain_file(relative_path)
    except FileNotFoundError as e:
        record_api_error(endpoint="/explain/file", exc=e, status_code=404)
        raise HTTPException(
            status_code=404,
            detail=(
                f"{e}. Файл отсутствует в текущей директории data/. "
                "Возможно, источник устарел после изменения файлов или нужна переиндексация."
            ),
        )
    except ValueError as e:
        record_api_error(endpoint="/explain/file", exc=e, status_code=400)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 - files API boundary records unexpected file/service failures as controlled HTTP 500.
        record_api_error(endpoint="/explain/file", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Explain file failed: {type(e).__name__}: {e}",
        )


@router.get("/content/file")
def content_file(relative_path: str):
    try:
        relative_path = validate_data_relative_path(relative_path)
        return services.get_file_content(relative_path)
    except FileNotFoundError as e:
        record_api_error(endpoint="/content/file", exc=e, status_code=404)
        raise HTTPException(
            status_code=404,
            detail=(
                f"{e}. Файл отсутствует в текущей директории data/. "
                "Возможно, источник устарел после изменения файлов или нужна переиндексация."
            ),
        )
    except ValueError as e:
        record_api_error(endpoint="/content/file", exc=e, status_code=400)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 - files API boundary records unexpected file/service failures as controlled HTTP 500.
        record_api_error(endpoint="/content/file", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Content file failed: {type(e).__name__}: {e}",
        )
