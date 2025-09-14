#!/usr/bin/env python3
"""
Benchmark between:
 - the commit that was the tip of base when this branch was created (branch-origin-parent),
 - the current branch HEAD (branch tip),
 - the current main tip (origin/<base_branch>).

Usage:
    python bench_compare.py [base_branch] [--file main.py] [--runs 5]

Defaults:
    base_branch = "main"
    file = "main.py"
    runs = 5
"""
from __future__ import annotations
import subprocess, time, statistics, sys, os
from typing import Optional

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
    # If we're on a named branch, restore to it. Otherwise restore to current commit id.
    branch = try_output("git symbolic-ref --short -q HEAD")
    if branch:
        return f"git checkout --quiet {branch}"
    else:
        head = run_output("git rev-parse HEAD")
        return f"git checkout --quiet {head}"

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
            # best effort; not fatal here
            pass

def ensure_fetched(base_branch: str):
    # Fetch origin and the base branch; try to unshallow if needed (best-effort)
    subprocess.run("git fetch --no-tags --prune origin", shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # ensure the base branch ref exists locally under origin/<base_branch>
    subprocess.run(f"git fetch origin {base_branch}:{base_branch}", shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # If repo is shallow, try to unshallow (best-effort)
    shallow = try_output("git rev-parse --is-shallow-repository")
    if shallow == "true":
        subprocess.run("git fetch --unshallow --no-tags --prune origin", shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    # parse args (minimal)
    base_branch = "main"
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
        if not a.startswith("--") and base_branch == "main":
            base_branch = a
            i += 1
            continue
        # unknown, skip
        i += 1

    # ensure we have refs available (best-effort)
    ensure_fetched(base_branch)

    # prefer origin/<base_branch> if available
    base_ref = f"origin/{base_branch}" if try_output(f"git rev-parse --verify origin/{base_branch}") else base_branch

    # Find the first commit unique to this branch (oldest commit on branch not reachable from base_ref)
    first_branch_commit = try_output(f"git rev-list --reverse HEAD ^{base_ref} | head -n 1")

    if not first_branch_commit:
        # fallback: try merge-base logic (less ideal)
        merge_base = try_output(f"git merge-base {base_ref} HEAD")
        if not merge_base:
            print("ERROR: could not determine branch creation commit or merge-base.", file=sys.stderr)
            sys.exit(2)
        print("WARNING: couldn't find a commit unique to the branch relative to base. Falling back to merge-base.")
        first_branch_commit = try_output(f"git rev-list --reverse {merge_base}..HEAD | head -n 1") or merge_base

    # The commit we want as "branch origin" is the parent of the first unique commit.
    # That parent is the commit that was the tip of base when the branch was created.
    branch_origin_parent = try_output(f"git rev-parse {first_branch_commit}^")
    if not branch_origin_parent:
        # if no parent (first commit is root), fallback to merge-base
        branch_origin_parent = try_output(f"git merge-base {base_ref} HEAD")
        if not branch_origin_parent:
            print("ERROR: could not find branch-origin parent commit.", file=sys.stderr)
            sys.exit(2)

    # For clarity, also get the tip refs we'll benchmark
    branch_tip = "HEAD"
    current_main_tip = base_ref  # this will typically be 'origin/main' or 'main' fallback

    print(f"branch first unique commit: {first_branch_commit}")
    print(f"branch-origin-parent (commit that was main when you branched): {branch_origin_parent}")
    print(f"branch tip (HEAD): {branch_tip}")
    print(f"current main ref used: {current_main_tip}")
    print(f"benchmark file: {filepath}, runs per commit: {runs}")

    regress = False
    try:
        # Run benchmarks (each run restores original HEAD)
        start = benchmark_commit(branch_origin_parent, "Branch origin (parent)", filepath, runs)
        end   = benchmark_commit(branch_tip, "Branch tip (HEAD)", filepath, runs)
        main  = benchmark_commit(current_main_tip, "Current main tip", filepath, runs)

        print("\n--- Performance Comparison ---")
        print(f"Branch origin (parent): {start:.4f} s")
        print(f"Branch tip (HEAD):     {end:.4f} s")
        print(f"Current main tip:      {main:.4f} s")

        if end > start * 1.10:
            print("❌ Regression vs branch origin (parent)")
            regress = True
        else:
            print("✅ OK vs branch origin (parent)")

        if end > main * 1.10:
            print("❌ Regression vs current main")
            regress = True
        else:
            print("✅ OK vs current main")

    finally:
        # ensure we leave the repo where we found it
        subprocess.run("git checkout --quiet -", shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if regress:
        sys.exit(1)

if __name__ == "__main__":
    main()
