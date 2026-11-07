#!/usr/bin/env python3
"""Configure on login, build on compute, preserve each candidate executable."""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import traceback

import run
import verify

COMPONENTS=['phys/physics_mmm','phys/noahmp','phys/MYNN-EDMF']


def git(repo,*args):
    return subprocess.check_output(['git','-C',str(repo),*args])


def source_state():
    result={}
    for component in ['.',*COMPONENTS]:
        repo=run.ROOT/component
        paths=git(repo,'ls-files','--cached','--others','--exclude-standard','-z').decode().split('\0')
        hashes={}
        for name in sorted(set(paths)):
            if not name:
                continue
            parts=Path(name).parts
            if component=='.' and (parts[0]=='perf' or parts[0].startswith('.') or name in ('AGENT.md','AGENTS.md')):
                continue
            path=repo/name
            if path.is_file():
                hashes[name]=run.digest(path)
        result[component]={'commit':git(repo,'rev-parse','HEAD').decode().strip(),'files':hashes}
    return result


def archive_sources(directory):
    for component in ['.',*COMPONENTS]:
        repo=run.ROOT/component
        name='wrf' if component=='.' else Path(component).name
        with (directory/(name+'.tar')).open('wb') as stream:
            subprocess.run(['git','-C',str(repo),'archive','HEAD'],stdout=stream,check=True)
        (directory/(name+'.patch')).write_bytes(git(repo,'diff','--binary','HEAD'))
        for relative in git(repo,'ls-files','--others','--exclude-standard','-z').decode().split('\0'):
            if not relative:
                continue
            parts=Path(relative).parts
            if component=='.' and (parts[0]=='perf' or parts[0].startswith('.')):
                continue
            path=repo/relative
            if path.is_file():
                target=directory/'untracked'/name/relative
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,target)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['configure','build'])
    parser.add_argument('--variant',required=True,help='stable incremental-build cache key; flags cannot change under this key')
    parser.add_argument('--label',required=True,help='unique recorded build experiment; output executable never overwritten')
    parser.add_argument('--extra-fcflags',help='append to original GNU Fortran options; build inherits the configured value if omitted')
    parser.add_argument('--pnetcdf-prefix', type=Path, help='explicit separate parallel I/O dependency; build inherits its locked prefix')
    parser.add_argument('--netcdf-prefix', type=Path, help='isolated netCDF/HDF5 dependency; build inherits its locked prefix')
    parser.add_argument('--openmp',action='store_true',default=None,help='enable the separate hybrid build; build inherits the configured setting')
    args=parser.parse_args()
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+',value) for value in (args.variant,args.label)):
        parser.error('variant and label must be safe names')
    if git(run.ROOT,'branch','--show-current').decode().strip()!='perf/wrf-cpu':
        raise RuntimeError('branch must remain perf/wrf-cpu')
    if args.mode=='build' and not os.environ.get('SLURM_JOB_ID'):
        parser.error('build on a Slurm compute allocation')
    cache=run.ART/'variant-cache'/args.variant
    cache.mkdir(parents=True,exist_ok=True)
    record=run.ART/'experiments'/args.label/'build'
    payload=run.ART/'candidates'/args.label/'bin/wrf'
    if args.extra_fcflags is None:
        args.extra_fcflags=json.loads((record/'build.json').read_text())['options']['extra_fcflags'] if args.mode=='build' else ''
    if args.openmp is None:
        args.openmp=json.loads((record/'build.json').read_text())['options'].get('use_openmp',False) if args.mode=='build' else False
    if args.pnetcdf_prefix is None and args.mode=='build':
        configured=json.loads((record/'build.json').read_text())['options']
        if configured.get('pnetcdf'):
            args.pnetcdf_prefix=Path(configured['pnetcdf']['prefix'])
    if args.netcdf_prefix is None and args.mode=='build':
        configured=json.loads((record/'build.json').read_text())['options']
        if configured.get('netcdf_dependency'):
            args.netcdf_prefix=Path(configured['netcdf_dependency']['prefix'])
    dependency_prefix=args.netcdf_prefix.resolve() if args.netcdf_prefix is not None else Path(os.environ['NETCDF'])
    build_environment=dict(os.environ)
    if args.netcdf_prefix is not None:
        build_environment.update(NETCDF=str(dependency_prefix),
            PATH=str(dependency_prefix/'bin')+os.pathsep+os.environ['PATH'],
            LD_LIBRARY_PATH=str(dependency_prefix/'lib')+os.pathsep+os.environ.get('LD_LIBRARY_PATH',''))
    options={'extra_fcflags':args.extra_fcflags,'netcdf':str(dependency_prefix),
             'toolchains':{name:run.digest(Path(__file__).with_name(name)) for name in ('gnu.cmake','variant.cmake')},
             'compiler':subprocess.check_output(['gfortran','--version'],text=True),
             'mpi':subprocess.check_output(['mpirun','--version'],text=True)}
    if args.openmp:
        options['use_openmp']=True
    if args.netcdf_prefix is not None:
        required=[dependency_prefix/'bin'/name for name in ('nc-config','nf-config')]
        required.extend(dependency_prefix/'include'/name for name in ('netcdf.h','netcdf.inc','netcdf.mod','H5public.h'))
        if not all(path.is_file() for path in required):
            raise RuntimeError('isolated netCDF/HDF5 prefix is not installed completely')
        files={path.resolve() for path in required}
        files.update(path.resolve() for path in (dependency_prefix/'include').glob('*.mod'))
        for library in ('libnetcdf','libnetcdff','libhdf5','libhdf5_hl'):
            matches=[path for path in (dependency_prefix/'lib').glob(library+'.*') if path.is_file()]
            if not matches:
                raise RuntimeError('isolated dependency library missing: '+library)
            files.update(path.resolve() for path in matches)
        options['netcdf_dependency']={'prefix':str(dependency_prefix),
            'files_sha256':{str(path):run.digest(path) for path in sorted(files)},
            'nc_config':subprocess.check_output([str(required[0]),'--all'],env=build_environment,text=True),
            'nf_config':subprocess.check_output([str(required[1]),'--all'],env=build_environment,text=True)}
    if args.pnetcdf_prefix is not None:
        prefix=args.pnetcdf_prefix.resolve()
        config=prefix/'bin/pnetcdf-config'
        required=[config,prefix/'include/pnetcdf.h',prefix/'include/pnetcdf.inc']
        if not all(path.is_file() for path in required):
            raise RuntimeError('parallel I/O prefix is not installed completely')
        files=set(path.resolve() for path in required)
        files.update(path.resolve() for path in (prefix/'include').glob('*.mod'))
        libraries=[path for path in (prefix/'lib').glob('libpnetcdf.*') if path.is_file()]
        if not libraries:
            raise RuntimeError('parallel I/O library missing from prefix')
        files.update(path.resolve() for path in libraries)
        options['pnetcdf']={'prefix':str(prefix),'files_sha256':{str(path):run.digest(path) for path in sorted(files)},
                            'version':subprocess.check_output([str(config),'--version'],text=True).strip()}
    with (cache/'build.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        cache_config=cache/'options.json'
        if cache_config.exists() and json.loads(cache_config.read_text())!=options:
            raise RuntimeError('variant cache options changed; use a new variant key')
        if payload.exists():
            raise RuntimeError('candidate executable already exists; use a new experiment label')
        if args.mode=='configure':
            record.mkdir(parents=True,exist_ok=False)
            meta={'label':args.label,'variant':args.variant,'status':'configuring','options':options,
                  'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'source':source_state()}
            verify.save(record/'build.json',meta)
            archive_sources(record)
            harness=record/'harness'; harness.mkdir()
            for path in Path(__file__).parent.iterdir():
                if path.is_file():
                    shutil.copy2(path,harness/path.name)
        else:
            meta=json.loads((record/'build.json').read_text())
            if meta['status']!='configured' or meta['options']!=options or meta['source']!=source_state():
                raise RuntimeError('configured source/options changed or prior build failed; preserve evidence and reconfigure with a new label')
            meta.update(status='building',job_id=os.environ['SLURM_JOB_ID'],host=os.uname().nodename,
                        cpu=json.loads(subprocess.check_output(['lscpu','-J'],text=True)))
        verify.save(record/'build.json',meta)
        try:
            if args.mode=='configure':
                command=['cmake','-S',str(run.ROOT),'-B',str(cache/'build'),'-G','Ninja',
                    '-DCMAKE_TOOLCHAIN_FILE='+str(Path(__file__).with_name('variant.cmake')),
                    '-DWRF_EXTRA_FCFLAGS:STRING='+args.extra_fcflags,
                    '-DCMAKE_INSTALL_PREFIX='+str(cache/'install'),'-DCMAKE_PREFIX_PATH='+str(dependency_prefix),
                    '-DnetCDF_ROOT='+str(dependency_prefix),'-DnetCDF-Fortran_ROOT='+str(dependency_prefix),
                    '-DCMAKE_C_COMPILER_LAUNCHER=ccache','-DWRF_CORE=ARW','-DWRF_NESTING=NONE','-DWRF_CASE=EM_REAL',
                    '-DUSE_MPI=ON','-DUSE_OPENMP='+('ON' if args.openmp else 'OFF'),'-DUSE_DOUBLE=OFF','-DUSE_IPO=OFF','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON']
                if options.get('pnetcdf'):
                    command+=['-DPNETCDF_PROGRAM='+str(Path(options['pnetcdf']['prefix'])/'bin/pnetcdf-config')]
                if options.get('netcdf_dependency'):
                    command+=['-DNETCDF_PROGRAM='+str(dependency_prefix/'bin/nc-config'),
                              '-DNETCDF-FORTRAN_PROGRAM='+str(dependency_prefix/'bin/nf-config')]
            else:
                command=['cmake','--build',str(cache/'build'),'--target','wrf','--parallel',os.environ.get('SLURM_CPUS_PER_TASK','32')]

            meta['last_command']=command
            verify.save(record/'build.json',meta)
            with (record/(args.mode+'.log')).open('w') as stream:
                subprocess.run(command,env=build_environment,stdout=stream,stderr=subprocess.STDOUT,check=True)
            if source_state()!=meta['source']:
                raise RuntimeError('model source changed during configure/build')
            if any(run.digest(Path(__file__).with_name(name))!=sha for name,sha in options['toolchains'].items()):
                raise RuntimeError('toolchain changed during configure/build')
            for dependency in ('pnetcdf','netcdf_dependency'):
                for path,sha in options.get(dependency,{}).get('files_sha256',{}).items():
                    if run.digest(Path(path))!=sha:
                        raise RuntimeError('dependency changed during configure/build: '+path)
            for name in ('CMakeCache.txt','compile_commands.json'):
                shutil.copy2(cache/'build'/name,record/name)
            if args.mode=='configure':
                verify.save(cache_config,options)
                meta['status']='configured'
            else:
                payload.parent.mkdir(parents=True,exist_ok=False)
                shutil.copy2(cache/'build/main/wrf',payload)
                payload.chmod(0o555)
                meta.update(status='completed',executable=str(payload),executable_sha256=run.digest(payload))
        except BaseException:
            meta.update(status='failed',error=traceback.format_exc())
            raise
        finally:
            meta['updated_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
            verify.save(record/'build.json',meta)
    print(json.dumps({'label':args.label,'status':meta['status'],'executable':meta.get('executable')}),flush=True)


if __name__=='__main__':
    main()
