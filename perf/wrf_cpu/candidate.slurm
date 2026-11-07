#!/usr/bin/env bash
#SBATCH --job-name=wrf-candidate
#SBATCH --partition=development
#SBATCH --account=acd110018
#SBATCH --nodes=1
#SBATCH --ntasks=112
#SBATCH --ntasks-per-node=112
#SBATCH --exclusive
#SBATCH --mem=200G
#SBATCH --time=03:00:00
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source perf/wrf_cpu/env.sh
export WRF_VERIFY_WORKERS=8
python perf/wrf_cpu/candidate_run.py "$@"
