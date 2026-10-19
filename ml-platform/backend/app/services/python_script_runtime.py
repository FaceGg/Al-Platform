"""Subprocess runtime for the ``python_script`` workflow operator.

User scripts execute in an isolated Python subprocess instead of the backend
process. Imports declared in the script are collected via AST and missing
distributions are auto-installed into a persistent venv (docker named volume)
using only server-configured package sources. Users cannot specify packages
or index URLs: everything is derived from the script's import statements.

An empty ``venv_dir`` disables the venv and executes against the current
interpreter (tests and local runs assume dependencies already exist).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import pandas as pd
import numpy as np

# Common import-name -> distribution-name mapping (import name != pip name).
MODULE_TO_PACKAGE = {
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "OpenSSL": "pyopenssl",
    "Crypto": "pycryptodome",
    "fitz": "pymupdf",
}

# Package names handed to pip are derived from import statements and must be
# plain distribution names: no extras, specifiers, URLs or paths.
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")

_ERROR_MARKER = "PYSCRIPT_ERROR:"

RUNNER_CODE = '''"""python_script operator runner: df -> result, pickle transport."""
import sys

import pandas as pd


def _fail(message):
    sys.stderr.write({marker!r} + str(message))
    sys.stderr.flush()
    raise SystemExit(3)


def main():
    in_path, out_path, script_path = sys.argv[1], sys.argv[2], sys.argv[3]
    df = pd.read_pickle(in_path)
    with open(script_path, "r", encoding="utf-8") as handle:
        code = handle.read()
    scope = {{"df": df, "__name__": "__main__"}}
    try:
        exec(compile(code, "<python_script>", "exec"), scope, scope)
    except BaseException as exc:  # noqa: BLE001 - reported back to the operator
        _fail(f"{{type(exc).__name__}}: {{exc}}")
    result = scope.get("result")
    if result is None:
        _fail("script must assign output to 'result'")
    if isinstance(result, pd.DataFrame):
        result.to_pickle(out_path)
        return
    if isinstance(result, list) and (not result or all(isinstance(row, dict) for row in result)):
        pd.DataFrame(result).to_pickle(out_path)
        return
    _fail("result must be a pandas.DataFrame or a list of records")


main()
'''.format(marker=_ERROR_MARKER)


def collect_import_modules(script: str) -> list[str]:
    """Return unique top-level module names imported anywhere in the script."""
    tree = ast.parse(script, mode="exec")
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    modules.discard("__future__")
    return sorted(modules)


def distribution_names(modules: list[str]) -> list[str]:
    """Map import modules to pip distribution names with strict validation."""
    names: set[str] = set()
    for module in modules:
        name = str(MODULE_TO_PACKAGE.get(module, module)).strip()
        if not _PACKAGE_NAME_RE.match(name):
            raise ValueError(
                f"PythonScript: refusing to install invalid package name "
                f"derived from import '{module}': {name!r}",
            )
        names.add(name)
    return sorted(names)


class _InstallLock:
    """Best-effort cross-process lock guarding pip installs on a shared venv."""

    def __init__(self, path: str, stale_seconds: int = 1800):
        self.path = path
        self.stale_seconds = stale_seconds

    def __enter__(self):
        deadline = time.monotonic() + self.stale_seconds
        while True:
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    if time.monotonic() - os.path.getmtime(self.path) > self.stale_seconds:
                        os.unlink(self.path)
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        "PythonScript: timed out waiting for another install to finish",
                    )
                time.sleep(0.5)

    def __exit__(self, *exc_info):
        try:
            os.close(self._fd)
            os.unlink(self.path)
        except OSError:
            pass
        return False


class PythonScriptRuntime:
    """Execute operator scripts in an isolated subprocess with auto-install."""

    def __init__(
        self,
        venv_dir: str = "",
        pip_sources: list[str] | None = None,
        auto_install: bool = True,
        exec_timeout: int = 300,
        install_timeout: int = 900,
        bootstrap_packages: tuple[str, ...] = ("pandas",),
    ):
        self.venv_dir = (venv_dir or "").strip()
        self.pip_sources = [source for source in (pip_sources or []) if source]
        self.auto_install = auto_install
        self.exec_timeout = max(1, int(exec_timeout))
        self.install_timeout = max(1, int(install_timeout))
        self.bootstrap_packages = tuple(bootstrap_packages)
        self._bootstrap_lock = threading.Lock()

    # -- interpreter resolution ------------------------------------------------

    def _venv_python(self) -> str | None:
        if not self.venv_dir:
            return None
        for candidate in (
            os.path.join(self.venv_dir, "bin", "python"),
            os.path.join(self.venv_dir, "Scripts", "python.exe"),
        ):
            if os.path.isfile(candidate):
                return candidate
        return None

    def _create_venv_at(self, target: str) -> None:
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", target],
                check=True, timeout=300, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError:
            # Some distro images ship python without ensurepip; retry
            # without pip and seed it from the parent interpreter.
            shutil.rmtree(target, ignore_errors=True)
            subprocess.run(
                [sys.executable, "-m", "venv", "--without-pip", target],
                check=True, timeout=300, capture_output=True, text=True,
            )
            tmp_python = self._venv_python_in(target)
            subprocess.run(
                [sys.executable, "-m", "pip", "--python", tmp_python,
                 "install", "--upgrade", "pip"],
                check=True, timeout=self.install_timeout,
                capture_output=True, text=True,
            )

    def _ensure_venv(self) -> str:
        existing = self._venv_python()
        if existing:
            return existing
        with self._bootstrap_lock:
            existing = self._venv_python()
            if existing:
                return existing
            parent = os.path.dirname(self.venv_dir) or "."
            os.makedirs(parent, exist_ok=True)
            tmp_target = os.path.join(
                parent, f".{os.path.basename(self.venv_dir)}.tmp-{os.getpid()}-{threading.get_ident()}",
            )
            try:
                if os.path.ismount(self.venv_dir):
                    # A mountpoint (e.g. a named Docker volume) cannot be
                    # replaced by rename; bootstrap in place under a
                    # cross-process lock instead.
                    lock = _InstallLock(os.path.join(
                        parent, f".{os.path.basename(self.venv_dir)}.bootstrap.lock",
                    ))
                    with lock:
                        existing = self._venv_python()
                        if existing:
                            return existing
                        self._create_venv_at(self.venv_dir)
                else:
                    self._create_venv_at(tmp_target)
                    try:
                        os.rename(tmp_target, self.venv_dir)
                    except OSError:
                        # Another process finished the bootstrap first.
                        pass
            finally:
                shutil.rmtree(tmp_target, ignore_errors=True)
            interpreter = self._venv_python()
            if interpreter is None:
                raise RuntimeError("PythonScript: failed to prepare the script venv")
            if self.bootstrap_packages:
                self._pip_install(
                    interpreter, [self._pinned(pkg) for pkg in self.bootstrap_packages],
                )
            return interpreter

    @staticmethod
    def _pinned(package: str) -> str:
        # The venv subprocess exchanges DataFrames with the parent process via
        # pickle; pandas/numpy must stay on the parent's exact versions or
        # read_pickle fails with internal-array mismatches.
        name = package.casefold()
        if name == "pandas":
            return f"pandas=={pd.__version__}"
        if name == "numpy":
            return f"numpy=={np.__version__}"
        return package

    def _venv_python_in(self, venv_dir: str) -> str:
        for candidate in (
            os.path.join(venv_dir, "bin", "python"),
            os.path.join(venv_dir, "Scripts", "python.exe"),
        ):
            if os.path.isfile(candidate):
                return candidate
        raise RuntimeError(f"PythonScript: venv python not found under {venv_dir}")

    def _resolve_interpreter(self, script: str, auto_install: bool | None = None) -> str:
        if not self.venv_dir:
            return sys.executable
        interpreter = self._ensure_venv()
        effective = self.auto_install if auto_install is None else bool(auto_install)
        if effective:
            external = [
                module for module in collect_import_modules(script)
                if module not in getattr(sys, "stdlib_module_names", frozenset())
            ]
            if external:
                missing = self._probe_missing(interpreter, external)
                if missing:
                    self._pip_install(interpreter, distribution_names(missing))
        return interpreter

    # -- dependency management -------------------------------------------------

    def _probe_missing(self, interpreter: str, modules: list[str]) -> list[str]:
        code = (
            "import importlib.util,sys,json;"
            "print(json.dumps([m for m in sys.argv[1:] "
            "if importlib.util.find_spec(m) is None]))"
        )
        try:
            proc = subprocess.run(
                [interpreter, "-c", code, *modules],
                capture_output=True, text=True, timeout=120,
                env=self._child_env(for_pip=False),
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("PythonScript: dependency probe timed out") from error
        if proc.returncode != 0:
            raise RuntimeError(
                f"PythonScript: dependency probe failed: {self._tail(proc.stderr)}",
            )
        try:
            return [str(item) for item in json.loads(proc.stdout.strip().splitlines()[-1])]
        except (ValueError, IndexError) as error:
            raise RuntimeError("PythonScript: dependency probe returned no data") from error

    def _pip_install(self, interpreter: str, packages: list[str]) -> None:
        for name in packages:
            if not _PACKAGE_NAME_RE.match(name):
                raise ValueError(
                    f"PythonScript: refusing to install invalid package name {name!r}",
                )
        command = [interpreter, "-m", "pip", "install", "--disable-pip-version-check",
                   "--no-input", "-q"]
        if self.pip_sources:
            command += ["--index-url", self.pip_sources[0]]
            for extra in self.pip_sources[1:]:
                command += ["--extra-index-url", extra]
        command += sorted(packages)
        # Keep pandas/numpy aligned with the parent interpreter (pickle contract).
        constraint_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
                handle.write(f"pandas=={pd.__version__}\nnumpy=={np.__version__}\n")
                constraint_path = handle.name
            command += ["--constraint", constraint_path]
            lock = _InstallLock(os.path.join(
                os.path.dirname(self.venv_dir) or ".", f".{os.path.basename(self.venv_dir)}.pip.lock",
            ))
            with lock:
                try:
                    proc = subprocess.run(
                        command, capture_output=True, text=True,
                        timeout=self.install_timeout, env=self._child_env(for_pip=True),
                    )
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError(
                        f"PythonScript: pip install of {', '.join(sorted(packages))} "
                        f"timed out after {self.install_timeout}s",
                    ) from error
            if proc.returncode != 0:
                raise RuntimeError(
                    f"PythonScript: auto-install failed for "
                    f"{', '.join(sorted(packages))}: {self._tail(proc.stderr)}",
                )
        finally:
            if constraint_path:
                try:
                    os.unlink(constraint_path)
                except OSError:
                    pass

    # -- subprocess execution --------------------------------------------------

    def execute(
        self,
        script: str,
        df: pd.DataFrame,
        auto_install: bool | None = None,
    ) -> pd.DataFrame:
        interpreter = self._resolve_interpreter(script, auto_install=auto_install)
        with tempfile.TemporaryDirectory(prefix="pyscript-") as tmp:
            script_path = os.path.join(tmp, "script.py")
            in_path = os.path.join(tmp, "input.pkl")
            out_path = os.path.join(tmp, "output.pkl")
            runner_path = os.path.join(tmp, "runner.py")
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write(script)
            with open(runner_path, "w", encoding="utf-8") as handle:
                handle.write(RUNNER_CODE)
            df.to_pickle(in_path)
            try:
                proc = subprocess.run(
                    [interpreter, runner_path, in_path, out_path, script_path],
                    capture_output=True, text=True, timeout=self.exec_timeout,
                    env=self._child_env(for_pip=False, tmp=tmp), cwd=tmp,
                )
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    f"PythonScript script error: execution timed out after "
                    f"{self.exec_timeout}s",
                ) from error
            if proc.returncode == 0:
                if not os.path.isfile(out_path):
                    raise RuntimeError(
                        "PythonScript script error: runner produced no output",
                    )
                return pd.read_pickle(out_path)
            raise RuntimeError(
                f"PythonScript script error: {self._extract_error(proc.stderr, proc.stdout)}",
            )

    # -- environment helpers ---------------------------------------------------

    def _child_env(self, for_pip: bool, tmp: str | None = None) -> dict[str, str]:
        """Minimal child env: never leak backend environment (secrets) onward."""
        env: dict[str, str] = {}
        bindir = os.path.dirname(sys.executable)
        path_parts = [bindir, "/usr/local/bin", "/usr/bin", "/bin"]
        env["PATH"] = os.pathsep.join(path_parts)
        home = tmp or (self.venv_dir if self.venv_dir else tempfile.gettempdir())
        env["HOME"] = home
        env.setdefault("LANG", "C.UTF-8")
        env.setdefault("LC_ALL", "C.UTF-8")
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if tmp:
            env["TMPDIR"] = tmp
        for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "SSL_CERT_DIR"):
            if name in os.environ:
                env[name] = os.environ[name]
        if for_pip:
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
                         "http_proxy", "https_proxy", "no_proxy"):
                if name in os.environ:
                    env[name] = os.environ[name]
        return env

    @staticmethod
    def _tail(text: str, limit: int = 800) -> str:
        cleaned = (text or "").strip()
        return cleaned[-limit:] if cleaned else "(no output)"

    def _extract_error(self, stderr: str, stdout: str) -> str:
        for stream in (stderr, stdout):
            for line in reversed((stream or "").splitlines()):
                if line.startswith(_ERROR_MARKER):
                    return line[len(_ERROR_MARKER):].strip() or "(empty error)"
        return self._tail(stderr)
