# Toolchain-only check: no compiler invocation or WRF model execution.
set(WRF_EXTRA_FCFLAGS "-g")
include("${CMAKE_CURRENT_LIST_DIR}/variant.cmake")
if(NOT WRF_FCOPTIM STREQUAL "-O2 -ftree-vectorize -funroll-loops -g")
  message(FATAL_ERROR "Candidate toolchain dropped or changed baseline options")
endif()
