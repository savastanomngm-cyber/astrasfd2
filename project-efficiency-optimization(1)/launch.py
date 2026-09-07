from pathlib import Path
import hashlib
import os
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if sys.version_info < (3, 11):
        raise SystemExit("Gamma Lab requires Python 3.11 or newer. Install Python 3.12 from python.org and reopen the launcher.")
    try:
        healthy = python.exists() and subprocess.run(
            [str(python), "-c", "import encodings, pip"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except OSError:
        healthy = False
    if not healthy:
        # Resolve shim paths so the venv points at the actual Python standard library.
        subprocess.check_call([str(Path(sys.executable).resolve()), "-m", "venv", str(environment)])
    requirements = root / "requirements.txt"
    fingerprint = hashlib.sha256(requirements.read_bytes() + sys.version.encode()).hexdigest()
    marker = environment / ".requirements-sha256"
    if not healthy or not marker.exists() or marker.read_text() != fingerprint:
        subprocess.check_call([str(python), "-m", "pip", "install", "-r", str(requirements)])
        marker.write_text(fingerprint)
    args = sys.argv[1:]
    if "--setup" in args:
        return
    if "--test" in args:
        args.remove("--test")
        raise SystemExit(subprocess.call([str(python), "-m", "pytest", "-q", *args]))
    raise SystemExit(subprocess.call([str(python), "-m", "streamlit", "run", str(root / "terminal.py"), "--server.address", "127.0.0.1", *args]))


if __name__ == "__main__":
    main()
