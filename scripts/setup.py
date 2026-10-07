"""Shared setup implementation for PowerShell, Git Bash, and macOS Bash."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, env):
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true", help="Also install test and lint tools.")
    parser.add_argument("--python", default="3.12", help="Python version for the uv environment.")
    args = parser.parse_args()
    env = os.environ.copy()
    uv = shutil.which("uv")
    if uv:
        uv_command = [uv]
    else:
        # Bootstrap locally rather than changing the participant's global Python.
        tools = ROOT / ".tools"
        if not (tools / "uv" / "__main__.py").exists():
            print("Installing uv into the SDK's .tools directory.", flush=True)
            run([sys.executable, "-m", "pip", "install", "--target", str(tools), "uv"], env)
        env["PYTHONPATH"] = str(tools) + os.pathsep + env.get("PYTHONPATH", "")
        uv_command = [sys.executable, "-m", "uv"]

    environment = ROOT / ".venv"
    if not (environment / "pyvenv.cfg").exists():
        run([*uv_command, "venv", "--python", args.python, str(environment)], env)
    else:
        print("Reusing .venv. The --python option applies when creating a new environment.")
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    requirements = "requirements-dev.txt" if args.dev else "requirements.txt"
    run([*uv_command, "pip", "install", "--python", str(python), "-r", requirements], env)

    target = ROOT / ".env"
    try:
        with target.open("x", encoding="utf-8", newline="\n") as output:
            output.write((ROOT / ".env.example").read_text(encoding="utf-8"))
        print("Created .env. Set API_KEY and check COMPETITION_ID before running main.py.")
    except FileExistsError:
        print("Preserved your existing .env.")
    print("Setup complete. Run the strategy without activating the environment:")
    print(r"  PowerShell: .\.venv\Scripts\python.exe main.py")
    print("  Git Bash:   .venv/Scripts/python.exe main.py")
    print("  macOS:      .venv/bin/python main.py")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print("Setup failed. Fix the command error above and rerun setup.", file=sys.stderr)
        sys.exit(error.returncode or 1)
