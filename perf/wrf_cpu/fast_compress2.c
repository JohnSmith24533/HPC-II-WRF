#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <zlib.h>
#include "libdeflate.h"

typedef int (*compress_fn)(Bytef *,uLongf *,const Bytef *,uLong,int);
static compress_fn original_compress;
static pthread_once_t original_once=PTHREAD_ONCE_INIT;
static _Atomic unsigned long long calls,fast_calls,fallback_calls,input_bytes;
static void resolve_original(void) {
    void *handle=dlopen("libz.so.1",RTLD_LAZY|RTLD_LOCAL);
    if (handle) {
        union { void *object; compress_fn function; } address;
        address.object=dlsym(handle,"compress2"); original_compress=address.function;
    }
}
static int fallback(Bytef *dest,uLongf *destlen,const Bytef *source,uLong length,int level) {
    atomic_fetch_add_explicit(&fallback_calls,1,memory_order_relaxed);
    pthread_once(&original_once,resolve_original);
    return original_compress ? original_compress(dest,destlen,source,length,level) : Z_STREAM_ERROR;
}
int ZEXPORT compress2(Bytef *dest,uLongf *destlen,const Bytef *source,uLong length,int level) {
    struct libdeflate_compressor *compressor;
    size_t size;
    atomic_fetch_add_explicit(&calls,1,memory_order_relaxed);
    if (!destlen || !dest || !source || level < -1 || level > 9)
        return fallback(dest,destlen,source,length,level);
    compressor=libdeflate_alloc_compressor(level == -1 ? 6 : level);
    if (!compressor) return fallback(dest,destlen,source,length,level);
    size=libdeflate_zlib_compress(compressor,source,(size_t)length,dest,(size_t)*destlen);
    libdeflate_free_compressor(compressor);
    if (!size) return fallback(dest,destlen,source,length,level);
    *destlen=(uLongf)size;
    atomic_fetch_add_explicit(&fast_calls,1,memory_order_relaxed);
    atomic_fetch_add_explicit(&input_bytes,length,memory_order_relaxed);
    return Z_OK;
}
__attribute__((destructor)) static void report_backend(void) {
    const char *prefix=getenv("WRF_FAST_DEFLATE_REPORT");
    const char *rank=getenv("OMPI_COMM_WORLD_RANK");
    char path[4096];
    FILE *stream;
    unsigned long long total=atomic_load_explicit(&calls,memory_order_relaxed);
    if (!prefix || !total) return;
    if (!rank) rank="standalone";
    if (snprintf(path,sizeof(path),"%s-r%s.json",prefix,rank)>=(int)sizeof(path)) return;
    stream=fopen(path,"w"); if (!stream) return;
    fprintf(stream,"{\"calls\":%llu,\"fast_calls\":%llu,\"fallback_calls\":%llu,\"input_bytes\":%llu}\n",total,
            atomic_load_explicit(&fast_calls,memory_order_relaxed),
            atomic_load_explicit(&fallback_calls,memory_order_relaxed),
            atomic_load_explicit(&input_bytes,memory_order_relaxed));
    fclose(stream);
}
