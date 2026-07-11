from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OLD_URL = "https://github.com/chmajster/" + "Home-Assistant-Monitoring"
NEW_URL = "https://github.com/chmajster/Home-Assistant-Addon-Infrastructure-Monitoring"
REQUIRED_CONFIG = {
    "name",
    "version",
    "slug",
    "description",
    "url",
    "arch",
    "startup",
    "boot",
    "ingress",
    "options",
    "schema",
}


def fail(errors: list[str], message: str) -> None:
    errors.append(f"ERROR: {message}")


def main() -> int:
    errors: list[str] = []
    repository = yaml.safe_load((ROOT / "repository.yaml").read_text(encoding="utf-8"))
    config = yaml.safe_load((ROOT / "monitoring_center/config.yaml").read_text(encoding="utf-8"))
    missing = REQUIRED_CONFIG - set(config or {})
    if missing:
        fail(errors, f"monitoring_center/config.yaml: brak pól {sorted(missing)}")
    if repository.get("url") != NEW_URL or config.get("url") != NEW_URL:
        fail(errors, "adres repozytorium w metadanych nie wskazuje aktualnego projektu")
    expected_arch = {"amd64", "aarch64"}
    if set(config.get("arch", [])) != expected_arch:
        fail(errors, f"arch musi wynosić dokładnie {sorted(expected_arch)}")

    package_text = (ROOT / "monitoring_center/monitoring_center/__init__.py").read_text(encoding="utf-8")
    docker_text = (ROOT / "monitoring_center/Dockerfile").read_text(encoding="utf-8")
    package_match = re.search(r'__version__\s*=\s*["\']([^"\']+)', package_text)
    image_match = re.search(r"ARG BUILD_VERSION=([^\s]+)", docker_text)
    versions = {
        "add-on": str(config.get("version")),
        "pakiet": package_match.group(1) if package_match else "<brak>",
        "obraz": image_match.group(1) if image_match else "<brak>",
    }
    if len(set(versions.values())) != 1:
        fail(errors, f"niespójne wersje: {versions}")

    text_extensions = {".md", ".yaml", ".yml", ".py", ".js", ".html", ".css", ".json", ".sh", ""}
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "wheels" in path.parts or path.suffix not in text_extensions:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if OLD_URL in text:
            fail(errors, f"stary URL repozytorium: {path.relative_to(ROOT)}")

    requirements = []
    for line in (ROOT / "monitoring_center/requirements.txt").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            if "==" not in line:
                fail(errors, f"nieprzypięta zależność runtime: {line}")
            requirements.append(line.split("==", 1)[0].lower().replace("-", "_"))
    wheel_names = {path.name.lower().replace("-", "_") for path in (ROOT / "monitoring_center/wheels").glob("*.whl")}
    for requirement in requirements:
        if not any(name.startswith(f"{requirement}_") for name in wheel_names):
            fail(errors, f"brak wheel dla zależności {requirement}")
    for binary in ("cryptography", "cffi", "pydantic_core"):
        for arch in ("x86_64", "aarch64"):
            if not any(name.startswith(f"{binary}_") and arch in name for name in wheel_names):
                fail(errors, f"brak {binary} dla {arch}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"OK: metadane, wersja {versions['add-on']}, architektury i wheelhouse są spójne")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
