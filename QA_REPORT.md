# scrublog — Quality Analyst Report

## Verdict: **FIX**

The library has a clean, well-tested core for common cases (all 25 tests pass in
0.01s). But there are **at least 5 real bugs**, **1 minor security smell** (symlink
following), **2 CLI robustness gaps** (OOM on `/dev/zero`, malformed arg combo
silently passes), and **several documentation inaccuracies**. None of the bugs cause
data loss in normal use, but the README claims (streaming, end-of-input handling,
ANSI detection) are contradicted by the actual behavior. Ship only after the listed
required fixes land.

---

## Test suite

- **Total tests:** 25
- **Passing:** 25
- **Failing:** 0

```
============================== 25 passed in 0.01s ==============================
```

Tests are shallow coverage: no adversarial inputs, no perf tests, no CLI in-place
on symlinks, no CLI behavior on nonexistent files, no `count_ansi` / `has_ansi`
consistency checks, no OSC/DCS split-stream tests. The 25 tests give false comfort.

---

## Break attempts

Library-API adversarial inputs (run against installed `scrublog` module):

| # | Attempt | Result | Observed |
|---|---------|--------|----------|
| a | 50 MB random ANSI input | **PASS** | 2.29s, ~16.7M chars out |
| b | CSI bomb `\x1b[` + `;`*10000 + `m` | **PASS** | 0.00s — no backtrack |
| c | OSC bomb `\x1b]` + `a`*100000 + `\x1b\\` | **PASS** | 0.00s |
| d | Nested-looking OSC `\x1b]0;\x1b]8;;url\x1b\\\x07` | **WRONG** | Output `'0;'` — first OSC consumed up to `\x1b\\`, leaves `0;` as garbage |
| e | OSC inside CSI `\x1b[\x1b]0;title\x07m` | **PASS** | Output `''` (consumed as CSI then OSC) |
| f | Incomplete CSI at end (`\x1b[3`, `\x1b[`, `\x1b`) | **PASS** | All return `''` |
| g | CSI with 1000 params `1;` * 1000 | **PASS** | 0.00s |
| h | Null bytes `\x1b[31mhello\x00world\x1b[0m` | **PASS** | Null preserved: `'hello\x00world'` |
| i | Invalid UTF-8 `\xff\xfe\xfd` and `\x1b[31m\xff\x1b[0m` | **PASS** | latin-1 fallback works, returns `'ÿþý'` and `'ÿ'` |
| j | Surrogates `\ud83d\ude00`, lone `\ud83d` | **PASS** | Returned unchanged (no crash) |
| k | 1M `\x1b` chars | **PASS** | 0.05s — `_TRAILING_ESC_RE` catches all of them (only because they're at end of input) |
| l | 10 MB plain text | **WRONG (low)** | `clean(s) is s` — returns the *same* object (relying on `re.sub` no-op behavior; safe because str is immutable, but a surprise) |
| m | `clean(lambda x: x)` | **PASS** | Raises `ScrubError: expected str or bytes, got function` |
| n | `clean(None)` | **PASS** | Raises `ScrubError` |
| o | `clean(42)` | **PASS** | Raises `ScrubError` |
| p | `clean(object())` | **PASS** | Raises `ScrubError` |
| q | `clean(x for x in "abc")` | **PASS** | Raises `ScrubError` |
| r | `stream(b"\x1b[31m\x00\x1b[0m")` | **PASS** | `['\x00']` |
| s | `stream("", "", "")` | **PASS** | `[]` |
| t | `stream("\x1b")` alone | **PASS** | `['']` (caught by `_TRAILING_ESC_RE`) |
| u | Nested-looking seq in single string | **PASS** | Output `'inner'` |
| v | `clean(open("/bin/ls","rb").read())` | **PASS** | 199 420 chars out |
| w | 200 MB of `\x1b[31m\x1b[0m` repeated | **PASS (slow)** | 6.33s for 200 MB (≈ 32 MB/s) — no OOM but slow for an ANSI-strip job |
| x  | `scrublog /dev/zero` | **CRITICAL** | Process killed with SIGKILL (`rc=-9`) — reads infinite zeros, will OOM a real user's machine or DoS a server |
| y  | `scrublog /dev/urandom` | **CRITICAL** | Hung indefinitely (timed out at 10s) — same OOM class |
| z  | `scrublog -i symlink-to-writable-file` | **SECURITY** | Silently follows the symlink and **overwrites the target through it** — `path.write_bytes()` in cli.py is symlink-blind |
| aa | 10 positional args | **PASS** | argparse rejects with rc=2 and clear usage |
| bb | `--stdin --in-place` | **WRONG** | rc=0, but `--in-place` is **silently ignored** — should be rejected |
| cc | Nonexistent path | **PASS** | rc=1 with clear `[Errno 2] No such file or directory` |
| dd | `--version` | **PASS** | Works fine |
| ee | 4096-char filename | **PASS** | OSError caught and printed |
| ff | Filename with spaces | **PASS** | OSError "No such file" |

Extra library-API findings (not in the task list but uncovered while testing):

| Finding | Severity |
|---------|----------|
| `stream("\x1b]0;title", "\x07world")` yields `['hello0;title', '\x07world']` — the OSC and the BEL **leak through** the streaming interface | **HIGH** |
| `stream("text\x1b", "more")` yields `['text', '\x1bmore']` — the `\x1b` between chunks **leaks** into output | **HIGH** |
| `has_ansi("hello\x1b") == False` but `clean("hello\x1b") == "hello"` (strips ESC) — **inconsistent** | MEDIUM |
| `count_ansi("hello\x1b") == 0` but clean strips it — same inconsistency | MEDIUM |
| `count_ansi("\x1b]0;title\x1b") == 1` — incomplete OSC counted as one ANSI sequence (false positive; matches via `\x1b[@-Z\\-_]` because `]` is 0x5D, in `\-_` range) | MEDIUM |
| `\x1b@` and `\x1b[` are stripped even when not at end of input — `_SINGLE_RE` matches `\x1b@` correctly, but `\x1b[` only because `[` is followed by a final byte that triggers CSI; **lone `\x1b[text` in middle of string** is handled as CSI and strips `\x1b[text` partially — ambiguous behavior | LOW |
| `\x1b5`, `\x1ba` (lowercase, digits after ESC) **leak through** as `\x1b5`, `\x1ba` — single-char regex `[@-Z\\-_]` only covers uppercase + `\` `]` `^` `_` | LOW |
| Lone `\x1b` in middle of `clean("hello\x1b world")` is **kept** as `'hello\x1b world'` | LOW |
| DCS terminated by BEL (non-standard but seen in some terminals) is **not stripped** — only ST terminator accepted | LOW |
| C1 8-bit control codes (e.g. `\x9b` as CSI) are **not stripped** — README says "all ANSI escape classes" | LOW |

---

## Code review findings

### BUG-1 — `stream()` does not actually buffer partial OSC/DCS sequences (HIGH)

`src/scrublog/__init__.py` line 39 defines `_TRAILING_ESC_RE = re.compile(r"\x1b(?:\[.*)?$")`. This regex only matches when the buffer ends with `\x1b` (optionally followed by `\[...` to end of string). For an in-progress OSC like `"\x1b]0;title"` or DCS `"\x1bP1;2;3abc"`, the buffer ends in a normal character, so the match fails, the *entire buffer* goes through `_FULL_PATTERN.sub`, and the OSC/DCS (which require a terminator) **passes through unchanged**. Then BEL/ST in the next chunk also leaks.

Reproduction:
```python
list(stream("\x1b]0;title", "\x07body"))  # → ['0;title', '\x07body']
list(stream("\x1bP1;2;3", "abc\x1b\\end"))  # → ['1;2;3', 'abcend']
list(stream("text\x1b", "more"))            # → ['text', '\x1bmore']
```

This is a direct contradiction of the README's headline feature: *"Safely handles incomplete / split escape sequences at end of input and across stream chunks."*

### BUG-2 — Symlink following in `--in-place` (MEDIUM, security)

`src/scrublog/cli.py` line 68 calls `p.write_bytes(...)` after `p = Path(args.path)` and `raw = p.read_bytes()`. `Path.write_bytes` calls `os.open` with default flags (no `O_NOFOLLOW`). On Unix, if the path is a symlink, both reads and writes **follow the symlink**. A user invoking `sudo scrublog -i log.txt` where `log.txt` is an attacker-controlled symlink will silently overwrite whatever target it points to (e.g. `/etc/passwd`, `/root/.ssh/authorized_keys`). Confirmed empirically: created symlink → tmp file → ran `scrublog -i symlink` → tmp file was overwritten with the cleaned version, symlink itself preserved.

Recommended fix: refuse to follow symlinks unless the user passes an explicit `--follow-symlinks` (or use `os.path.realpath` to detect and refuse). At minimum, document this clearly.

### BUG-3 — `--stdin --in-place` silently accepted (MEDIUM, UX/correctness)

`src/scrublog/cli.py` line 44 only rejects the combination `args.stdin and args.path not in (None, "")`. So `scrublog --stdin --in-place` (no path) goes through cleanly, rc=0, but `--in-place` is silently ignored because the stdin branch never honors it. The user almost certainly meant something impossible; the right behavior is to refuse the combo.

### BUG-4 — `has_ansi` / `count_ansi` disagree with `clean()` (MEDIUM)

`_DETECT_PATTERN` is built from CSI / OSC / DCS / SINGLE only — it does NOT include `_TRAILING_ESC_RE`. So:

| Input | `has_ansi` | `count_ansi` | `clean` |
|-------|------------|--------------|---------|
| `"hello\x1b"` | False | 0 | `"hello"` |
| `"hello\x1b["` | False | 0 | `"hello"` |
| `"hello\x1b world"` | False | 0 | `"hello\x1b world"` (no change!) |

A user calling `if has_ansi(line): line = clean(line)` will leave a `\x1b` in their output for an incomplete trailing ESC — exactly the case the README claims to handle.

Recommended fix: include `_TRAILING_ESC_RE` (or a dedicated partial-CSI/OSC/DCS detector) in `_DETECT_PATTERN`.

### BUG-5 — `count_ansi` false positive on lone OSC introducer (MEDIUM)

`has_ansi("\x1b]0;title\x1b")` returns `True`, `count_ansi` returns `1`. But this is an *incomplete* OSC (no terminator) — there's no actual escape sequence here. The match comes from `_SINGLE_RE = \x1b[@-Z\\-_]`, and `]` (0x5D) is in the `\-_` (0x5C–0x5F) range, so the lone `\x1b]` is counted as a "single-char escape". This is wrong per ECMA-48: `ESC ]` is reserved as the OSC introducer and should never appear as a complete sequence.

This also causes `count_ansi("\x1b]")` to return 1 even though it's just an orphan.

### BUG-6 — `clean()` returns the *same* str object when input has no escapes (LOW)

`clean("hello") is "hello"` evaluates to `True` (verified empirically). This is `re.sub`'s documented no-op behavior. It is safe in practice (str is immutable in CPython), but a user mutating the result via `io.StringIO` or similar would not notice the aliasing. README should mention this or the implementation should always return a new str.

### SMELL-1 — `scrublog /dev/zero` and `/dev/urandom` will OOM (HIGH, CLI)

`src/scrublog/cli.py` line 61 does `raw = p.read_bytes()`. On a regular file this is fine, but on `/dev/zero` it's an infinite stream of NUL bytes — the process keeps allocating until OOM-killer strikes (verified: ran in subprocess, got rc=-9 SIGKILL within ~3s on this machine). Same for `/dev/urandom`.

Fix: stat the file first, refuse anything in `/dev/` without an explicit `--allow-special-files`, or stream the read in chunks.

### SMELL-2 — CLI docstring says exit code 1 for usage errors (LOW)

`cli.py` line 11: `1  usage / I/O error`. argparse uses rc=2 for usage errors. Confirmed: `scrublog --bogus-flag` returns rc=2.

### DEAD-1 — `--version` doesn't honor `argv=None` consistently (LOW)

`main(argv=None)` is fine, but the version string is hardcoded (`print("scrublog 0.1.0")`) and does not use `__version__`. Two sources of truth.

### DEAD-2 — Import of `count_ansi` from docstring example is unreachable (cosmetic)

`__init__.py` docstring lists `stream(*chunks) -> iter` but `stream` is a generator (returns `Iterator[str]`, not `iter`). Minor.

### DEAD-3 — `re.compile` patterns are defined but `_FULL_PATTERN` is the only one used as sub target; `_DETECT_PATTERN` is used only for `search` and `finditer`. Fine, but worth knowing.

### DEAD-4 — `_TRAILING_ESC_RE` regex `\x1b(?:\[.*)?$` uses `.` greedy, which could in theory be slow on extreme inputs, but `.` is anchored to `$` and is followed by an end-of-string assertion. Safe in practice.

### CODE-1 — `_as_text` accepts `bytes` and `bytearray` but no other buffer protocol (LOW)

`memoryview(b"...")` raises `ScrubError`. Fine, just an edge case.

### CODE-2 — `stream()` calls `_FULL_PATTERN.sub` per chunk; for large buffers this re-scans the same text multiple times if `count_ansi` is also called. Not a real issue for current use.

---

## README review findings

### DOC-1 — Streaming claim is contradicted by the code (HIGH)

> "Safely handles **incomplete / split escape sequences** at end of input and across stream chunks"

`stream("\x1b]0;title", "\x07world")` leaks the OSC and BEL through. The CLI file mode works (because the whole file is in one buffer), but `stream()` does not honor this promise for OSC/DCS splits.

### DOC-2 — "Incomplete / trailing" row in supported-escapes table is inaccurate (MEDIUM)

> Incomplete / trailing | `text\x1b` or `text\x1b[31` | ✅ dropped cleanly |

`text\x1b[31` IS dropped (because `_TRAILING_ESC_RE` matches at end), but:
- A **partial CSI like `text\x1b[31m foo`** is *not* treated as trailing; if it doesn't fit the final-byte pattern, behavior depends on what follows.
- A **partial OSC/DCS like `text\x1b]0;title` in the middle of a stream** is **not** dropped (BUG-1).

### DOC-3 — `pip install scrublog` requires the package be published to PyPI (LOW)

The repo is on GitHub but PyPI status unknown. New users running the install command will hit "no such package" if it's not on PyPI. README should either link to PyPI or remove the line.

### DOC-4 — README example output `clean("\x1b[31mhello\x1b[0m") # => "hello"` (LOW)

Verified correct.

### DOC-5 — README says `scrublog 0.1.0` prints version but docstring of `main()` doesn't make this obvious (LOW)

### DOC-6 — "Tested on Python 3.8 – 3.12" — no CI config present in repo (LOW)

There's no `.github/workflows/` or other CI config. The claim is unverified.

### DOC-7 — Example in README uses `count_ansi(line_with_many_codes)` without a sample input/output (cosmetic)

### DOC-8 — pyproject.toml `Development Status :: 4 - Beta` — README describes it as production-ready ("does it right, does it small"). Minor mismatch in tone vs reality given the bugs.

### DOC-9 — README doesn't mention `ScrubError` is a `ValueError` subclass (LOW)

Users catching `ValueError` will also catch `ScrubError`. Worth documenting so users know they can do either.

### DOC-10 — README doesn't warn that `--in-place` follows symlinks (MEDIUM, security)

`$ scrublog -i server.log` example doesn't mention this footgun. See BUG-2.

### DOC-11 — README doesn't warn that `scrublog /dev/zero` is dangerous (MEDIUM)

See SMELL-1.

---

## Test coverage gaps

| Gap | Suggested test |
|-----|----------------|
| **GAP-1 (HIGH)**: No streaming tests for OSC split across chunks. | `assert "".join(stream("\x1b]0;title", "\x07body")) == "body"` |
| **GAP-2 (HIGH)**: No test for `\x1b` between stream chunks. | `assert "".join(stream("text\x1b", "more")) == "textmore"` |
| **GAP-3 (MEDIUM)**: No test for `has_ansi` / `count_ansi` consistency with `clean` on trailing/incomplete sequences. | `assert has_ansi("hello\x1b") is True; assert count_ansi("hello\x1b") == 1` |
| **GAP-4 (MEDIUM)**: No symlink-safety test for CLI `--in-place`. | `tmp_path/symlink_to_etc_passwd → assert rc != 0 or /etc/passwd unchanged` |
| **GAP-5 (MEDIUM)**: No CLI test for `--stdin --in-place`. | `with pytest.raises(SystemExit): main(["--stdin", "--in-place"])` |
| **GAP-6 (MEDIUM)**: No CLI test for `/dev/zero` or other special files. | `assert main(["/dev/zero"]) != 0` (or stdout is bounded) |
| **GAP-7 (MEDIUM)**: No test for lone `\x1b]` (false positive in `count_ansi`). | `assert count_ansi("\x1b]") == 0` |
| **GAP-8 (LOW)**: No test for `\x1b5` / `\x1ba` — should they leak? Decide and test. | Spec-dependent |
| **GAP-9 (LOW)**: No test for C1 8-bit control codes (`\x9b`). | Spec-dependent |
| **GAP-10 (LOW)**: No test for `\x1b[?25h` (CSI with private mode marker). | `assert clean("\x1b[?25l\x1b[?25h") == ""` |
| **GAP-11 (LOW)**: No test for DCS with BEL terminator (non-standard but seen). | Spec-dependent |
| **GAP-12 (LOW)**: No test that `clean(s) is not s` for any input (or document the aliasing). | `assert clean("\x1b[31mhi\x1b[0m") is not s` |
| **GAP-13 (LOW)**: No test for `count_ansi` returning int (not bool etc.) for various inputs. | `isinstance(count_ansi("a\x1b[31mb"), int)` |
| **GAP-14 (LOW)**: No test for `has_ansi` returning exactly `bool`. | `isinstance(has_ansi("a\x1b[31mb"), bool)` |
| **GAP-15 (LOW)**: No test that the CLI prints to stderr (not stdout) on errors. | Capture stderr, check non-empty on nonexistent path |
| **GAP-16 (LOW)**: No perf test (claim of "fast" in README). | `time_budget = 5s; clean(50MB of random ANSI)` |
| **GAP-17 (LOW)**: No test for `ScrubError` being a `ValueError`. | `assert issubclass(ScrubError, ValueError)` |
| **GAP-18 (LOW)**: No test for `stream()` yielding `str` (not `bytes`). | `isinstance(next(stream("x")), str)` |
| **GAP-19 (LOW)**: No test for `--version` exit code. | `assert main(["--version"]) == 0` |
| **GAP-20 (LOW)**: No test for `stream()` with no args. | `list(stream()) == []` |

---

## Required fixes (must land before SHIP)

1. **Fix `stream()` to actually buffer partial OSC/DCS sequences.** The
   `_TRAILING_ESC_RE` approach is insufficient. Either widen the trailing
   pattern to also catch `\x1b` followed by `]`, `P`, `X`, `^`, `_` without
   terminator, or do explicit per-class partial matching. Also extend the
   pattern to match a trailing `\x1b` (not just `\x1b[`…) so a `\x1b` alone
   in the middle of a multi-chunk buffer is stripped.

2. **Fix `--in-place` to refuse symlinks by default** (or follow with
   `--follow-symlinks`). Document the chosen behavior. Use `os.O_NOFOLLOW`
   when opening for write, or check `p.is_symlink()` and abort.

3. **Reject `--stdin --in-place` in `main()`** — both because the combo is
   nonsensical and because the current code silently ignores `--in-place`,
   which violates least-surprise.

4. **Make `has_ansi` / `count_ansi` consistent with `clean`**. Either include
   `_TRAILING_ESC_RE` in `_DETECT_PATTERN`, or remove trailing-ESC handling
   from `clean`. Pick one and apply everywhere.

5. **Fix `/dev/zero` / `/dev/urandom` DoS**. Refuse regular files in `/dev/`,
   or stat the file size and refuse anything bigger than a threshold, or
   stream the read in chunks with an explicit max-bytes limit.

6. **Update README** to accurately describe what works:
   - Streaming of OSC/DCS splits is currently broken; either fix it or remove
     the claim.
   - Document that `--in-place` follows symlinks (until fixed).
   - Document that `\x1b` followed by lowercase or digits is left in place
     (or fix it).

7. **Add the missing tests** for the above behaviors (see GAP-1, GAP-2,
   GAP-3, GAP-4, GAP-5, GAP-6, GAP-7 at minimum).

## Optional improvements (nice to have)

- `clean()` could always return a new str for consistency. The current "return
  same object on no-op" behavior is documented for `re.sub` but not for scrublog.
- Use `__version__` instead of hardcoded "0.1.0" in `cli.py`.
- Document `ScrubError`'s `ValueError` parent class.
- Consider handling C1 control codes (`\x9b`, `\x9d`, `\x90`-`\x97`, `\x9c`)
  for completeness — many 8-bit terminals send them.
- The OSC regex `[^\x07\x1b]|\x1b\\` could be tightened to specifically
  allow ST (`\x1b\\`) but reject other `\x1b` (which it does), but also
  consider accepting BEL in DCS/SOS/PM/APC for compatibility.
- The single-char escape regex `[@-Z\\-_]` strips `\x1b@`, which is not
  actually a defined escape. Tighten to `[A-Z\\]^_` to match ECMA-48.
- Add a CI workflow (GitHub Actions) running pytest on Python 3.8-3.12.
- Add a property-based test (hypothesis) for the cleaner to find counterexamples
  automatically.
- The 200 MB perf test (~32 MB/s) suggests room for optimization — but this
  is a "nice to have" not a correctness bug.

---

## Ship or no-ship?

**Do not ship yet.** The streaming API is the headline feature advertised in
the README, but its primary use case (cleaning subprocess output streamed in
chunks) is broken: any OSC or DCS sequence that arrives split across two
`stream()` chunks will leak the leading bytes and the BEL/ST terminator into
the user's output, which is exactly the kind of garbage the user was trying to
remove. The CLI has a real symlink-traversal footgun in `--in-place` that a
non-careful user (or any `sudo` invocation in a multi-tenant env) will trip,
and `scrublog /dev/zero` will reliably OOM a user's machine. The
`has_ansi`/`count_ansi`/`clean` inconsistency means anyone using the documented
"`if has_ansi(line): line = clean(line)`" idiom will produce broken output
when given a trailing partial escape. None of these are catastrophic on
their own — no RCE, no auth bypass, no data loss in single-call usage — but
they combine into a library that doesn't actually do what its README says,
which is the kind of thing that gets a project reputation-killed the first
time a real user hits one. Fix the six required items, add the gap tests,
update the README to match reality, and this becomes shippable.
