"""One-shot parser process. Receives trusted API-generated temporary paths only."""
import json
from pathlib import Path
import sys

from services.upload_validation import validate_upload
from services.image_module import image_module
from services.pdf_module import pdf_module
from services.pdf_tools import MAX_MERGE_FILES


def execute(request: dict) -> dict:
    from api.server import _info_action, _transform

    operation = request["operation"]
    work = Path(request["work"]).resolve()
    if not work.is_dir():
        raise ValueError("Рабочая папка недоступна")

    if operation == "validate_only":
        validate_upload(work / ("source" + request["suffix"]), request["suffix"])
        return {"ok": True}
    if operation == "single":
        source = work / ("source" + request["suffix"])
        validate_upload(source, request["suffix"])
        info = _info_action(source, request["action"])
        if info is not None:
            return {"ok": True, "info": info}
        target = _transform(source, work, request["action"], request["pages"])
    elif operation == "batch":
        paths = [work / ("image_" + str(i) + suffix) for i, suffix in enumerate(request["suffixes"])]
        for path, suffix in zip(paths, request["suffixes"]):
            validate_upload(path, suffix)
        target = work / "fileshape_photos.pdf"
        image_module.bundle_as_pdf(paths, target)
    elif operation == "pdf_merge":
        # Paths are built only from API-owned workspace and bounded indices.
        count = request.get("count")
        if type(count) is not int or not 2 <= count <= MAX_MERGE_FILES:
            raise ValueError("Выбери от 2 до 5 PDF")
        paths = [work / f"pdf_{index}.pdf" for index in range(count)]
        for path in paths:
            validate_upload(path, ".pdf")
        target = work / "merged.pdf"
        pdf_module.merge(paths, target)
    else:
        raise ValueError("Недопустимая операция")
    if not target.is_file() or target.stat().st_size == 0:
        raise ValueError("Пустой результат")
    return {"ok": True, "filename": target.name, "bytes": target.stat().st_size}


def main():
    try:
        request = json.load(sys.stdin)
        result = execute(request)
    except ValueError as exc:
        result = {"ok": False, "error": str(exc)[:200]}
    except Exception:
        result = {"ok": False, "error": "Не удалось обработать файл"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
