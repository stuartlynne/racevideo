"""Fetch the official CPU ReID IR and verify Open Model Zoo SHA384 checksums."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

NAME='person-reidentification-retail-0288'
BASE=f'https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1/{NAME}/FP32/'
HASHES={
    'xml':'25082c8e783ad358396039d6c3969f9d862512de0cd3dd87b23c2e5790fabc64e288336e5d42369fcc4c347be15c19f2',
    'bin':'ffc5956253b60f9fac52189976a2ceba2b69288715b35caeff05238840b6e87dcc314d777b612c54d55d976988d6b9d9'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,default=Path('data/models')/NAME);a=p.parse_args()
    a.directory.mkdir(parents=True,exist_ok=True)
    for suffix,expected in HASHES.items():
        path=a.directory/(NAME+'.'+suffix)
        data=path.read_bytes() if path.exists() else urllib.request.urlopen(BASE+path.name,timeout=60).read()
        if hashlib.sha384(data).hexdigest()!=expected:raise ValueError('Model checksum mismatch: '+path.name)
        if not path.exists():path.write_bytes(data)
    manifest=dict(model=NAME,urls=[BASE+NAME+'.'+suffix for suffix in HASHES],sha384=HASHES,
        documentation='https://github.com/openvinotoolkit/open_model_zoo/tree/master/models/intel/'+NAME,
        license='https://github.com/openvinotoolkit/open_model_zoo/blob/master/LICENSE')
    (a.directory/'source.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Verified model:',a.directory/(NAME+'.xml'))


if __name__=='__main__':main()
