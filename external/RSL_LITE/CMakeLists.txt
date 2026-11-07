# WRF CMake Build

get_filename_component( FOLDER_COMPILE_TARGET ${CMAKE_CURRENT_SOURCE_DIR} NAME)

add_library(
            ${FOLDER_COMPILE_TARGET}
              STATIC
              )

target_sources(
                ${FOLDER_COMPILE_TARGET}
                PRIVATE
                  c_code.c
                  buf_for_proc.c
                  rsl_malloc.c
                  rsl_bcast.c
                  task_for_point.c
                  period.c
                  swap.c
                  cycle.c
                  f_pack.F90
                  f_xpose.F90
                  )

# Short GNU rows use constant byte copies. The Fortran dispatcher keeps
# large OpenMP copies parallel and leaves non-GNU/legacy paths unchanged.
if(CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
  target_sources(${FOLDER_COMPILE_TARGET} PRIVATE pack_ikj.c)
  target_compile_definitions(${FOLDER_COMPILE_TARGET} PRIVATE RSL_LITE_FAST_IKJ)
endif()

set_target_properties( 
                      ${FOLDER_COMPILE_TARGET} 
                        PROPERTIES
                          Fortran_MODULE_DIRECTORY ${CMAKE_INSTALL_PREFIX}/${FOLDER_COMPILE_TARGET}
                          EXPORT_PROPERTIES        Fortran_MODULE_DIRECTORY
                      )


target_link_libraries(  ${FOLDER_COMPILE_TARGET}
                          PRIVATE
                            $<$<BOOL:${USE_MPI}>:$<TARGET_NAME_IF_EXISTS:MPI::MPI_Fortran>>
                            $<$<BOOL:${USE_OPENMP}>:$<TARGET_NAME_IF_EXISTS:OpenMP::OpenMP_Fortran>>
                        )

install(
        TARGETS ${FOLDER_COMPILE_TARGET}
        EXPORT  ${EXPORT_NAME}Targets
        RUNTIME DESTINATION bin/
        ARCHIVE DESTINATION lib/
        LIBRARY DESTINATION lib/
        )
