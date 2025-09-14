#!/usr/bin/env python3
"""
Benchmark between:
 - the commit that was the tip of the branch you created from (branch-origin-parent),
 - the current branch HEAD (branch tip),
 - the current tip(s) of the base branch(es) that contain that parent.

This script auto-detects the base branch (does not assume 'main').

Usage:
    python bench_compare.py [--file main.py] [--runs 5]

Defaults:
    file = "main.py"
    runs = 5
"""
from __future__ import annotations
import subprocess, time, statistics, sys, os
from typing import Optional, List

def run_output(cmd: str) -> str:
    return subprocess.check_output(cmd, shell=True).decode().strip()

def try_output(cmd: str) -> Optional[str]:
    try:
        return run_output(cmd)
    except subprocess.CalledProcessError:
        return None

def time_run(cmd: str, runs: int = 5) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run(cmd, shell=True, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        times.append(time.perf_counter() - start)
    return statistics.median(times)

def safe_checkout(commit: str):
    subprocess.run(f"git checkout --quiet {commit}", shell=True, check=True)

def detect_restore_cmd() -> str:
    branch = try_output("git symbolic-ref --short -q HEAD")
    if branch:
        return f"git checkout --quiet {branch}"
    else:
        head = run_output("git rev-parse HEAD")
        return f"git checkout --quiet {head}"

def branches_containing(commit: str) -> List[str]:
    """
    Returns a list of refs (as printed by `git branch --all --contains <commit>`)
    normalized (strip leading markers and 'remotes/' prefix).
    """
    out = try_output(f"git branch --all --contains {commit} 2>/dev/null")
    if not out:
        return []
    lines = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # remove leading "* " if present
        if line.startswith("* "):
            line = line[2:].strip()
        # skip '->' lines (HEAD -> origin/main)
        if "->" in line:
            continue
        # normalize remotes/ prefix: "remotes/origin/main" -> "origin/main"
        if line.startswith("remotes/"):
            line = line[len("remotes/"):]
        lines.append(line)
    return lines

def find_branch_origin_parent() -> Optional[tuple]:
    """
    Scan old->new commits of HEAD; for each commit take its parent and check
    whether that parent is present in other branch refs. If found, return
    (first_unique_commit, parent_commit, branches_containing_parent_list).
    """
    # get current branch name (if any)
    current_branch = try_output("git symbolic-ref --short -q HEAD") or ""
    # iterate commits oldest->newest on HEAD
    revs = try_output("git rev-list --reverse HEAD")
    if not revs:
        return None
    for commit in revs.splitlines():
        # skip commits that are also reachable from some remote/local branch? we still need the first unique commit
        # find parent
        parent = try_output(f"git rev-parse {commit}^")
        if not parent:
            # root commit; continue searching
            continue
        # find which refs contain that parent
        refs = branches_containing(parent)
        # remove entries that are just the current branch (we want "other" branches)
        other_refs = [r for r in refs if (r != current_branch and not r.endswith(f"/{current_branch}"))]
        if other_refs:
            # parent is present in other refs -> we found branch creation point
            return commit, parent, other_refs
    return None

def ensure_fetched(): 
    # Attempt to fetch refs to increase chance parent is present locally
    subprocess.run("git fetch --no-tags --prune origin", shell=True, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # If shallow, try unshallow
    shallow = try_output("git rev-parse --is-shallow-repository")
    if shallow == "true":
        subprocess.run("git fetch --unshallow --no-tags --prune origin", shell=True, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def benchmark_commit(commit: str, label: str, filepath: str, runs: int) -> float:
    print(f"\n--- Checking out {label}: {commit} ---")
    restore_cmd = detect_restore_cmd()
    try:
        safe_checkout(commit)
        result = time_run(f"python {filepath}", runs=runs)
        print(f"{label}: {result:.4f} s")
        return result
    finally:
        # Always attempt to restore original HEAD/branch
        try:
            subprocess.run(restore_cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

def pick_preferred_ref(refs: List[str]) -> str:
    """
    Given a list of refs (like ['origin/main','origin/dev','master','feature/x']),
    prefer origin/main, origin/master, then first origin/*, then first local.
    Returns the chosen ref string.
    """
    if not refs:
        return ""
    # normalize unique order
    seen = []
    for r in refs:
        if r not in seen:
            seen.append(r)
    refs = seen
    # prefer origin/main then origin/master
    if "origin/main" in refs:
        return "origin/main"
    if "origin/master" in refs:
        return "origin/master"
    for r in refs:
        if r.startswith("origin/"):
            return r
    # fallback to first non-HEAD-looking ref
    return refs[0]

def main():
    # parse args (minimal)
    filepath = "main.py"
    runs = 5
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--file" and i+1 < len(args):
            filepath = args[i+1]; i += 2; continue
        if a == "--runs" and i+1 < len(args):
            runs = int(args[i+1]); i += 2; continue
        # unknown flag, skip
        i += 1

    ensure_fetched()

    # Try to detect branch-origin-parent by scanning commits
    found = find_branch_origin_parent()

    if found:
        first_unique, branch_origin_parent, refs = found
        chosen_base_ref = pick_preferred_ref(refs)
        if not chosen_base_ref:
            chosen_base_ref = refs[0]
        print(f"Detected first unique commit on branch: {first_unique}")
        print(f"Detected branch-origin-parent (commit that was tip of base when branched): {branch_origin_parent}")
        print(f"Refs that contain that parent: {refs}")
        print(f"Chosen base ref to represent current base tip: {chosen_base_ref}")
    else:
        # fallback: use merge-base with origin/main if nothing else found
        print("Warning: could not auto-detect branch-origin-parent by scanning. Falling back to merge-base with origin/main.", file=sys.stderr)
        base_ref = "origin/main" if try_output("git rev-parse --verify origin/main") else "main"
        merge_base = try_output(f"git merge-base {base_ref} HEAD")
        if not merge_base:
            print("ERROR: fallback merge-base failed.", file=sys.stderr)
            sys.exit(2)
        first_unique = try_output(f"git rev-list --reverse {merge_base}..HEAD | head -n 1") or merge_base
        branch_origin_parent = try_output(f"git rev-parse {first_unique}^") or merge_base
        chosen_base_ref = base_ref
        print(f"Fallback branch-origin-parent: {branch_origin_parent} (from merge-base)")

    branch_tip = "HEAD"
    current_base_tip = chosen_base_ref or "origin/main"

    print(f"\nBenchmarking file '{filepath}' with {runs} runs per commit.")
    print(f"branch-origin-parent: {branch_origin_parent}")
    print(f"branch tip (HEAD): {branch_tip}")
    print(f"current base tip ref used: {current_base_tip}")

    regress = False
    try:
        start = benchmark_commit(branch_origin_parent, "Branch origin (parent)", filepath, runs)
        end   = benchmark_commit(branch_tip, "Branch tip (HEAD)", filepath, runs)
        main  = benchmark_commit(current_base_tip, "Current base tip (chosen)", filepath, runs)

        print("\n--- Performance Comparison ---")
        print(f"Branch origin (parent): {start:.4f} s")
        print(f"Branch tip (HEAD):     {end:.4f} s")
        print(f"Current base tip ({current_base_tip}): {main:.4f} s")

        if end > start * 1.10:
            print("❌ Regression vs branch origin (parent)")
            regress = True
        else:
            print("✅ OK vs branch origin (parent)")

        if end > main * 1.10:
            print("❌ Regression vs current base tip")
            regress = True
        else:
            print("✅ OK vs current base tip")

    finally:
        # return to previous working state
        subprocess.run("git checkout --quiet -", shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if regress:
        sys.exit(1)

if __name__ == "__main__":
    main()
