import os
from pathlib import Path
from collections import defaultdict
import csv, json, time, yaml, gc
import numpy as np
from PIL import Image
from ultralytics import YOLO
import torch

ROOT=Path(os.environ.get('CIRCUITCARE_EXPERIMENT_ROOT', Path(__file__).resolve().parents[3]))
DATA=ROOT/'work'/'yolo26-benchmark'/'dataset-40class-pilot'
OUT=ROOT/'outputs'/'yolo26m-40class-experiments'
STATE=json.loads((OUT/'experiment-state.json').read_text(encoding='utf-8'))
YAML=yaml.safe_load((DATA/'data.yaml').read_text(encoding='utf-8'))
NAMES=YAML['names']
CONF=0.25; IOU=0.50; MAX_DET=300

def gt_for_image(imgpath):
    w,h=Image.open(imgpath).size
    labels=DATA/'test'/'labels'/(imgpath.stem+'.txt')
    boxes=[]; classes=[]
    for line in labels.read_text(encoding='utf-8',errors='ignore').splitlines():
        q=line.split()
        if len(q)<5: continue
        try: c=int(q[0]); x,y,bw,bh=map(float,q[1:5])
        except ValueError: continue
        boxes.append([(x-bw/2)*w,(y-bh/2)*h,(x+bw/2)*w,(y+bh/2)*h]); classes.append(c)
    return np.asarray(boxes,dtype=float).reshape(-1,4),np.asarray(classes,dtype=int)

def iou_matrix(a,b):
    if len(a)==0 or len(b)==0: return np.zeros((len(a),len(b)),dtype=float)
    lt=np.maximum(a[:,None,:2],b[None,:,:2]); rb=np.minimum(a[:,None,2:],b[None,:,2:])
    wh=np.maximum(0,rb-lt); inter=wh[:,:,0]*wh[:,:,1]
    aa=np.maximum(0,a[:,2]-a[:,0])*np.maximum(0,a[:,3]-a[:,1])
    bb=np.maximum(0,b[:,2]-b[:,0])*np.maximum(0,b[:,3]-b[:,1])
    return inter/np.maximum(aa[:,None]+bb[None,:]-inter,1e-9)

def match(gtb,gtc,pb,pc,pconf):
    order=np.argsort(-pconf); used=set(); tp=0; fp=0
    mat=iou_matrix(pb,gtb)
    for pi in order:
        candidates=[gi for gi,c in enumerate(gtc) if int(c)==int(pc[pi]) and gi not in used]
        if candidates:
            gi=max(candidates,key=lambda x:mat[pi,x])
            if mat[pi,gi]>=IOU:
                tp+=1;used.add(gi);continue
        fp+=1
    fn=len(gtb)-tp
    precision=tp/(tp+fp) if tp+fp else 0.0
    recall=tp/(tp+fn) if tp+fn else 0.0
    f1=2*precision*recall/(precision+recall) if precision+recall else 0.0
    strict=int(fp==0 and fn==0)
    return tp,fp,fn,precision,recall,f1,strict

images=sorted(p for p in (DATA/'test'/'images').iterdir() if p.is_file())
conditions=[
 ('resolution_640','640 baseline',640,{},'best_weights'),
 ('resolution_960','960 baseline',960,{},'best_weights'),
 ('resolution_1280','1280 baseline',1280,{},'best_weights'),
 ('cls_pw_0_5','cls_pw=0.5',640,{},'best_weights'),
 ('pcb_augmentation','PCB augmentation',640,{},'best_weights'),
 ('multi_scale_25','Multi-scale ±25%',640,{},'best_weights'),
 ('rare_class_oversampling','Rare-class oversampling',640,{},'best_weights'),
 ('inference_tta','640 + TTA',640,{'augment':True},'base_weights'),
 ('inference_tiling','640 + tiled inference',640,{'tile':True},'base_weights')]
all_rows=[]; summary=[]

def write_partial():
    if all_rows:
        with (OUT/'per-image-detection-results.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(all_rows[0]));w.writeheader();w.writerows(all_rows)
    if summary:
        with (OUT/'all-sample-accuracy.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(summary[0]));w.writeheader();w.writerows(summary)

for key,label,imgsz,opts,weightkey in conditions:
    r=STATE['runs'].get(key,{})
    if r.get('status')!='complete': continue
    weights=r.get(weightkey)
    if not weights or not Path(weights).exists():
        if key.startswith('inference_'): weights=STATE['runs'].get('resolution_640',{}).get('best_weights')
    if not weights or not Path(weights).exists(): continue
    print('PREDICT',label,flush=True)
    gc.collect(); torch.cuda.empty_cache()
    model=YOLO(weights)
    # Use CPU for this small report-only pass to avoid high-resolution checkpoints exhausting VRAM.
    preds=model.predict(source=[str(p) for p in images],imgsz=imgsz,batch=1,device='cpu',workers=0,
        conf=CONF,iou=0.7,max_det=MAX_DET,verbose=False,save=False,**opts)
    totals=[0,0,0]; exact=0; per_f1=[]
    for im,res in zip(images,preds):
        gtb,gtc=gt_for_image(im)
        if res.boxes is None:
            pb=np.zeros((0,4));pc=np.zeros((0,),dtype=int);pconf=np.zeros((0,))
        else:
            pb=res.boxes.xyxy.detach().cpu().numpy()
            pc=res.boxes.cls.detach().cpu().numpy().astype(int)
            pconf=res.boxes.conf.detach().cpu().numpy()
        tp,fp,fn,p,rr,f1,strict=match(gtb,gtc,pb,pc,pconf)
        totals[0]+=tp;totals[1]+=fp;totals[2]+=fn;exact+=strict;per_f1.append(f1)
        all_rows.append({'condition':label,'image':im.name,'gt_boxes':len(gtb),'pred_boxes':len(pb),
            'tp':tp,'fp':fp,'fn':fn,'precision':p,'recall':rr,'f1':f1,'strict_exact_match':strict})
    tp,fp,fn=totals
    summary.append({'condition':label,'images':len(images),'confidence':CONF,'iou_threshold':IOU,'max_det':MAX_DET,
      'exact_match_images':exact,'exact_image_accuracy':exact/len(images) if images else 0,
      'tp':tp,'fp':fp,'fn':fn,'micro_precision':tp/(tp+fp) if tp+fp else 0,
      'micro_recall':tp/(tp+fn) if tp+fn else 0,
      'micro_f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,
      'mean_image_f1':float(np.mean(per_f1)) if per_f1 else 0})
    write_partial()
    del preds,model,res,im
    gc.collect(); torch.cuda.empty_cache()

write_partial()
lines=['# All-sample correctness by condition','',
 f'Test sample: {len(images)} images. “Exact-image accuracy” requires every labeled box to match the class at IoU ≥ {IOU:.2f}, confidence ≥ {CONF:.2f}, with no extra detections. This is intentionally strict; detection has no ordinary classification accuracy.', '',
 '| Condition | Exact images | Exact-image accuracy | Micro P | Micro R | Micro F1 | Mean image F1 | TP / FP / FN |',
 '|---|---:|---:|---:|---:|---:|---:|---:|']
for s in summary:
    lines.append(f"| {s['condition']} | {s['exact_match_images']}/{s['images']} | {s['exact_image_accuracy']:.1%} | {s['micro_precision']:.3f} | {s['micro_recall']:.3f} | {s['micro_f1']:.3f} | {s['mean_image_f1']:.3f} | {s['tp']} / {s['fp']} / {s['fn']} |")
lines += ['',f'Matching rule: greedy one-to-one class match with IoU ≥ {IOU:.2f}; predictions below confidence {CONF:.2f} are ignored; max detections per image = {MAX_DET}.',
 'The exact-image rate is not directly comparable to mAP because it uses one confidence threshold and requires every object in an image to be correct. See the per-image CSV for all sample-level TP/FP/FN.', '']
(OUT/'all-sample-accuracy.md').write_text('\n'.join(lines),encoding='utf-8')
print('WROTE',OUT/'all-sample-accuracy.md','conditions',len(summary),'images',len(images),flush=True)


