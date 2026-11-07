#!/usr/bin/env bash
#SBATCH --job-name=wrf-hardware-probe
#SBATCH --partition=development
#SBATCH --account=acd110018
#SBATCH --nodes=9
#SBATCH --ntasks=9
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:05:00
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source perf/wrf_cpu/env.sh
srun --mpi=none --nodes="$SLURM_JOB_NUM_NODES" --ntasks="$SLURM_JOB_NUM_NODES" \
  --ntasks-per-node=1 --cpus-per-task=1 --cpu-bind=cores \
  python perf/wrf_cpu/hardware.py --output-dir "$WRF_CPU_ARTIFACTS/progress/hardware-probe-$SLURM_JOB_ID" "$@"
