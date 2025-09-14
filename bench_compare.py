#!/usr/bin/env python3
"""
Robust bench_compare.py

Usage:
  python bench_compare.py [base_branch]

Behavior:
- Attempts multiple strategies to resolve the base commit (origin/main, main, etc).
- Checks out main.py from different commits and times running it (median of runs).
- Restores main.py at the end.
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

    # Try multiple ways to resolve a usable base commit
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

    # Save current main.py content (if present) so we can restore it if needed
    saved_main = None
    if os.path.exists("main.py"):
        with open("main.py", "rb") as f:
            saved_main = f.read()

    try:
        start = benchmark_commit(base_commit, "Branch start")
        end   = benchmark_commit("HEAD", "Branch end")

        # For "Main" try origin/{base_branch} if it exists, else fall back to base_branch
        main_ref = None
        if try_output(f"git rev-parse --verify origin/{base_branch}"):
            main_ref = f"origin/{base_branch}"
        else:
            main_ref = base_branch

        main  = benchmark_commit(main_ref, "Main")

        print("\n--- Performance Comparison ---")
        print(f"Branch start: {start:.4f} s")
        print(f"Branch end:   {end:.4f} s")
        print(f"Main:         {main:.4f} s")

        if end > start * 1.10:
            print("❌ Regression vs branch start")
        else:
            print("✅ OK vs branch start")

        if end > main * 1.10:
            print("❌ Regression vs main")
        else:
            print("✅ OK vs main")

    finally:
        # try to restore main.py from HEAD; if that fails, restore the saved content
        try:
            subprocess.run("git checkout HEAD -- main.py", shell=True, check=True)
        except Exception:
            if saved_main is not None:
                with open("main.py", "wb") as f:
                    f.write(saved_main)
