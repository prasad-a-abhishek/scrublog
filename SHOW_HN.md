# Show HN Launch Package: scrublog

**Target Title:**
`Show HN: scrublog – Lossless ANSI escape & color stripper for terminal logs`

**Target URL:**
`https://github.com/prasad-a-abhishek/scrublog`

**Top Comment to Post Immediately After Submission:**

Hi HN! 👋

`scrublog` is a zero-dependency Python tool for stripping ANSI color codes, cursor escape sequences, and OSC hyperlinks from build logs, CI output, and terminal dumps.

Most developers use `re.sub()` for this, but naive regex patterns fail when escape sequences are split across chunk boundaries during streaming, or corrupt multi-byte ST/BEL terminators in hyperlinks.

### ⚡ Benchmark Results (10,000-Line Terminal Log)

| Workload Profile | `scrublog.clean()` | Standard Regex | Speed Advantage |
| :--- | :---: | :---: | :---: |
| **ANSI Log (10,000 lines)** | ⚡ **49.94 ms** | 126.90 ms | **2.5x Faster** |
| **Heavy ANSI Log (5,000 lines)** | ⚡ **50.07 ms** | 127.53 ms | **2.5x Faster** |
| **Stream Boundary Support** | 💡 **Native (`stream()`)** | 🛑 **Corrupts split bytes** | **Lossless** |

*Trade-off Note: For plain text without any ANSI codes, pre-compiled regex sub is faster (0.2ms vs 23ms). `scrublog` is designed for actual ANSI-decorated terminal streams.*

### Quick Start
pip install scrublog
cat build.log | scrublog > clean.log

Replicate locally: `python3 benchmarks/run_benchmark.py`
GitHub: https://github.com/prasad-a-abhishek/scrublog
PyPI: https://pypi.org/project/scrublog/
