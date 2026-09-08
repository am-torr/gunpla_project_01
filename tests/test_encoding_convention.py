"""AC5 -- every file open in the new/changed Python passes encoding="utf-8".

This box's locale default is cp1252.  A bare ``open(path)`` silently mangles
Japanese kit names on write and raises UnicodeDecodeError on read, and neither
failure shows up until a non-ASCII item lands in the feed.  The rule is therefore
enforced mechanically rather than by review.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

import gunpla_official_news

PACKAGE_DIR = pathlib.Path(gunpla_official_news.__file__).resolve().parent
TESTS_DIR = pathlib.Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

#: Files copied verbatim from the reference project and NOT changed by this batch.
#: They are covered by test_regression_baseline.py instead; re-formatting them to
#: satisfy a new convention would itself be the regression.
UNCHANGED = {
    "config.py",
    "dedupe.py",
    "runner.py",
    "template.py",
    "__init__.py",
}

#: Callables whose file handle must carry an explicit encoding.
_OPENERS = {"open", "io.open", "pathlib.Path.open", "read_text", "write_text"}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _files_under_test():
    files = [p for p in PACKAGE_DIR.rglob("*.py") if p.name not in UNCHANGED]
    files += list(TESTS_DIR.glob("*.py"))
    files.append(ROOT / "conftest.py")
    return sorted(set(files))


def test_there_is_something_to_check():
    assert len(_files_under_test()) >= 10


@pytest.mark.parametrize(
    "path", _files_under_test(), ids=lambda p: str(pathlib.Path(p).name)
)
def test_every_open_passes_encoding_utf8(path):
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=str(path))

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in _OPENERS:
            continue
        # Binary mode needs no encoding and must not be given one.
        mode = ""
        if name in ("open",) and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            mode = str(node.args[1].value)
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = str(kw.value.value)
        if "b" in mode:
            continue

        encodings = [
            kw.value
            for kw in node.keywords
            if kw.arg == "encoding" and isinstance(kw.value, ast.Constant)
        ]
        if not encodings:
            offenders.append((node.lineno, name, "no encoding= argument"))
        elif str(encodings[0].value).lower().replace("-", "") != "utf8":
            offenders.append((node.lineno, name, "encoding=%r" % encodings[0].value))

    assert not offenders, "%s: %s" % (path, offenders)


def test_output_writes_pin_newline_so_line_endings_do_not_drift():
    """Exported .md/.json must not gain CRLF from Windows text mode."""
    from gunpla_official_news import brief, working_data

    for module in (brief, working_data):
        with open(module.__file__, "r", encoding="utf-8") as fh:
            source = fh.read()
        for line in source.splitlines():
            if 'open(' in line and '"w"' in line:
                assert 'newline="\\n"' in line, (module.__file__, line)
