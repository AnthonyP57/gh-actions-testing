import subprocess, time, statistics, sys, os

def time_run(cmd, runs=5):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        times.append(time.perf_counter() - start)
    return statistics.median(times)

def benchmark_commit(commit, label):
    subprocess.run(f"git checkout {commit} -- main.py", shell=True, check=True)
    result = time_run("python main.py")
    print(f"{label}: {result:.4f} s")
    return result

if __name__ == "__main__":
    base_branch = sys.argv[1] if len(sys.argv) > 1 else "main"

    # figure out commits
    base_commit = subprocess.check_output(
        f"git merge-base origin/{base_branch} HEAD", shell=True
    ).decode().strip()

    start = benchmark_commit(base_commit, "Branch start")
    end   = benchmark_commit("HEAD", "Branch end")
    main  = benchmark_commit(f"origin/{base_branch}", "Main")

    print("\n--- Performance Comparison ---")
    print(f"Branch start: {start:.4f} s")
    print(f"Branch end:   {end:.4f} s")
    print(f"Main:         {main:.4f} s")

    problems = []
    if end > start * 1.10:
        problems.append(f"❌ Regression vs branch start: {end:.4f}s vs {start:.4f}s")
    else:
        print(f"✅ OK vs branch start")

    if end > main * 1.10:
        problems.append(f"❌ Regression vs main: {end:.4f}s vs {main:.4f}s")
    else:
        print(f"✅ OK vs main")

    if problems:
        sys.exit("\n".join(problems))
