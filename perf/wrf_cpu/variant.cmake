# Keep the baseline arithmetic options unless a recorded experiment adds flags.
include("${CMAKE_CURRENT_LIST_DIR}/gnu.cmake")
if(DEFINED WRF_EXTRA_FCFLAGS)
  string(APPEND WRF_FCOPTIM " ${WRF_EXTRA_FCFLAGS}")
endif()
