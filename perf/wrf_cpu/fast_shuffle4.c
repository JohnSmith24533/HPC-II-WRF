#define _GNU_SOURCE
#include <dlfcn.h>
#include <hdf5.h>
#include <smmintrin.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The pinned HDF5 library references this descriptor through its GOT. Preserve
 * its version, ID, name, applicability and local-parameter callbacks exactly. */
H5Z_class2_t H5Z_SHUFFLE[1];
static H5Z_func_t original_filter;
static int use_sse41;
static const char *original_library;
static _Atomic unsigned long long calls, fast_calls, fallback_calls, fast_bytes;

__attribute__((target("sse4.1"), noinline))
static void shuffle4(unsigned char *out, const unsigned char *in, size_t n) {
    const __m128i mask = _mm_set1_epi32(255);
    size_t i = 0;
    for (; n - i >= 16; i += 16) {
        const __m128i a = _mm_loadu_si128((const __m128i *)(in + 4*i));
        const __m128i b = _mm_loadu_si128((const __m128i *)(in + 4*i + 16));
        const __m128i c = _mm_loadu_si128((const __m128i *)(in + 4*i + 32));
        const __m128i d = _mm_loadu_si128((const __m128i *)(in + 4*i + 48));
        for (unsigned j = 0; j < 4; ++j) {
            const __m128i aa = _mm_and_si128(_mm_srli_epi32(a, 8*j), mask);
            const __m128i bb = _mm_and_si128(_mm_srli_epi32(b, 8*j), mask);
            const __m128i cc = _mm_and_si128(_mm_srli_epi32(c, 8*j), mask);
            const __m128i dd = _mm_and_si128(_mm_srli_epi32(d, 8*j), mask);
            const __m128i ab = _mm_packus_epi32(aa, bb);
            const __m128i cd = _mm_packus_epi32(cc, dd);
            _mm_storeu_si128((__m128i *)(out + j*n + i), _mm_packus_epi16(ab, cd));
        }
    }
    for (; i < n; ++i)
        for (size_t j = 0; j < 4; ++j) out[j*n+i] = in[4*i+j];
}

static size_t fast_filter(unsigned flags, size_t count, const unsigned values[],
                          size_t bytes, size_t *capacity, void **buffer) {
    atomic_fetch_add_explicit(&calls,1,memory_order_relaxed);
    if (!use_sse41 || (flags & H5Z_FLAG_REVERSE) || count != 1 ||
        values[0] != 4 || bytes/4 < 16) {
        atomic_fetch_add_explicit(&fallback_calls,1,memory_order_relaxed);
        return original_filter(flags,count,values,bytes,capacity,buffer);
    }
    unsigned char *out = malloc(bytes);
    if (!out) {
        atomic_fetch_add_explicit(&fallback_calls,1,memory_order_relaxed);
        return original_filter(flags,count,values,bytes,capacity,buffer);
    }
    shuffle4(out,*buffer,bytes/4);
    memcpy(out+4*(bytes/4),(unsigned char *)*buffer+4*(bytes/4),bytes%4);
    free(*buffer);
    *buffer = out;
    *capacity = bytes;
    atomic_fetch_add_explicit(&fast_calls,1,memory_order_relaxed);
    atomic_fetch_add_explicit(&fast_bytes,bytes,memory_order_relaxed);
    return bytes;
}

__attribute__((constructor)) static void prepare_descriptor(void) {
    const H5Z_class2_t *stock = dlsym(RTLD_NEXT,"H5Z_SHUFFLE");
    Dl_info info;
    if (!stock || stock->version != H5Z_CLASS_T_VERS ||
        stock->id != H5Z_FILTER_SHUFFLE || !stock->filter ||
        !stock->encoder_present || !stock->decoder_present ||
        strcmp(stock->name,"shuffle") || sizeof(*stock) != 48) {
        fputs("WRF shuffle: incompatible original descriptor\n",stderr);
        abort();
    }
    H5Z_SHUFFLE[0] = *stock;
    original_filter = stock->filter;
    __builtin_cpu_init();
    use_sse41 = __builtin_cpu_supports("sse4.1") != 0;
    if (!dladdr((void *)original_filter,&info) || !info.dli_fname) abort();
    original_library = info.dli_fname;
    H5Z_SHUFFLE[0].filter = fast_filter;
}

__attribute__((destructor)) static void report_backend(void) {
    const char *prefix=getenv("WRF_FAST_SHUFFLE_REPORT"), *rank=getenv("OMPI_COMM_WORLD_RANK");
    unsigned long long total=atomic_load_explicit(&calls,memory_order_relaxed);
    if (!prefix || !total) return;
    if (!rank) rank="standalone";
    char path[4096];
    if (snprintf(path,sizeof(path),"%s-r%s.json",prefix,rank)>=(int)sizeof(path)) return;
    FILE *f=fopen(path,"w");
    if (!f) return;
    fprintf(f,"{\"calls\":%llu,\"fast_calls\":%llu,\"fallback_calls\":%llu,\"fast_bytes\":%llu,\"sse41\":%s,\"descriptor_version\":%d,\"original_library\":\"%s\"}\n",
        total,atomic_load_explicit(&fast_calls,memory_order_relaxed),
        atomic_load_explicit(&fallback_calls,memory_order_relaxed),
        atomic_load_explicit(&fast_bytes,memory_order_relaxed),
        use_sse41?"true":"false",H5Z_SHUFFLE[0].version,original_library);
    fclose(f);
}
