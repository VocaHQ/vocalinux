"""Exercise local AUR gate orchestration without network access or Docker."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def gate_recipe() -> str:
    """Read the real shell recipe, rejecting prerequisites that use shared outputs."""
    match = re.search(
        r"^aur-gate:([^\n]*)\n((?:[ \t].*\n|\n)+)",
        (ROOT / "justfile").read_text(),
        re.MULTILINE,
    )
    assert match, "aur-gate recipe missing"
    assert not match[1].strip(), "aur-gate must not invoke a shared-output prerequisite"
    return textwrap.dedent(match[2])


def executable(path: Path, content: str) -> None:
    """Write a Python stand-in for an external command."""
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(content))
    path.chmod(0o755)


@pytest.mark.parametrize("failure", ["", "build", "arch"])
def test_local_gate_isolates_outputs_and_retains_failed_diagnostics(
    tmp_path: Path, failure: str
) -> None:
    """Use real output validation and source preparation, stubbing only tool work."""
    recipe = gate_recipe()
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    template = checkout / "packaging/aur/vocalinux"
    template.mkdir(parents=True)
    shutil.copy2(ROOT / "packaging/aur/vocalinux/PKGBUILD", template / "PKGBUILD")
    shutil.copy2(ROOT / "scripts/prepare_aur_source.py", scripts / "prepare_aur_source.py")

    # Keep the real cleanup policy: shared dist/ would reject these outputs.
    (scripts / "build_reproducible_wheel.py").write_text(textwrap.dedent(f"""\
            import argparse
            import importlib.util
            import io
            import json
            import os
            import sys
            import tarfile
            from pathlib import Path

            parser = argparse.ArgumentParser()
            parser.add_argument('--python', required=True)
            parser.add_argument('--output', type=Path, default=Path('dist'))
            parser.add_argument('--diagnostics', type=Path, default=Path('build/reproducible-wheel'))
            args = parser.parse_args()
            assert args.python == os.environ['PYTHON']
            with open(os.environ['AUR_GATE_TEST_LOG'], 'a') as log:
                log.write(json.dumps(['build', str(args.output), str(args.diagnostics)]) + '\\n')
            spec = importlib.util.spec_from_file_location(
                'wheel_gate', {str(ROOT / 'scripts/build_reproducible_wheel.py')!r}
            )
            gate = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gate)
            gate.prepare_outputs(args.output, args.diagnostics)
            (args.diagnostics / 'canonical.log').write_text('retained build diagnostics')
            if os.environ['AUR_GATE_TEST_FAILURE'] == 'build':
                sys.exit(31)
            args.output.mkdir(parents=True, exist_ok=True)
            with tarfile.open(args.output / 'vocalinux-0.18.4.tar.gz', 'w:gz') as archive:
                metadata = b'Name: vocalinux\\nVersion: 0.18.4\\n'
                member = tarfile.TarInfo('vocalinux-0.18.4/PKG-INFO')
                member.size = len(metadata)
                archive.addfile(member, io.BytesIO(metadata))
            (args.output / 'vocalinux-0.18.4-py3-none-any.whl').write_text('new wheel')
            """))

    # Existing packaging outputs, wheel diagnostics and dev tooling are not ours.
    protected = {}
    for name in (
        "dist/vocalinux-0.18.4-py3-none-any.whl",
        "dist/vocalinux-0.18.4.tar.gz",
        "dist/Vocalinux-0.18.4-x86_64.AppImage",
        "dist/vocalinux_0.18.4_amd64.deb",
        "dist/vocalinux-0.18.4.x86_64.rpm",
        "build/reproducible-wheel/canonical.log",
        ".venv/keep.txt",
    ):
        path = checkout / name
        path.parent.mkdir(parents=True, exist_ok=True)
        protected[path] = f"existing {name}".encode()
        path.write_bytes(protected[path])

    tools = tmp_path / "tools"
    tools.mkdir()
    interpreter = "#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n'
    executable(
        tools / "uv",
        f"""\
        import sys
        from pathlib import Path

        if sys.argv[1] == 'venv':
            target = Path(sys.argv[-1]) / 'bin/python'
            target.parent.mkdir(parents=True)
            target.write_text({interpreter!r})
            target.chmod(0o755)
        else:
            assert sys.argv[1:3] == ['pip', 'install']
            assert {{'--require-hashes', '--no-deps', '--only-binary=:all:'}} <= set(sys.argv)
            assert sys.argv[-1] == 'requirements/release-build.txt'
        """,
    )
    executable(
        tools / "docker",
        """\
        import json
        import os
        import sys
        from pathlib import Path

        source = next(arg.removesuffix(':/aur-source:ro') for arg in sys.argv
                      if arg.endswith(':/aur-source:ro'))
        assert (Path(source) / 'PKGBUILD').is_file()
        assert (Path(source) / 'vocalinux-0.18.4.tar.gz').is_file()
        assert 'AUR_SOURCE=/aur-source' in sys.argv
        with open(os.environ['AUR_GATE_TEST_LOG'], 'a') as log:
            log.write(json.dumps(['arch', source]) + '\\n')
        sys.exit(42 if os.environ['AUR_GATE_TEST_FAILURE'] == 'arch' else 0)
        """,
    )
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    log = tmp_path / "calls.jsonl"
    result = subprocess.run(
        ["bash", "-c", recipe],
        cwd=checkout,
        env={
            **os.environ,
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "PYTHON": sys.executable,
            "TMPDIR": str(temporary),
            "AUR_GATE_TEST_LOG": str(log),
            "AUR_GATE_TEST_FAILURE": failure,
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == {"": 0, "build": 31, "arch": 42}[failure], result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls[0][0] == "build"
    output, diagnostics = (Path(path) for path in calls[0][1:])
    work = output.parent
    assert work.parent == temporary
    assert diagnostics.parent == work and diagnostics != output
    if failure != "build":
        assert calls[1] == ["arch", str(work / "source")]
    if failure:
        assert str(work) in result.stderr
        assert (diagnostics / "canonical.log").read_text() == "retained build diagnostics"
    else:
        assert not work.exists()
    assert {path: path.read_bytes() for path in protected} == protected
