#!/usr/bin/env bash
#SBATCH --job-name=wrf-profile
#SBATCH --partition=development
#SBATCH --account=acd110018
#SBATCH --nodes=1
#SBATCH --ntasks=112
#SBATCH --cpus-per-task=1
#SBATCH --exclusive
#SBATCH --mem=200G
#SBATCH --time=02:00:00
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source perf/wrf_cpu/env.sh
export WRF_VERIFY_WORKERS=${WRF_VERIFY_WORKERS:-8}
python perf/wrf_cpu/wrf_profile.py "$@"
