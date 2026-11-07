"""Download pinned official Windows builds and verify their SHA-256 checksums."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile
import tarfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
PROMETHEUS = "3.16.0"
GRAFANA = "13.3.0"


def download(url, target):
    if not target.exists():
        print(f"Downloading {url}", flush=True)
        request = urllib.request.Request(url, headers={"User-Agent": "apm-lab"})
        with urllib.request.urlopen(request, timeout=120) as source:
            temporary = target.with_suffix(target.suffix + ".part")
            with temporary.open("wb") as destination:
                while chunk := source.read(1024 * 1024):
                    destination.write(chunk)
            temporary.replace(target)
    return target


def install(name, url, checksum_url, archive_name, expected=None):
    destination = TOOLS / name
    if (destination / ".verified").exists():
        print(f"{name}: already installed", flush=True)
        return
    archive = download(url, TOOLS / archive_name)
    if expected is None:
        checksum_file = download(checksum_url, TOOLS / (name + "-checksums.txt"))
        lines = checksum_file.read_text().splitlines()
        expected = next((line.split()[0] for line in lines
                         if archive_name in line or len(lines) == 1), None)
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected:
        raise RuntimeError(f"Checksum mismatch for {archive_name}: {actual} != {expected}")
    destination.mkdir(exist_ok=True)
    if archive_name.endswith(".zip"):
        with zipfile.ZipFile(archive) as package:
            package.extractall(destination)
    else:
        with tarfile.open(archive) as package:
            package.extractall(destination, filter="data")
    (destination / ".verified").write_text(actual)
    print(f"{name}: SHA-256 verified, extracted", flush=True)


def main():
    TOOLS.mkdir(exist_ok=True)
    prom_name = f"prometheus-{PROMETHEUS}.windows-amd64.zip"
    prom_base = f"https://github.com/prometheus/prometheus/releases/download/v{PROMETHEUS}"
    install("prometheus", f"{prom_base}/{prom_name}",
            f"{prom_base}/sha256sums.txt", prom_name)
    grafana_name = f"grafana_{GRAFANA}_40412481033_windows_amd64.tar.gz"
    grafana_url = f"https://dl.grafana.com/grafana/release/{GRAFANA}/{grafana_name}"
    # Published at https://grafana.com/grafana/download/13.3.0?edition=oss&platform=windows
    install("grafana", grafana_url, None, grafana_name,
            "748358c29405b50b28c67792f264b5a49c07faf4c2c353b652db3ab751bb874d")
    (TOOLS / "versions.json").write_text(json.dumps({
        "prometheus": PROMETHEUS, "grafana": GRAFANA}, indent=2))


if __name__ == "__main__":
    main()
