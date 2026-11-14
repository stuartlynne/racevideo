"""Diagnostic copy: trained weights with original BatchNorm running statistics."""
import argparse,json,hashlib
from pathlib import Path
import paddle

def main():
 p=argparse.ArgumentParser();p.add_argument('--pretrained',type=Path,required=True);p.add_argument('--tuned',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists():raise FileExistsError(a.output)
 paddle.set_device('cpu');original=paddle.load(str(a.pretrained));tuned=paddle.load(str(a.tuned));keys=[]
 for key in tuned:
  if key.endswith(('._mean','._variance')):
   if key not in original or tuned[key].shape!=original[key].shape:raise ValueError(key)
   tuned[key]=original[key];keys.append(key)
 if not keys:raise RuntimeError('No normalization statistics found')
 paddle.save(tuned,str(a.output));meta=dict(pretrained=str(a.pretrained),tuned=str(a.tuned),pretrained_sha256=hashlib.sha256(a.pretrained.read_bytes()).hexdigest(),tuned_sha256=hashlib.sha256(a.tuned.read_bytes()).hexdigest(),restored_keys=keys,output_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest())
 a.output.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n');print('Restored',len(keys),'BatchNorm running-statistic tensors; other tuned weights retained')
if __name__=='__main__':main()
