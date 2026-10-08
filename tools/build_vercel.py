"""Build static public assets without uploading private sensor data or docs."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web"
OUTPUT = ROOT / "public"
ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".json", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ttf", ".woff", ".woff2"}


def build():
    OUTPUT.mkdir(exist_ok=True)
    for source in SOURCE.rglob("*"):
        if not source.is_file():
            continue
        if source.suffix.lower() not in ALLOWED_EXTENSIONS and not source.name.endswith("-OFL.txt"):
            continue
        target = OUTPUT / source.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (OUTPUT / "runtime-config.js").write_text('window.DINING_API_BASE = window.location.origin + "/api";\n', encoding="utf-8")
    print(f"Static Vercel output ready: {OUTPUT}")


if __name__ == "__main__":
    build()
