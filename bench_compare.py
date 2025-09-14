#!/usr/bin/env python3
"""
Benchmark performance between branch base, branch head, and main.

Usage:
  python bench_compare.py [base_branch]

Default base_branch is 'main'.
"""

import subprocess
import time
import statistics
import sys
import os

def run_output(cmd):
    return subprocess.check_output(cmd, shell=True).decode().strip()

def try_output(cmd):
    try:
        return run_output(cmd)
    except subprocess.CalledProcessError:
        return None

def time_run(cmd, runs=5):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run(cmd, shell=True, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        times.append(time.perf_counter() - start)
    return statistics.median(times)

def benchmark_commit(commit, label, filepath="main.py"):
    """
    Temporarily checkout a commit, run the benchmark, and restore original HEAD.
    """
    # Save current HEAD
    current_head = run_output("git rev-parse HEAD")

    # Checkout the commit
    subprocess.run(f"git checkout {commit}", shell=True, check=True)

    # Run benchmark
    result = time_run(f"python {filepath}")
    print(f"{label}: {result:.4f} s")

    # Restore original HEAD
    subprocess.run(f"git checkout {current_head}", shell=True, check=True)

    return result

if __name__ == "__main__":
    base_branch = sys.argv[1] if len(sys.argv) > 1 else "main"

    # Ensure base branch exists
    subprocess.run(f"git fetch origin {base_branch}:{base_branch}", shell=True, check=False)

    # Find merge base (where branch diverged from main)
    merge_base = try_output(f"git merge-base {base_branch} HEAD")
    if not merge_base:
        print(f"ERROR: couldn't find merge-base with {base_branch}", file=sys.stderr)
        sys.exit(2)

    # Branch start = first commit after merge base
    branch_start = try_output(f"git rev-list --reverse {merge_base}..HEAD | head -n 1") or merge_base

    # Branch end = HEAD
    branch_end = "HEAD"

    # Main = tip of base branch
    main_ref = f"origin/{base_branch}" if try_output(f"git rev-parse --verify origin/{base_branch}") else base_branch

    regress = False
    try:
        print("Running benchmarks...")

        start = benchmark_commit(branch_start, "Branch base (start)")
        end   = benchmark_commit(branch_end, "Branch tip (HEAD)")
        main  = benchmark_commit(main_ref, "Main branch tip")

        print("\n--- Performance Comparison ---")
        print(f"Branch base: {start:.4f} s")
        print(f"Branch tip:  {end:.4f} s")
        print(f"Main tip:    {main:.4f} s")

        # Regression checks
        if end > start * 1.10:
            print("❌ Regression vs branch base")
            regress = True
        else:
            print("✅ OK vs branch base")

        if end > main * 1.10:
            print("❌ Regression vs main")
            regress = True
        else:
            print("✅ OK vs main")

    finally:
        # Restore HEAD in case of error
        subprocess.run("git checkout HEAD", shell=True, check=False)

    if regress:
        sys.exit(1)
