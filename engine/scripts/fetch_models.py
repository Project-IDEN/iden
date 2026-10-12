"""Download the models in `models.toml` and check every byte against it.

    uv run python -m scripts.fetch_models

Each download is verified before anything is extracted from it, and each
extracted file again after, so a model that runs is always the reviewed one.
Files already present and matching are left alone.
"""

import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

from engine.config import settings
from engine.manifest import load
from engine.runtime import sha256_of


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=600) as response:
        return response.read()


def main() -> None:
    manifest = load(settings.engine_manifest)
    model_dir = settings.engine_model_dir
    wanted = {model.file: model.sha256 for model in manifest.model_files()}

    def present(name: str) -> bool:
        path = model_dir / name
        return path.is_file() and sha256_of(path) == wanted[name]

    for source in manifest.sources:
        names = source.extract or [source.file or ""]
        if all(present(name) for name in names):
            print(f"ok      {', '.join(names)}")
            continue

        print(f"fetch   {source.url}")
        data = _download(source.url)
        if hashlib.sha256(data).hexdigest() != source.sha256:
            sys.exit(f"{source.url} does not match its sha256; refusing it.")

        if source.extract:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                files = {name: archive.read(name) for name in source.extract}
        else:
            files = {names[0]: data}

        for name, content in files.items():
            target = model_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            Path(target).write_bytes(content)
            if sha256_of(target) != wanted[name]:
                target.unlink()
                sys.exit(f"{name} does not match the manifest; removed it.")
            print(f"wrote   {target}")


if __name__ == "__main__":
    main()
