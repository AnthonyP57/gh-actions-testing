#!/usr/bin/env python3
"""
Benchmark and compare performance between commits.

Usage:
  python bench_compare.py [base_branch]
"""
import subprocess, time, statistics, sys, os

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
    subprocess.run(f"git checkout {commit} -- {filepath}", shell=True, check=True)
    result = time_run(f"python {filepath}")
    print(f"{label}: {result:.4f} s")
    return result

if __name__ == "__main__":
    base_branch = sys.argv[1] if len(sys.argv) > 1 else "main"

    # Resolve base commit
    candidates = [
        f"git merge-base origin/{base_branch} HEAD",
        f"git merge-base {base_branch} HEAD",
        f"git rev-parse origin/{base_branch}",
        f"git rev-parse {base_branch}"
    ]

    base_commit = None
    for c in candidates:
        val = try_output(c)
        if val:
            base_commit = val
            break

    if base_commit is None:
        print(f"ERROR: couldn't resolve base commit for branch '{base_branch}'", file=sys.stderr)
        sys.exit(2)

    saved_main = None
    if os.path.exists("main.py"):
        with open("main.py", "rb") as f:
            saved_main = f.read()

    regress = False
    try:

        # Find merge base (common ancestor)
        merge_base = try_output(f"git merge-base origin/{base_branch} HEAD")
        if not merge_base:
            print(f"ERROR: couldn't find merge-base with {base_branch}", file=sys.stderr)
            sys.exit(2)

        # Branch start = first commit after merge-base on the PR branch
        branch_start = try_output(f"git rev-list {merge_base}..HEAD | tail -n 1") or merge_base

        # Branch end = HEAD
        branch_end = "HEAD"

        # Main = tip of base branch
        main_ref = f"origin/{base_branch}" if try_output(f"git rev-parse --verify origin/{base_branch}") else base_branch

        start = benchmark_commit(branch_start, "Branch start")
        end   = benchmark_commit(branch_end, "Branch end")
        main  = benchmark_commit(main_ref, "Main")


        print("\n--- Performance Comparison ---")
        print(f"Branch start: {start:.4f} s")
        print(f"Branch end:   {end:.4f} s")
        print(f"Main:         {main:.4f} s")

        if end > start * 1.10:
            print("❌ Regression vs branch start")
            regress = True
        else:
            print("✅ OK vs branch start")

        if end > main * 1.10:
            print("❌ Regression vs main")
            regress = True
        else:
            print("✅ OK vs main")

    finally:
        try:
            subprocess.run("git checkout HEAD -- main.py", shell=True, check=True)
        except Exception:
            if saved_main is not None:
                with open("main.py", "wb") as f:
                    f.write(saved_main)

    if regress:
        sys.exit(1)  # must be OUTSIDE the finally

