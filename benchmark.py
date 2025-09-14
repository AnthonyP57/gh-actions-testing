import subprocess, time, statistics

def time_run(cmd, runs=5):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run(cmd, shell=True, check=True)
        times.append(time.perf_counter() - start)
    return statistics.median(times)

if __name__ == "__main__":
    result = time_run("python main.py", runs=5)
    print(f"{result:.4f}")
