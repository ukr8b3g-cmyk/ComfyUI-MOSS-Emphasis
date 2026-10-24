"""Create a deterministic install ZIP and SHA256SUMS using only the stdlib."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".github", "__pycache__", ".pytest_cache", ".venv", "node_modules", "dist"}

def main():
    version = (ROOT / "RELEASE_TAG").read_text().strip()
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    path = output / f"ComfyUI-MOSS-Emphasis-{version}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in sorted(ROOT.rglob("*")):
            relative = source.relative_to(ROOT)
            if not source.is_file() or source.is_symlink() or any(part in SKIP for part in relative.parts) or source.suffix in {".pyc", ".pyo"}:
                continue
            info = zipfile.ZipInfo("ComfyUI-MOSS-Emphasis/" + relative.as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes())
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("ZIP integrity check failed")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    print(path.name, digest)

if __name__ == "__main__":
    main()
