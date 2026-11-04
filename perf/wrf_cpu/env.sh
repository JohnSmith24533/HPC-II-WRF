#!/usr/bin/env bash
# Source from any directory. Keep dependencies and caches inside this worktree.
WRF_CPU_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
export WRF_CPU_ROOT
export WRF_CPU_ARTIFACTS=${WRF_CPU_ARTIFACTS:-$WRF_CPU_ROOT/.wrf-cpu}
module load gcc/10.4.0 openmpi/5.0.2
export NETCDF="$WRF_CPU_ARTIFACTS/env"
export PATH="$NETCDF/bin:$PATH"
export LD_LIBRARY_PATH="$NETCDF/lib:${LD_LIBRARY_PATH:-}"
export CCACHE_DIR="$WRF_CPU_ARTIFACTS/ccache"
export CCACHE_BASEDIR="$WRF_CPU_ROOT"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export HDF5_USE_FILE_LOCKING=FALSE
