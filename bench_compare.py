#!/usr/bin/env python3
"""
Benchmark between:
 - the commit that was the tip of base when this branch was created (branch-origin-parent),
 - the current branch HEAD (branch tip),
 - the current main/base tip (origin/<base_branch> or <base_branch>).

Usage:
    python bench_compare.py [base_branch] [--file main.py] [--runs 5] [--debug]

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
    # If we're on a named branch, restore to it. Otherwise restore to previous (dash)
    branch = try_output("git symbolic-ref --short -q HEAD")
    if branch:
        return f"git checkout --quiet {branch}"
    else:
        # fall back to previous checkout (git checkout -)
        return "git checkout --quiet -"

def file_exists_in_commit(commit: str, filepath: str) -> bool:
    # returns True if commit:path exists
    rc = subprocess.run(f"git cat-file -e {commit}:{filepath}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return rc.returncode == 0

def show_files_in_commit(commit: str, limit: int = 40) -> str:
    out = try_output(f"git ls-tree -r --name-only {commit} | head -n {limit}")
    return out or ""

def benchmark_commit(commit: str, label: str, filepath: str, runs: int, debug: bool=False) -> float:
    print(f"\n--- Checking out {label}: {commit} ---")
    # save restore command
    restore_cmd = detect_restore_cmd()
    try:
        safe_checkout(commit)
        # Verify file exists in this commit before running
        if not file_exists_in_commit(commit, filepath):
            print(f"ERROR: {filepath!r} not found in commit {commit}. Files at that commit (first lines):")
            print(show_files_in_commit(commit) or "(no files listed)")
            raise SystemExit(3)
        if debug:
            # print some additional info for debugging
            blob_info = try_output(f"git ls-tree -r {commit} {filepath} || true")
            print(f"DEBUG ls-tree: {blob_info}")
            short_contents = try_output(f"git show {commit}:{filepath} | sed -n '1,20p'") or ""
            print("DEBUG file head (first 20 lines):")
            print(short_contents)
        result = time_run(f"python {filepath}", runs=runs)
        print(f"{label}: {result:.4f} s")
        return result
    finally:
        # restore original HEAD/branch (best-effort)
        try:
            subprocess.run(restore_cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            # final fallback: try to checkout HEAD
            subprocess.run("git checkout --quiet HEAD", shell=True, check=False)

def ensure_fetched(base_branch: str):
    # Attempt to fetch refs to increase chance parent is present locally (best-effort)
    subprocess.run("git fetch --no-tags --prune origin", shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(f"git fetch origin {base_branch}:{base_branch}", shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Try unshallow if shallow repo
    shallow = try_output("git rev-parse --is-shallow-repository")
    if shallow == "true":
        subprocess.run("git fetch --unshallow --no-tags --prune origin", shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    # args
    base_branch = "main"
    filepath = "main.py"
    runs = 5
    debug = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--file" and i+1 < len(args):
            filepath = args[i+1]; i += 2; continue
        if a == "--runs" and i+1 < len(args):
            runs = int(args[i+1]); i += 2; continue
        if a == "--debug":
            debug = True; i += 1; continue
        if not a.startswith("--") and base_branch == "main":
            base_branch = a; i += 1; continue
        i += 1

    ensure_fetched(base_branch)
    base_ref = f"origin/{base_branch}" if try_output(f"git rev-parse --verify origin/{base_branch}") else base_branch

    # Find the first commit unique to this branch (oldest commit on branch not reachable from base_ref)
    first_branch_commit = try_output(f"git rev-list --reverse HEAD ^{base_ref} | head -n 1")

    if not first_branch_commit:
        # fallback to merge-base if nothing unique (or shallow)
        merge_base = try_output(f"git merge-base {base_ref} HEAD")
        if not merge_base:
            print("ERROR: could not determine branch creation commit nor merge-base.", file=sys.stderr)
            sys.exit(2)
        print("WARNING: could not find a commit unique to the branch relative to base. Falling back to merge-base.")
        first_branch_commit = try_output(f"git rev-list --reverse {merge_base}..HEAD | head -n 1") or merge_base

    # The commit we want as "branch origin" is the parent of the first unique commit.
    branch_origin_parent = try_output(f"git rev-parse {first_branch_commit}^")
    if not branch_origin_parent:
        # If the first unique commit has no parent (root commit), fallback to merge-base
        branch_origin_parent = try_output(f"git merge-base {base_ref} HEAD")
        if not branch_origin_parent:
            print("ERROR: could not find branch-origin parent commit.", file=sys.stderr)
            sys.exit(2)

    branch_tip = "HEAD"
    current_main_tip = base_ref

    print(f"first unique commit on branch: {first_branch_commit}")
    print(f"branch-origin-parent (commit that was tip of {base_ref} when branched): {branch_origin_parent}")
    print(f"branch tip (HEAD): {branch_tip}")
    print(f"current base tip ref used: {current_main_tip}")
    print(f"benchmark file: {filepath}, runs per commit: {runs}")

    # quick sanity: ensure file exists in branch-origin-parent before running
    if not file_exists_in_commit(branch_origin_parent, filepath):
        print(f"ERROR: {filepath!r} does not exist in branch-origin-parent {branch_origin_parent}. Aborting.", file=sys.stderr)
        print("Files at that commit (first lines):")
        print(show_files_in_commit(branch_origin_parent))
        sys.exit(3)

    regress = False
    try:
        start = benchmark_commit(branch_origin_parent, "Branch origin (parent)", filepath, runs, debug=debug)
        end   = benchmark_commit(branch_tip, "Branch tip (HEAD)", filepath, runs, debug=debug)
        main  = benchmark_commit(current_main_tip, "Current base tip", filepath, runs, debug=debug)

        print("\n--- Performance Comparison ---")
        print(f"Branch origin (parent): {start:.4f} s")
        print(f"Branch tip (HEAD):     {end:.4f} s")
        print(f"Current base tip ({current_main_tip}): {main:.4f} s")

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
        # leave repo where we started (best-effort)
        subprocess.run("git checkout --quiet -", shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if regress:
        sys.exit(1)

if __name__ == "__main__":
    main()
