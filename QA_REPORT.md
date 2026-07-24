---
tests_run: 134
tests_passed: 134
tests_passing: true
commit_sha_verified: 5db55ed0d1b6c6a9d335797fbc56562b9224b5d6
fuzz_inputs_tried:
  - random_bytes_4096
  - unicode_emoji_combining_rtl_and_ansi
  - empty_input
  - binary_garbage_all_byte_values
  - stdin_10MiB
boundaries_tried:
  - empty_stdin
  - single_newline
  - stdin_100MiB
limitations_section_present: true
shippable: true
---

# scrublog QA Report — cycle 01, QA #3

## Verdict summary

All three release pillars hold. The implementation remains within the completion-only scope in `spec.md`: a zero-runtime-dependency Python library and CLI that strips the documented 7-bit ECMA-48/xterm sequence classes, supports chunk-safe bounded streaming, and applies the required CLI safety behavior. I found no unrelated feature expansion or scope creep.

## Useful

I re-read `/root/.hermes/repo_factory/cycles/cycle_01/spec.md` and compared its scope and acceptance requirements with the repository. The project remains a stripper rather than a terminal emulator, adds no new runtime dependency, and does not introduce any out-of-scope redaction, terminal rendering, HTML conversion, plugin, or PyPI-release work. Source totals 607 lines across the package (603 substantive lines excluding the four-line `__main__.py`); this exceeds the spec's preferred, non-mandatory 500-LOC compactness target but is not scope creep and was not introduced by commit `5db55ed`, which is README-only.

## Proven

- Fresh full-suite run: `pytest --tb=short -q` collected 134 tests and passed 134/134 in 0.33 seconds.
- Fresh isolated install: created `/tmp/scrub-fresh-qa3`, installed editable from `/root/projects/scrublog`, and successfully ran `scrublog --help`.
- Fresh installed CLI smoke: piped SGR-colored `ERROR` through `scrublog -`; exit 0, output `ERROR`, no ANSI bytes.
- Fresh installed library smoke: imported `scrublog` and cleaned an SGR-wrapped byte string to `OK`.
- Adversarial CLI subprocess cases all exited 0 with no stderr or retained tested SGR sequences:
  1. 4,096 random bytes.
  2. Unicode containing emoji, ZWJ, combining text, RTL text, and SGR.
  3. Empty input.
  4. Binary garbage containing all byte values, repeated to 4,096 bytes.
  5. 10 MiB stdin with SGR near EOF; completed in 0.453 seconds.
- Boundary cases:
  1. Empty stdin: zero-byte output, exit 0.
  2. Single newline: one-byte output, exit 0.
  3. 100 MiB stdin: completed in 4.407 seconds, exit 0; output was 100 MiB plus the documented stdout final newline.

## Honest

- `git show 5db55ed --stat` resolves to full commit `5db55ed0d1b6c6a9d335797fbc56562b9224b5d6`; it changes only README.md (18 lines: 14 additions, 4 deletions).
- README lines 114, 119, 121, and 133 all use the explicit stdin marker `scrublog -`.
- A complete README scan found zero pipe examples containing bare `| scrublog` without `| scrublog -`.
- The Limitations section is present at README lines 214–222 and explicitly describes the residual TOCTOU window between the symlink-component check and open/rename.
- The limitation matches source behavior and comments: `src/scrublog/cli.py` performs a path-component `is_symlink()` walk in `_has_symlink_component` before opening the input and later performs `os.replace`; source does not claim descriptor-based `O_NOFOLLOW` race elimination. README's “one-shot lstat-style walk” is an accurate high-level description of that stat-style precheck.
- Working tree was clean before this QA report was regenerated.

I tried random bytes, Unicode/ZWJ/combining/RTL text, empty input, all-byte binary garbage, a 10 MiB stream, a single-newline boundary, a 100 MiB boundary, a fresh virtualenv install, the installed CLI, and the installed library API and found nothing broken.

VERDICT: SHIP
