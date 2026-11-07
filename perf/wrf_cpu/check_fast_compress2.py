from pathlib import Path
import concurrent.futures,ctypes,hashlib,json,os,statistics,time,zlib
import numpy as np
import netCDF4
import argparse


def main():
    parser=argparse.ArgumentParser(description='Check lossless compress2 compatibility and benchmark real WRF chunks; not a WRF speedup.')
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--backend-name',choices=['libdeflate','isal'],default='libdeflate')
    parser.add_argument('--input',type=Path,help='specific frozen CONUS history file for real chunks')
    args=parser.parse_args()
    if args.report.exists():
        parser.error('preserve existing report; choose a new output path')
    lib=ctypes.CDLL(str(args.library.resolve()))
    stock=ctypes.CDLL(str(Path(os.environ['NETCDF'])/'lib/libz.so.1'))
    for handle in [lib,stock]:
        handle.compress2.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong),ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int]
        handle.compress2.restype=ctypes.c_int
    stock.compressBound.argtypes=[ctypes.c_ulong];stock.compressBound.restype=ctypes.c_ulong

    def compress(handle,data,level=2,capacity=None):
        capacity=stock.compressBound(len(data)) if capacity is None else capacity
        dest=ctypes.create_string_buffer(max(capacity,1));length=ctypes.c_ulong(capacity)
        code=handle.compress2(dest,ctypes.byref(length),data,len(data),level)
        return code,length.value,dest.raw[:length.value]

    rng=np.random.default_rng(4372452)
    fixtures=[b'',b'a',b'\x00'*4096,bytes(range(256))*256,rng.bytes(65536),rng.bytes(6*1024*1024)]
    for n in [1,2,3,7,31,32,127,128,1023,1024,65535]:fixtures.append(rng.bytes(n))
    reference=Path(os.environ['WRF_CPU_ARTIFACTS'])/'scaled-golden/conus12/full'
    path=args.input or next(reference.glob('wrfout_d01_*'))
    real=[]
    with netCDF4.Dataset(path) as dataset:
        dataset.set_auto_mask(False)
        for name in ['T','P','U','QRAIN']:
            variable=dataset[name];chunk=variable.chunking()
            raw=np.ascontiguousarray(variable[0,:chunk[1],:chunk[2],:chunk[3]],dtype='<f4').tobytes()
            shuffled=np.frombuffer(raw,dtype='u1').reshape(-1,4).T.copy().tobytes()
            fixtures.append(shuffled);real.append((name,shuffled))
    checks=0
    before_hashes=[hashlib.sha256(data).hexdigest() for data in fixtures]
    for data in fixtures:
        for level in [-1,0,1,2,6,9]:
            result=compress(lib,data,level)
            if result[0]!=0 or zlib.decompress(result[2])!=data:raise RuntimeError('decoded bytes differ')
            checks+=1
        for capacity in [0,1,5]:
            result=compress(lib,data,2,capacity);original=compress(stock,data,2,capacity)
            if result[0]!=original[0]:raise RuntimeError('buffer failure status differs')
            if result[0]==0 and zlib.decompress(result[2])!=data:raise RuntimeError('small-buffer bytes differ')
            checks+=1
        for level in [-2,10]:
            if compress(lib,data,level)[0]!=compress(stock,data,level)[0]:raise RuntimeError('invalid-level status differs')
            checks+=1

    def parallel(data):
        for _ in range(3):
            code,_,encoded=compress(lib,data)
            if code or zlib.decompress(encoded)!=data:raise RuntimeError('concurrent bytes differ')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(parallel,[data for _,data in real]))
    core=min(os.sched_getaffinity(0));os.sched_setaffinity(0,{core})
    measurements=[]
    for repeat in range(3):
        order=[('stock',stock),(args.backend_name,lib)]
        if repeat%2:order.reverse()
        for name,data in real:
            for variant,handle in order:
                start=time.perf_counter()
                for _ in range(3):code,size,encoded=compress(handle,data)
                elapsed=(time.perf_counter()-start)/3
                if code or zlib.decompress(encoded)!=data:raise RuntimeError('timed decoded bytes differ')
                measurements.append({'repeat':repeat+1,'field':name,'variant':variant,'seconds_per_chunk':elapsed,'compressed_bytes':size,'input_bytes':len(data),'input_sha256':hashlib.sha256(data).hexdigest()})
    summary=[]
    for name,_ in real:
        medians={v:statistics.median(r['seconds_per_chunk'] for r in measurements if r['field']==name and r['variant']==v) for v in ['stock',args.backend_name]}
        summary.append({'field':name,'median_seconds':medians,'compression_only_speedup':medians['stock']/medians[args.backend_name]})
    if [hashlib.sha256(data).hexdigest() for data in fixtures]!=before_hashes:raise RuntimeError('input bytes mutated')
    report={'backend':args.backend_name,'input_file':str(path.resolve()),'passed':True,'checks':checks,'concurrent_checks':12,'benchmark_core':core,'measurements':measurements,'summary':summary,'scope':'Compression microbenchmark; not a WRF speedup.'}
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['passed','checks','concurrent_checks','summary']}))


if __name__=='__main__':
    main()
