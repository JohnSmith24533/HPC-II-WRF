#!/usr/bin/env bash
# Run on a network-enabled login node, from the repository root.
set -euo pipefail
[[ $(git branch --show-current) == perf/wrf-cpu ]]
artifact_dir="$PWD/.wrf-cpu"
mkdir -p "$artifact_dir/downloads" "$artifact_dir/data" "$artifact_dir/logs"
if [[ ! -x $artifact_dir/env/bin/python ]]; then
  conda create --yes --prefix "$artifact_dir/env" --file perf/wrf_cpu/conda-linux-64.lock
fi
"$artifact_dir/env/bin/python" -m pip install f90nml==1.5.0
if [[ ! -d phys/physics_mmm ]]; then
  git clone --branch 20240626-MPASv8.2 --depth 1 https://github.com/NCAR/MMM-physics.git phys/physics_mmm
fi
[[ $(git -C phys/physics_mmm rev-parse HEAD) == 0ea59b1cd673006ee7a9a9958c533a6a0e354243 ]]
archive="$artifact_dir/downloads/v4.4_bench_conus12km.tar.gz"
expected=30110ce5b03b2c93b2f4e8081e24d8c83eb7be7e6bccb657a69b69b2ed953d50
if [[ ! -f $archive ]] || [[ $(sha256sum "$archive" | cut -d ' ' -f1) != "$expected" ]]; then
  curl --fail --location --retry 3 --continue-at - --output "$archive" \
    https://www2.mmm.ucar.edu/wrf/users/benchmark/v44/v4.4_bench_conus12km.tar.gz
fi
printf '%s  %s\n' "$expected" "$archive" | sha256sum --check
if [[ ! -f $artifact_dir/data/v4.4_bench_conus12km/wrfinput_d01 ]]; then
  tar -xzf "$archive" -C "$artifact_dir/data"
fi
bash perf/wrf_cpu/build.sh configure
