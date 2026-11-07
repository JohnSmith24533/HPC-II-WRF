#define _GNU_SOURCE
#include <dlfcn.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#include "igzip_lib.h"

typedef int (*compress_fn)(Bytef *,uLongf *,const Bytef *,uLong,int);
static compress_fn original_compress;
static pthread_once_t original_once=PTHREAD_ONCE_INIT;
static _Atomic unsigned long long calls,fast_calls,fallback_calls,input_bytes;
static void resolve_original(void) {
    void *handle=dlopen("libz.so.1",RTLD_LAZY|RTLD_LOCAL);
    if (handle) {
        union { void *object; compress_fn function; } address;
        address.object=dlsym(handle,"compress2");original_compress=address.function;
    }
}
static int fallback(Bytef *dest,uLongf *destlen,const Bytef *source,uLong length,int level) {
    atomic_fetch_add_explicit(&fallback_calls,1,memory_order_relaxed);
    pthread_once(&original_once,resolve_original);
    return original_compress?original_compress(dest,destlen,source,length,level):Z_STREAM_ERROR;
}
int ZEXPORT compress2(Bytef *dest,uLongf *destlen,const Bytef *source,uLong length,int level) {
    struct isal_zstream *stream;
    void *buffer;
    uint32_t written;
    int result,complete;
    atomic_fetch_add_explicit(&calls,1,memory_order_relaxed);
    if (!destlen || !dest || !source || level!=2 || length>UINT32_MAX || *destlen>UINT32_MAX)
        return fallback(dest,destlen,source,length,level);
    stream=aligned_alloc(64,(sizeof(*stream)+63)&~(size_t)63);
    buffer=malloc(ISAL_DEF_LVL2_DEFAULT);
    if (!stream || !buffer) {
        free(stream);free(buffer);
        return fallback(dest,destlen,source,length,level);
    }
    memset(stream,0,sizeof(*stream));isal_deflate_stateless_init(stream);
    stream->next_in=(uint8_t *)(uintptr_t)source;stream->avail_in=(uint32_t)length;
    stream->next_out=dest;stream->avail_out=(uint32_t)*destlen;
    stream->level=2;stream->level_buf=buffer;stream->level_buf_size=ISAL_DEF_LVL2_DEFAULT;
    stream->gzip_flag=IGZIP_ZLIB;stream->end_of_stream=1;stream->flush=NO_FLUSH;
    result=isal_deflate_stateless(stream);written=stream->total_out;
    complete=result==COMP_OK && stream->avail_in==0 && stream->total_in==(uint32_t)length;
    free(buffer);free(stream);
    if (!complete) return fallback(dest,destlen,source,length,level);
    *destlen=written;
    atomic_fetch_add_explicit(&fast_calls,1,memory_order_relaxed);
    atomic_fetch_add_explicit(&input_bytes,length,memory_order_relaxed);
    return Z_OK;
}
__attribute__((destructor)) static void report_backend(void) {
    const char *prefix=getenv("WRF_FAST_DEFLATE_REPORT"),*rank=getenv("OMPI_COMM_WORLD_RANK");
    char path[4096];FILE *f;
    unsigned long long total=atomic_load_explicit(&calls,memory_order_relaxed);
    if (!prefix || !total) return;
    if (!rank) rank="standalone";
    if (snprintf(path,sizeof(path),"%s-r%s.json",prefix,rank)>=(int)sizeof(path)) return;
    f=fopen(path,"w");if (!f) return;
    fprintf(f,"{\"calls\":%llu,\"fast_calls\":%llu,\"fallback_calls\":%llu,\"input_bytes\":%llu}\n",total,
            atomic_load_explicit(&fast_calls,memory_order_relaxed),
            atomic_load_explicit(&fallback_calls,memory_order_relaxed),
            atomic_load_explicit(&input_bytes,memory_order_relaxed));
    fclose(f);
}
