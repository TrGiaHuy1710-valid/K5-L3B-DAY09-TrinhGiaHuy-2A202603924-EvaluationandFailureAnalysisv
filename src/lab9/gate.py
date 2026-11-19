"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    manifest, base_manifest = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. Aggregate values must be real numbers: NaN/inf compare False against every floor.
    for k, v in (pr.get("metrics") or {}).items():
        if _not_finite(v):
            problems.append(f"metric {k} is {v} (NaN/inf compares False against any threshold)")

    # 2. A grader that crashed is not a pass.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s) in the PR run, "
                        f"first: {str(pr['evaluator_failures'][0])[:80]}")

    # 3. Row coverage: exactly items x seeds, no duplicates, same (item, seed) set as the baseline.
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    want_n = int(manifest.get("items") or 0) * len(manifest.get("seeds") or [])
    if len(rows) != want_n:
        problems.append(f"{len(rows)} rows, manifest promises {manifest.get('items')} items x "
                        f"{len(manifest.get('seeds') or [])} seeds = {want_n}")
    dupes = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dupes:
        problems.append(f"{len(dupes)} duplicated (item, seed) row(s), first {dupes[0]}")
    if sorted(manifest.get("seeds") or []) != sorted(base_manifest.get("seeds") or []):
        problems.append(f"seeds {manifest.get('seeds')} differ from the baseline's {base_manifest.get('seeds')}")
    if manifest.get("items") != base_manifest.get("items"):
        problems.append(f"manifest items {manifest.get('items')} != baseline {base_manifest.get('items')}")
    have, want = set(keys), {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if have != want:
        missing, extra = sorted(want - have, key=str), sorted(have - want, key=str)
        problems.append(f"(item, seed) set differs from the baseline: {len(missing)} missing"
                        f"{' e.g. ' + str(missing[0]) if missing else ''}, {len(extra)} extra"
                        f"{' e.g. ' + str(extra[0]) if extra else ''}")

    # 4. Every graded spec metric has a real verdict on every row: a None silently leaves the mean.
    graded = [m for m in spec.get("metrics") or [] if m["id"] in _graded_ids()]
    none_rows: dict[str, int] = {}
    for r in rows:
        for m in graded:
            v = r.get(m["id"])
            if v is None or _not_finite(v):
                none_rows[m["id"]] = none_rows.get(m["id"], 0) + 1
    problems += [f"{n} row(s) have no value for graded metric {mid}" for mid, n in none_rows.items()]

    # 5. Reported aggregates must follow from the rows (a hand-edited metric block).
    if rows and not none_rows:
        problems += _recompute_mismatch(pr, spec, graded)

    # 6. Slice tags per item must match the baseline's (moving an item out of a slice hides it).
    tags = lambda rs: {r.get("item_id"): sorted(r.get("slices") or []) for r in rs}
    pr_tags, base_tags = tags(rows), tags(base_rows)
    moved = sorted(i for i in pr_tags.keys() & base_tags.keys() if pr_tags[i] != base_tags[i])
    if moved:
        problems.append(f"slice tags changed vs baseline on {len(moved)} item(s), first {moved[0]}: "
                        f"{base_tags[moved[0]]} -> {pr_tags[moved[0]]}")

    # 7. Ratchet: on the same eval-set version thresholds may only get stricter.
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _not_finite(v) -> bool:
    return isinstance(v, float) and not math.isfinite(v)


def _graded_ids() -> set[str]:
    from lab9.graders import GRADERS   # local: keep `import lab9.gate` light for the CI tests
    return set(GRADERS)


def _recompute_mismatch(pr: dict, spec: dict, graded: list[dict]) -> list[str]:
    from lab9.eval import aggregate
    rows = pr["rows"]
    ids = [m["id"] for m in graded if all(m["id"] in r for r in rows)]
    if all("cost" in r for r in rows):
        fresh = aggregate(rows, ids, k_values=spec.get("pass_k", []))
    else:   # hand-built report without costs: recompute the graded metrics only
        fresh = {}
        for m in ids:
            vals = [r[m] for r in rows]
            fresh[m] = sum(map(bool, vals)) if m in ("secret_leak", "approval_bypass") \
                else round(sum(map(bool, vals)) / len(vals), 4)
    out = []
    for k, v in fresh.items():
        got = (pr.get("metrics") or {}).get(k)
        if v is None or got is None or _not_finite(got):
            continue
        if abs(float(got) - float(v)) > 1e-3:
            out.append(f"metric {k} reported {got} but the rows give {v} (edited report)")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []   # a new eval-set version starts its own thresholds (and needs a new baseline)
    out = []
    for key in ("eval_set", "labels", "seeds"):
        if base_spec.get(key) is not None and spec.get(key) != base_spec.get(key):
            out.append(f"ratchet: {key} changed on the same eval-set version "
                       f"({base_spec.get(key)} -> {spec.get(key)})")
    new = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        out += _looser(f"metric {m['id']}", m, new.get(m["id"]))
    skey = lambda s: (s.get("name"), s.get("metric"))
    new_s = {skey(s): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        out += _looser(f"slice {s.get('name')}/{s.get('metric')}", s, new_s.get(skey(s)))
    return out


def _looser(what: str, old: dict, new: dict | None) -> list[str]:
    if new is None:
        return [f"ratchet: {what} was removed"]
    out = []
    th_old = old.get("threshold", old)   # slices keep min / no_significant_drop at the top level
    th_new = new.get("threshold", new)
    if old.get("blocking") and not new.get("blocking"):
        out.append(f"ratchet: {what} is no longer blocking")
    for k in ("max", "max_increase"):
        if k in th_old and (k not in th_new or th_new[k] > th_old[k]):
            out.append(f"ratchet: {what} {k} {th_old[k]} -> {th_new.get(k, 'removed')} (looser)")
    if "min" in th_old and ("min" not in th_new or th_new["min"] < th_old["min"]):
        out.append(f"ratchet: {what} min {th_old['min']} -> {th_new.get('min', 'removed')} (looser)")
    if th_old.get("no_significant_drop") and not th_new.get("no_significant_drop"):
        out.append(f"ratchet: {what} dropped no_significant_drop")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            # A slice the spec names but the PR does not cover cannot be "passed": it was emptied.
            verdict, note = "missing", "no PR rows carry this slice"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
            note = f"{len(a)} item(s) {note}".strip()
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<40} {note:<38} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
