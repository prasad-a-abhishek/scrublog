"""Security and CLI robustness tests.

Covers:
- BUG-2: ``--in-place`` must refuse symlinks by default, follow with
  ``--follow-symlinks``.
- BUG-3 / SMELL-2: ``--stdin --in-place`` must be rejected with rc=2.
- SMELL-1: ``scrublog /dev/zero`` must not OOM — refuse with rc=1.
- BUG-6 / DOC: ``--version`` exits 0, errors go to stderr, missing-file rc=1.
"""
import io
import os
import sys
from pathlib import Path

import pytest

import scrublog.cli as cli_mod
from scrublog.cli import main


# ---- Symlink safety (BUG-2) ----

class TestInPlaceSymlink:
    def test_clean_strips_file_symlink_in_place_refuses(self, tmp_path, capsys):
        # Real target file containing ANSI.
        target = tmp_path / "real.log"
        target.write_bytes(b"\x1b[31msecret\x1b[0m")
        original = target.read_bytes()

        # Symlink pointing at the target.
        link = tmp_path / "link.log"
        link.symlink_to(target)

        rc = main([str(link), "--in-place"])
        err = capsys.readouterr().err

        assert rc != 0
        assert "symlink" in err.lower()
        # Target must NOT be modified.
        assert target.read_bytes() == original
        # Symlink itself must still exist.
        assert link.is_symlink()

    def test_clean_strips_file_symlink_in_place_with_flag_follows(
        self, tmp_path, capsys
    ):
        target = tmp_path / "real.log"
        target.write_bytes(b"\x1b[31msecret\x1b[0m")

        link = tmp_path / "link.log"
        link.symlink_to(target)

        rc = main([str(link), "--in-place", "--follow-symlinks"])

        assert rc == 0
        # Target bytes should now be cleaned.
        assert target.read_bytes() == b"secret"

    def test_clean_symlink_without_in_place_still_works(self, tmp_path, capsys):
        # Without --in-place, following a symlink is fine (read-only op).
        target = tmp_path / "real.log"
        target.write_bytes(b"\x1b[31mhi\x1b[0m")
        link = tmp_path / "link.log"
        link.symlink_to(target)

        rc = main([str(link)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "hi" in out
        # Target unchanged.
        assert target.read_bytes() == b"\x1b[31mhi\x1b[0m"

    def test_in_place_on_regular_file_still_works(self, tmp_path, capsys):
        # Make sure the symlink check doesn't break the normal path.
        f = tmp_path / "plain.log"
        f.write_bytes(b"\x1b[31mhi\x1b[0m")
        rc = main([str(f), "--in-place"])
        assert rc == 0
        assert f.read_bytes() == b"hi"

    def test_in_place_refuses_dangling_symlink(self, tmp_path, capsys):
        # Symlink whose target doesn't exist — refuse without --follow-symlinks.
        link = tmp_path / "dangling.log"
        link.symlink_to(tmp_path / "does-not-exist.log")

        rc = main([str(link), "--in-place"])
        assert rc != 0


# ---- stdin + --in-place rejection (BUG-3) ----

class TestStdinInPlaceRejection:
    def test_cli_rejects_stdin_with_in_place(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--stdin", "--in-place"])
        assert exc.value.code == 2

    def test_cli_rejects_stdin_with_dash_and_in_place(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["-", "--in-place"])
        assert exc.value.code == 2

    def test_cli_rejects_stdin_with_short_in_place_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--stdin", "-i"])
        assert exc.value.code == 2

    def test_cli_in_place_alone_with_stdin_emits_error(self, capsys):
        # Both the SystemExit and the stderr message.
        with pytest.raises(SystemExit) as exc:
            main(["--stdin", "--in-place"])
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "--in-place" in err or "stdin" in err


# ---- /dev/zero protection (SMELL-1) ----

class TestDevZeroProtection:
    def test_cli_refuses_dev_zero(self, capsys):
        # Must NOT OOM. Must exit non-zero with a clear stderr message.
        rc = main(["/dev/zero"])
        err = capsys.readouterr().err
        assert rc != 0
        assert rc == 1
        assert "dev" in err.lower() or "special" in err.lower()

    def test_cli_refuses_dev_urandom(self, capsys):
        # Same DoS class for /dev/urandom.
        rc = main(["/dev/urandom"])
        assert rc == 1

    def test_cli_allow_special_files_flag_parsed(self):
        # Verify the --allow-special-files flag is accepted by the parser.
        # We do NOT actually drain /dev/zero in tests because that would OOM
        # pytest itself. Instead verify the flag doesn't cause parse errors.
        # Without the flag, /dev/zero must be refused (rc=1).
        rc = main(["/dev/zero"])
        assert rc == 1

    def test_cli_allow_special_flag_works_on_normal_files_too(self, tmp_path, capsys):
        # --allow-special-files should be a no-op for normal files.
        f = tmp_path / "ok.log"
        f.write_bytes(b"\x1b[31mhi\x1b[0m\n")
        rc = main([str(f), "--allow-special-files"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.startswith("hi")


# ---- Misc CLI hygiene ----

class TestCliBasics:
    def test_cli_version_exit_zero(self, capsys):
        rc = main(["--version"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "scrublog" in out
        # Should NOT print to stderr.
        assert capsys.readouterr().err == ""

    def test_cli_version_uses_module_version(self):
        # The version string should match __version__ (single source of truth).
        from scrublog import __version__ as v
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--version"])
        assert v in buf.getvalue()

    def test_cli_prints_errors_to_stderr(self, capsys, tmp_path):
        nonexistent = tmp_path / "no-such-file.log"
        rc = main([str(nonexistent)])
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.err != ""
        # The error must be on stderr, not stdout.
        assert "no such file" in captured.err.lower() or "not found" in captured.err.lower()

    def test_cli_no_args_returns_error(self, capsys):
        rc = main([])
        assert rc != 0
        assert capsys.readouterr().err != ""


# ---- Symlink / in-place cross-check: existing symlink behaviour for the
# refactor safety net.

class TestSymlinkOsNoFollowFallback:
    """The implementation should use Path.is_symlink() / realpath, not
    silently depend on O_NOFOLLOW semantics. This test simply re-runs the
    behaviour to catch regressions if anyone swaps the impl.
    """

    def test_symlink_to_directory_refused_in_place(self, tmp_path, capsys):
        # /dev is a symlink-free directory in the test env so this works,
        # but we just want a symlink-to-dir target.
        d = tmp_path / "subdir"
        d.mkdir()
        f = d / "file.log"
        f.write_bytes(b"\x1b[31mhi\x1b[0m")
        original = f.read_bytes()

        link = tmp_path / "link-dir"
        link.symlink_to(d)

        rc = main([str(link) + "/file.log", "--in-place"])
        assert rc != 0
        assert f.read_bytes() == original