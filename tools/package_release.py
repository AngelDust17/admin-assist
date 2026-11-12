"""Create a source-only upload archive; never include working databases."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / "admin-assist-deploy.zip"
FILES = ["app.py", "database.py", "domain.py", "investigation.py", "wsgi.py",
         "start.bat", "README.md", "DEPLOYMENT.md", ".gitignore"]
SUFFIXES = {".py", ".js", ".cjs", ".html", ".css", ".svg", ".md", ".yml"}


def main():
    files = [ROOT / name for name in FILES]
    for directory in ("web", "tests", "deploy", "tools", ".github"):
        files.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and not path.is_symlink() and path.suffix in SUFFIXES)
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, "admin-assist/" + path.relative_to(ROOT).as_posix())
    print(f"Created: {OUTPUT.name}; files: {len(files)}; working data excluded.")


if __name__ == "__main__":
    main()
