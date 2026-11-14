"""Configure a small isolated fine-tuning run without changing pretrained files."""
import argparse,copy,json
from pathlib import Path
import yaml

def main():
 p=argparse.ArgumentParser();p.add_argument('--upstream',type=Path,required=True);p.add_argument('--data',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--epochs',type=int,default=2);p.add_argument('--batch',type=int,default=4);a=p.parse_args()
 base=a.upstream/'configs/rec/PP-OCRv5/PP-OCRv5_mobile_rec.yml';config=yaml.safe_load(base.read_text());data=a.data.resolve();output=a.output.resolve()
 config['Global'].update(epoch_num=a.epochs,save_model_dir=str(output),pretrained_model=str(a.checkpoint.resolve()),checkpoints=None,save_epoch_step=1,eval_batch_step=[0,400],print_batch_step=25,distributed=False,use_visualdl=False,use_amp=True,amp_level='O1',scale_loss=1024,character_dict_path=str((a.upstream/'ppocr/utils/dict/ppocrv5_dict.txt').resolve()),seed=20261105)
 config['Optimizer']['lr'].update(learning_rate=1e-5,warmup_epoch=0)
 transforms=[{'DecodeImage':{'img_mode':'BGR','channel_first':False}},{'MultiLabelEncode':{'gtc_encode':'NRTRLabelEncode'}},{'RecResizeImg':{'image_shape':[3,48,320]}},{'KeepKeys':{'keep_keys':['image','label_ctc','label_gtc','length','valid_ratio']}}]
 for phase,split in [('Train','train'),('Eval','val')]:
  config[phase]={'dataset':{'name':'SimpleDataSet','data_dir':str(data),'label_file_list':[str(data/(split+'.txt'))],'transforms':copy.deepcopy(transforms)},'loader':{'shuffle':phase=='Train','drop_last':phase=='Train','batch_size_per_card':a.batch,'num_workers':0}}
 output.parent.mkdir(parents=True,exist_ok=True);path=output.parent/(output.name+'.yml');path.write_text(yaml.safe_dump(config,sort_keys=False));print(path)
if __name__=='__main__':main()
