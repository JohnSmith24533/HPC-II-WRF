#!/usr/bin/env bash
#SBATCH --job-name=wrf-candidate-build
#SBATCH --partition=development
#SBATCH --account=acd110018
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=160G
#SBATCH --time=02:00:00
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source perf/wrf_cpu/env.sh
python perf/wrf_cpu/candidate_build.py build "$@"
