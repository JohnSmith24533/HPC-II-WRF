#include <stddef.h>
#include <limits.h>
#include <string.h>

/* Copy IKJ halo rows without an out-of-line memcpy for each short row.
 * Raw bytes preserve INTEGER/REAL bit patterns. Wider rows retain libc memcpy.
 * The Fortran dispatcher keeps its original path when this file is not enabled.
 */
#if CHAR_BIT != 8
#error "IKJ byte copies require 8-bit bytes"
#endif
typedef char rsl_fast_integer_size_check[(sizeof(int) == 4) ? 1 : -1];

#if defined(NOUNDERSCORE)
# define RSL_FAST_PACK_INT_IKJ rsl_fast_pack_int_ikj
# define RSL_FAST_UNPACK_INT_IKJ rsl_fast_unpack_int_ikj
# define RSL_FAST_PACK_LINT_IKJ rsl_fast_pack_lint_ikj
# define RSL_FAST_UNPACK_LINT_IKJ rsl_fast_unpack_lint_ikj
#elif defined(F2CSTYLE)
# define RSL_FAST_PACK_INT_IKJ rsl_fast_pack_int_ikj__
# define RSL_FAST_UNPACK_INT_IKJ rsl_fast_unpack_int_ikj__
# define RSL_FAST_PACK_LINT_IKJ rsl_fast_pack_lint_ikj__
# define RSL_FAST_UNPACK_LINT_IKJ rsl_fast_unpack_lint_ikj__
#else
# define RSL_FAST_PACK_INT_IKJ rsl_fast_pack_int_ikj_
# define RSL_FAST_UNPACK_INT_IKJ rsl_fast_unpack_int_ikj_
# define RSL_FAST_PACK_LINT_IKJ rsl_fast_pack_lint_ikj_
# define RSL_FAST_UNPACK_LINT_IKJ rsl_fast_unpack_lint_ikj_
#endif

#define COPY_ROWS(N) do { \
    int j,k; \
    for (j=0;j<nj;j++) { \
        unsigned char *d=destination+(ptrdiff_t)j*dj; \
        const unsigned char *s=source+(ptrdiff_t)j*sj; \
        for (k=0;k<nk;k++) { memcpy(d,s,(size_t)(N)*WORD_BYTES);s+=sk;d+=dk; } \
    } \
} while(0)

#define WORD_BYTES 4
static void copy4(unsigned char *destination,const unsigned char *source,int nx,int nk,int nj,ptrdiff_t sk,ptrdiff_t sj,ptrdiff_t dk,ptrdiff_t dj) {
    switch(nx) {
        case 1: COPY_ROWS(1); break;
        case 2: COPY_ROWS(2); break;
        case 3: COPY_ROWS(3); break;
        case 4: COPY_ROWS(4); break;
        case 5: COPY_ROWS(5); break;
        case 6: COPY_ROWS(6); break;
        case 7: COPY_ROWS(7); break;
        case 8: COPY_ROWS(8); break;
        case 9: COPY_ROWS(9); break;
        case 10: COPY_ROWS(10); break;
        case 11: COPY_ROWS(11); break;
        case 12: COPY_ROWS(12); break;
        case 13: COPY_ROWS(13); break;
        case 14: COPY_ROWS(14); break;
        case 15: COPY_ROWS(15); break;
        case 16: COPY_ROWS(16); break;
        case 17: COPY_ROWS(17); break;
        case 18: COPY_ROWS(18); break;
        case 19: COPY_ROWS(19); break;
        case 20: COPY_ROWS(20); break;
        case 21: COPY_ROWS(21); break;
        case 22: COPY_ROWS(22); break;
        case 23: COPY_ROWS(23); break;
        case 24: COPY_ROWS(24); break;
        case 25: COPY_ROWS(25); break;
        case 26: COPY_ROWS(26); break;
        case 27: COPY_ROWS(27); break;
        case 28: COPY_ROWS(28); break;
        case 29: COPY_ROWS(29); break;
        case 30: COPY_ROWS(30); break;
        case 31: COPY_ROWS(31); break;
        case 32: COPY_ROWS(32); break;
        default: COPY_ROWS(nx);break;
    }
}
#undef WORD_BYTES
#define WORD_BYTES 8
static void copy8(unsigned char *destination,const unsigned char *source,int nx,int nk,int nj,ptrdiff_t sk,ptrdiff_t sj,ptrdiff_t dk,ptrdiff_t dj) {
    switch(nx) {
        case 1: COPY_ROWS(1); break;
        case 2: COPY_ROWS(2); break;
        case 3: COPY_ROWS(3); break;
        case 4: COPY_ROWS(4); break;
        case 5: COPY_ROWS(5); break;
        case 6: COPY_ROWS(6); break;
        case 7: COPY_ROWS(7); break;
        case 8: COPY_ROWS(8); break;
        case 9: COPY_ROWS(9); break;
        case 10: COPY_ROWS(10); break;
        case 11: COPY_ROWS(11); break;
        case 12: COPY_ROWS(12); break;
        case 13: COPY_ROWS(13); break;
        case 14: COPY_ROWS(14); break;
        case 15: COPY_ROWS(15); break;
        case 16: COPY_ROWS(16); break;
        case 17: COPY_ROWS(17); break;
        case 18: COPY_ROWS(18); break;
        case 19: COPY_ROWS(19); break;
        case 20: COPY_ROWS(20); break;
        case 21: COPY_ROWS(21); break;
        case 22: COPY_ROWS(22); break;
        case 23: COPY_ROWS(23); break;
        case 24: COPY_ROWS(24); break;
        case 25: COPY_ROWS(25); break;
        case 26: COPY_ROWS(26); break;
        case 27: COPY_ROWS(27); break;
        case 28: COPY_ROWS(28); break;
        case 29: COPY_ROWS(29); break;
        case 30: COPY_ROWS(30); break;
        case 31: COPY_ROWS(31); break;
        case 32: COPY_ROWS(32); break;
        default: COPY_ROWS(nx);break;
    }
}
#undef WORD_BYTES

#define ARGS const void *input,void *output,const int *js,const int *je,const int *ks,const int *ke,const int *is,const int *ie,const int *jms,const int *jme,const int *kms,const int *kme,const int *ims,const int *ime,int *curs
#define DEFINE_BINDING(NAME,BYTES,UNPACK,COPY) \
void NAME(ARGS) { \
    int nx=*ie-*is+1,nk=*ke-*ks+1,nj=*je-*js+1; \
    ptrdiff_t mi=(ptrdiff_t)*ime-*ims+1,mk=(ptrdiff_t)*kme-*kms+1; \
    ptrdiff_t offset=((ptrdiff_t)*is-*ims+((ptrdiff_t)*ks-*kms)*mi+((ptrdiff_t)*js-*jms)*mi*mk)*BYTES; \
    const unsigned char *source=(const unsigned char *)input; \
    unsigned char *destination=(unsigned char *)output; \
    *curs=nx*nk*nj; \
    if(nx<=0||nk<=0||nj<=0)return; \
    if(UNPACK)COPY(destination+offset,source,nx,nk,nj,(ptrdiff_t)nx*BYTES,(ptrdiff_t)nx*nk*BYTES,mi*BYTES,mi*mk*BYTES); \
    else COPY(destination,source+offset,nx,nk,nj,mi*BYTES,mi*mk*BYTES,(ptrdiff_t)nx*BYTES,(ptrdiff_t)nx*nk*BYTES); \
}
DEFINE_BINDING(RSL_FAST_PACK_INT_IKJ,4,0,copy4)
DEFINE_BINDING(RSL_FAST_UNPACK_INT_IKJ,4,1,copy4)
DEFINE_BINDING(RSL_FAST_PACK_LINT_IKJ,8,0,copy8)
DEFINE_BINDING(RSL_FAST_UNPACK_LINT_IKJ,8,1,copy8)
