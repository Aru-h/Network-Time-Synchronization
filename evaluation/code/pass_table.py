#!/usr/bin/env python3
"""
Print the PASS / FAIL / SKIP table for run_d2.sh and exit non-zero if anything failed.

    pass_table.py STEPS.tsv [SUMMARY.txt]

STEPS.tsv: one `name<TAB>PASS|FAIL<TAB>detail` per wrapper step.
SUMMARY.txt: the runner's summary; each test line is `name  status ...` (indented
lines and `key=value` environment lines are ignored).
"""
import re
import sys

PASS = re.compile(r"(PASS|DELAY ACHIEVED|CONGESTION ACHIEVED|CONTROL OK|MEASURED|QOS EFFECTIVE|QOS PARTIAL)")
SKIP = re.compile(r"SKIPPED")


def classify(status):
    if SKIP.match(status):
        return "SKIP"
    return "PASS" if PASS.match(status) else "FAIL"


def read_steps(path):
    rows = []
    for line in open(path):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2:
            rows.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return rows


def read_summary(path):
    """Test lines only: they end at the first blank line (the environment block follows it)."""
    rows = []
    for line in open(path):
        if not line.strip():
            break
        if line[0].isspace():
            continue
        m = re.match(r"(\S+)\s+(.*)$", line.rstrip())
        if not m:
            continue
        status = m.group(2)
        result = classify(status)
        detail = re.sub(r"^(PASS|FAIL)\s*-?\s*", "", status)
        rows.append((m.group(1), result, detail))
    return rows


def main():
    rows = read_steps(sys.argv[1])
    if len(sys.argv) > 2:
        try:
            rows += read_summary(sys.argv[2])
        except FileNotFoundError:
            rows.append(("runner summary", "FAIL", f"{sys.argv[2]} not found"))
    w = max(len(r[0]) for r in rows) if rows else 10
    print("\n" + "=" * 100)
    print(f"{'CHECK':<{w}}  RESULT  DETAIL")
    print("-" * 100)
    for name, res, detail in rows:
        print(f"{name:<{w}}  {res:<6}  {detail[:100 - w - 10]}")
    n = {k: sum(1 for r in rows if r[1] == k) for k in ("PASS", "FAIL", "SKIP")}
    print("-" * 100)
    print(f"PASS {n['PASS']}   FAIL {n['FAIL']}   SKIP {n['SKIP']}")
    print("OVERALL:", "FAIL" if n["FAIL"] else "PASS")
    print("=" * 100)
    sys.exit(1 if n["FAIL"] else 0)


if __name__ == "__main__":
    main()
