#!/usr/bin/env bash
#SBATCH --job-name=wrf-golden-verify
#SBATCH --partition=development
#SBATCH --account=acd110018
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
#SBATCH --time=04:00:00
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source perf/wrf_cpu/env.sh
python perf/wrf_cpu/run.py --label replay --against baseline
python perf/wrf_cpu/publish.py --baseline baseline --replay replay
python perf/wrf_cpu/audit.py
python perf/wrf_cpu/summarize.py
