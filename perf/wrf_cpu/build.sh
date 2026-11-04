#!/usr/bin/env bash
#SBATCH --job-name=wrf-baseline-build
#SBATCH --partition=development
#SBATCH --account=acd110018
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=120G
#SBATCH --time=02:00:00
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(pwd)}"
source perf/wrf_cpu/env.sh
[[ ! -e $WRF_CPU_ARTIFACTS/golden/manifest.json ]] || { echo 'Golden exists: baseline build is frozen; use a separate candidate build/install.' >&2; exit 1; }
[[ $(git branch --show-current) == perf/wrf-cpu ]]
# Refuse a changed model. Harness additions do not change official WRF sources.
[[ -z $(git diff HEAD -- . ':!perf' ':!.gitignore') ]]
[[ $(git -C phys/physics_mmm rev-parse HEAD) == 0ea59b1cd673006ee7a9a9958c533a6a0e354243 ]]
mkdir -p "$WRF_CPU_ARTIFACTS/baseline" "$WRF_CPU_ARTIFACTS/logs"
git rev-parse HEAD > "$WRF_CPU_ARTIFACTS/baseline/source-commit.txt"
git submodule status > "$WRF_CPU_ARTIFACTS/baseline/submodules.txt"
git -C phys/physics_mmm rev-parse HEAD > "$WRF_CPU_ARTIFACTS/baseline/mmm-physics-commit.txt"
for component in phys/physics_mmm phys/noahmp phys/MYNN-EDMF; do
  git -C "$component" archive HEAD > "$WRF_CPU_ARTIFACTS/baseline/$(basename "$component").tar"
done
python -m pip freeze > "$WRF_CPU_ARTIFACTS/baseline/pip-freeze.txt"
git archive HEAD > "$WRF_CPU_ARTIFACTS/baseline/source.tar"
conda list --explicit --prefix "$NETCDF" > "$WRF_CPU_ARTIFACTS/baseline/conda-explicit.txt"
module list 2> "$WRF_CPU_ARTIFACTS/baseline/modules.txt"
lscpu > "$WRF_CPU_ARTIFACTS/baseline/build-cpu.txt"
gfortran --version > "$WRF_CPU_ARTIFACTS/baseline/compiler.txt"
mpirun --version > "$WRF_CPU_ARTIFACTS/baseline/mpi.txt"
for kind in ideal real; do
  case_name=EM_B_WAVE
  [[ $kind != real ]] || case_name=EM_REAL
  if [[ ${1:-build} == configure ]]; then
  cmake -S "$WRF_CPU_ROOT" -B "$WRF_CPU_ARTIFACTS/build-$kind" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$WRF_CPU_ROOT/perf/wrf_cpu/gnu.cmake" \
    -DCMAKE_INSTALL_PREFIX="$WRF_CPU_ARTIFACTS/install-$kind" \
    -DCMAKE_PREFIX_PATH="$NETCDF" -DnetCDF_ROOT="$NETCDF" -DnetCDF-Fortran_ROOT="$NETCDF" \
    -DCMAKE_C_COMPILER_LAUNCHER=ccache -DWRF_CORE=ARW -DWRF_NESTING=NONE \
    -DWRF_CASE="$case_name" -DUSE_MPI=ON -DUSE_OPENMP=OFF -DUSE_DOUBLE=OFF \
    -DUSE_IPO=OFF -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    > "$WRF_CPU_ARTIFACTS/logs/configure-$kind.log" 2>&1
  continue
  fi
  cmake --build "$WRF_CPU_ARTIFACTS/build-$kind" --parallel "${SLURM_CPUS_PER_TASK:-16}" \
    > "$WRF_CPU_ARTIFACTS/logs/build-$kind.log" 2>&1
  cmake --install "$WRF_CPU_ARTIFACTS/build-$kind" > "$WRF_CPU_ARTIFACTS/logs/install-$kind.log" 2>&1
  cp "$WRF_CPU_ARTIFACTS/build-$kind/CMakeCache.txt" "$WRF_CPU_ARTIFACTS/baseline/CMakeCache-$kind.txt"
done
[[ ${1:-build} != configure ]] || exit 0
ccache --show-stats > "$WRF_CPU_ARTIFACTS/baseline/ccache.txt"
sha256sum "$WRF_CPU_ARTIFACTS"/install-{ideal,real}/bin/* > "$WRF_CPU_ARTIFACTS/baseline/executables.sha256"
date -u +%FT%TZ > "$WRF_CPU_ARTIFACTS/baseline/build-complete.txt"
