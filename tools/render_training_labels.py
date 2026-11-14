"""Render clean masters through the actual qllabels functions; never calls main.

qllabels imports its printer dependencies, but these pure renderer calls do not
convert printer instructions, open sockets, or change printer configuration.
"""
import argparse,hashlib,importlib,json,sys
from pathlib import Path
from PIL import Image,ImageDraw


def main():
 p=argparse.ArgumentParser();p.add_argument('--qllabels-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--numbers',nargs='+',default=['000','235','469','609','906','999']);a=p.parse_args()
 if any(len(n)!=3 or any(c not in '0123456789' for c in n) for n in a.numbers):p.error('numbers must be three ASCII digits')
 root=a.qllabels_root.resolve();sys.path.insert(0,str(root));ql=importlib.import_module('qllabels.qllabels')
 if Path(ql.__file__).resolve()!=root/'qllabels/qllabels.py':raise RuntimeError('Loaded a different qllabels module')
 a.output.mkdir(parents=True,exist_ok=True);ql.LABEL_DPI=300;manifest=dict(source=str(Path(ql.__file__).resolve()),source_sha256=hashlib.sha256(Path(ql.__file__).read_bytes()).hexdigest(),font=str(ql.DIN_ENG_FONT),font_sha256=hashlib.sha256(ql.DIN_ENG_FONT.read_bytes()).hexdigest(),dpi=300,items=[])
 cards=[]
 for number in a.numbers:
  fields=ql.LabelFields(bib=number,event='RACEVIDEO TEST',participant='TEST RIDER')
  for kind,side,size in [('Frame','left','62x100'),('Frame','right','62x100'),('Body',None,'102x152')]:
   dims=ql.IMAGESIZE_300[size]
   image=ql.render_frame_label(fields,dims,vertical_side=side) if kind=='Frame' else ql.render_body_label(fields,dims)
   name=f'{kind}-{number}-{size}'+(f'-{side}' if side else '')+'.png';image.save(a.output/name)
   manifest['items'].append(dict(number=number,kind=kind,side=side,labelsize=size,size=list(image.size),file=name))
   thumb=image.convert('RGB');thumb.thumbnail((330,230));cards.append((name,thumb))
 (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 sheet=Image.new('RGB',(1080,len(a.numbers)*270),'#202630');draw=ImageDraw.Draw(sheet)
 for i,(name,im) in enumerate(cards):
  x=i%3*360;y=i//3*270;draw.text((x+8,y+5),name,fill='white');sheet.paste(im,(x+8,y+30))
 sheet.save(a.output/'contact-sheet.jpg');print('Rendered',len(cards),'masters without printer operations')
if __name__=='__main__':main()
