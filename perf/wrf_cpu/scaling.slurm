#!/usr/bin/env bash
#SBATCH --job-name=wrf-scaling
#SBATCH --partition=development
#SBATCH --account=acd110018
#SBATCH --nodes=1
#SBATCH --ntasks=112
#SBATCH --cpus-per-task=1
#SBATCH --exclusive
#SBATCH --mem=200G
#SBATCH --time=08:00:00
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source perf/wrf_cpu/env.sh
if [[ -n ${WRF_HARDWARE_REFERENCE:-} ]]; then
  srun --mpi=none --nodes="$SLURM_JOB_NUM_NODES" --ntasks="$SLURM_JOB_NUM_NODES" \
    --ntasks-per-node=1 --cpus-per-task=1 --cpu-bind=cores \
    python perf/wrf_cpu/hardware.py --reference "$WRF_HARDWARE_REFERENCE" \
      --output-dir "$WRF_CPU_ARTIFACTS/progress/hardware-$SLURM_JOB_ID"
fi
export WRF_VERIFY_WORKERS=${WRF_VERIFY_WORKERS:-8}
python perf/wrf_cpu/verify_parallel.py --workers "$WRF_VERIFY_WORKERS" \
  --report "$WRF_CPU_ARTIFACTS/progress/verify-parallel-${SLURM_JOB_ID}.json"
python perf/wrf_cpu/scaling.py "$@"
