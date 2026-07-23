# ANSI-in-logs audit: scrublog’s wedge

**Scope / date:** targeted review of common ANSI tooling and log workflows (2026-07-23). The practical pattern is not “render ANSI everywhere”: producers color terminal output, while collectors and machine-readable sinks usually want plain text. Teams either disable color at the source (`NO_COLOR`, tool-specific `--color=never`), strip at the shell/pipeline boundary, or configure a collector/parser. A terminal emulator is the wrong abstraction when the requirement is simply safe text.

## 1. Tool audit

- **strip-ansi (Node, `strip-ansi`)** is the familiar small filter: use `stripAnsi(string)`; it removes ANSI escape codes with the `ansi-regex` dependency. It is a good precedent for a narrowly scoped “clean this captured output” utility, but it is not a Python CLI/streaming bytes tool.
- **Colorama** is primarily a Windows terminal compatibility layer (`colorama.init()`, `just_fix_windows_console()`): it converts/strips ANSI while writing to a terminal, not a general log sanitization boundary. Pulling it into a log pipeline is extra behavior and dependency surface.
- **pyte** is a terminal emulator/parser. It interprets cursor movement, screen state, carriage returns, alternate screens, etc. That is appropriate for reconstructing terminal displays, but overkill when the desired result is the textual payload and can create surprising output for progress bars/overwrites.
- **ansi2html** intentionally preserves meaning by converting ANSI styling into HTML. That is useful for web reports, not JSON/Loki/Datadog fields, and introduces formatting/security considerations.
- **Datadog** and similar collectors generally solve this with source settings or processing pipelines: parse/transform at ingestion, then index/search normalized fields. ANSI is not a semantic log field; leaving it in damages search/display and JSON escaping. Loki/Promtail and CloudWatch users likewise commonly pipe/transform before shipping rather than emulate a terminal.
- **GitHub Actions** renders supported workflow commands and log annotations, and lets users view/search/download job logs. Downloaded/raw logs are a particularly concrete boundary: terminal styling is noise, while commands such as `::error` are protocol-like metadata and must not be confused with ANSI stripping. `scrublog` should remove ESC sequences without claiming to parse CI commands.

## 2. User complaints / real failure modes

Typical complaints are: grep/search misses `ERROR` because bytes surround it; JSON logs contain literal `\u001b[31m`; copied incidents contain unreadable `^[`/escape garbage; hyperlink OSC sequences leak URLs into records; and regexes fail when a subprocess read splits `ESC[` from `31m`. Progress bars and cursor controls can also leave misleading `\r`/screen-control artifacts if users expect a final rendered terminal state. A second operational concern is accidental whole-file memory loading for large/infinite inputs.

The common workaround is `tool --color=never`, `TERM=dumb`, `NO_COLOR=1`, or `... 2>&1 | sed/perl | tee`; these are fragile because every producer has different flags and some libraries emit color based on TTY detection. Collector-side stripping is safer when many producers are involved.

## 3. Tuesday workflows (five personas)

1. **Python test/CI engineer:** `pytest --color=yes | scrublog > test-output.txt`; uploads readable artifacts and greps failures. Failure: CI capture is non-TTY but a forced-color flag emits SGR; split reads expose partial sequences.
2. **Container operator:** `docker logs app 2>&1 | scrublog | gzip`; removes colors before shipping to CloudWatch/Loki. Failure: application logger was configured for a terminal, so every record has reset codes and OSC hyperlinks.
3. **SRE incident responder:** `kubectl logs pod | scrublog | grep -E 'ERROR|FATAL'`. Failure: raw output pasted into a ticket/search query contains escapes; cursor controls make output visually misleading.
4. **Build/release engineer:** `npm test -- --color=always | scrublog`; retains readable CI artifacts while preserving Unicode. Failure: tool-specific “disable color” switches differ or are ignored in wrappers.
5. **Library/platform engineer:** wraps `subprocess.Popen(..., stdout=PIPE)` and feeds chunks to `stream()`. Failure: decoding arbitrary bytes and escape boundaries; wants no heavyweight terminal emulator and bounded behavior.

## 4. Current scrublog coverage (README + `src/scrublog/`)

### SHIPPED

- Pure-stdlib library and CLI; `clean`, `has_ansi`, `count_ansi`, and `stream`.
- SGR, CSI cursor/clear, OSC (including BEL/ST hyperlinks), DCS/SOS/PM/APC, and single-character escapes.
- 16/256/truecolor sequences; `str`, `bytes`, UTF-8 with latin-1 fallback; Unicode preservation.
- Correct handling of split chunks and trailing bare ESC/partial CSI; stream buffering with a 1 MiB partial-tail cap.
- CLI stdin (`--stdin`/`-`), file-to-stdout, `-i/--in-place`, `--version`, explicit refusal of symlink paths for in-place writes, and refusal of `/dev/*` special files unless `--allow-special-files`.

### PARTIAL

- CLI stdin currently does `sys.stdin.buffer.read()` and file mode uses `Path.read_bytes()`: the public streaming API is robust, but the CLI is not bounded/streaming for large logs and is unsafe for “tail forever” workflows. This is the largest practical mismatch with the README’s “byte streams” positioning.
- It strips control sequences, but does not reconstruct terminal semantics: carriage-return progress bars, backspaces, and screen updates are not rendered into a final display. That is correct for a stripper, but should be explicit.
- Bytes decoding is per whole input/chunk with UTF-8 then latin-1 fallback; a UTF-8 code point split across chunks may decode as latin-1 in the affected chunk, producing mojibake. A true byte-stream decoder would buffer incomplete UTF-8 separately.
- No collector-native integration (Docker logging driver, Fluent Bit/Vector/Promtail/Datadog processor), no JSON-aware field traversal, and no automatic producer configuration.
- Not yet on PyPI (README says GitHub install), which is friction for a one-command operational utility.

### MISSING

- A documented `--follow`/incremental file mode, bounded memory CLI path, or explicit `--max-bytes`/backpressure story.
- Policy modes such as “strip ANSI only” versus “strip ANSI plus terminal controls”; no preserve/replace/report option for auditing removed sequences.
- Shell integrations and examples for major collectors, and benchmark/large-log guarantees.

## 5. One wedge

**Wedge: the dependency-free, streaming subprocess/log boundary for Python teams.** Do not compete with terminal emulators or HTML converters. Own the moment where a Python service captures colored CLI output and must safely hand it to a text/JSON/log sink: `stream()` handles escape sequences split across reads, while `clean()` handles bytes and hostile/truncated tails, with zero dependencies. The memorable promise is: **“Normalize arbitrary subprocess output before it enters your logs—without emulating a terminal.”**

The wedge is strongest if the CLI catches up with the API: bounded chunked stdin/file processing, then copy-paste recipes for `subprocess`, Docker, CI artifacts, and one collector. A generic regex comparison is less persuasive than a failure-mode test: OSC 8 hyperlink + truecolor + split `ESC[`/parameters + truncated final ESC, all removed without losing the message.

## 6. Recommendation

Keep the scope narrow and ship the operational path, in this order:

1. Make `scrublog --stdin` genuinely chunked (and add a documented `--follow` or clearly state EOF-only behavior); preserve output bytes/encoding policy as far as possible. Avoid whole-file reads.
2. Add an explicit “does not render terminal state” note and tests/examples for `\r` progress bars, backspace, and GitHub Actions command lines.
3. Publish to PyPI and provide tiny integrations: Python `Popen` loop using `stream()`, `docker logs ... | scrublog`, and a Vector/Fluent Bit/Promtail transform example. Include `--color=never`/`NO_COLOR` as preferred producer-side controls, with scrublog as the defense-in-depth boundary.
4. Add optional metrics/reporting only if it remains cheap (`count_ansi` already supports quality gates); do not turn the project into a parser, renderer, HTML converter, or redaction engine.

**Bottom line:** people mostly disable color when they can, but cannot reliably control every subprocess and wrapper. Existing Python choices either adapt terminal output (Colorama), emulate it (pyte), or transform presentation (ansi2html). `scrublog`’s credible wedge is the small, zero-dependency, ANSI-complete and chunk-boundary-safe Python boundary filter—provided its CLI becomes truly streaming and its packaging/integration story removes Tuesday friction.

## Sources read

1. https://github.com/chalk/strip-ansi — small Node strip-ANSI API and dependency model.
2. https://github.com/tartley/colorama — terminal compatibility/ANSI translation rather than log normalization.
3. https://github.com/selectel/pyte — terminal emulator/parser scope.
4. https://github.com/pycontribs/ansi2html — ANSI-to-HTML presentation alternative.
5. https://docs.datadoghq.com/logs/log_configuration/processors/ — ingestion-time log processing model.
6. https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/using-workflow-run-logs — searchable/downloadable workflow logs and CI boundary.

Additional relevant references: https://no-color.org/ (producer-side convention) and https://github.com/getsentry/sentry-cli/issues/ (representative ecosystem issue searches around colored captured output).
