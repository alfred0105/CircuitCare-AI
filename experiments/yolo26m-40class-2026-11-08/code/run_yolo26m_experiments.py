from pathlib import Path
from collections import defaultdict
import csv, json, math, os, shutil, time, gc, yaml
import numpy as np
import torch
from ultralytics import YOLO

ROOT = Path(os.environ.get('CIRCUITCARE_EXPERIMENT_ROOT', Path(__file__).resolve().parents[3]))
BASE = ROOT / 'work' / 'yolo26-benchmark'
DATA = BASE / 'dataset-40class-pilot'
DATA_YAML = DATA / 'data.yaml'
MODEL_PATH = ROOT / 'yolo26m.pt'
OUT = ROOT / 'outputs' / 'yolo26m-40class-experiments'
RUNS = BASE / 'runs-40class-experiments-m'
OUT.mkdir(parents=True, exist_ok=True); RUNS.mkdir(parents=True, exist_ok=True)
started = time.monotonic()
manifest = json.loads((DATA/'sample-manifest.json').read_text(encoding='utf-8'))
SAMPLE_COUNTS = {k:v['selected_images'] for k,v in manifest['splits'].items()}
EPOCHS = 10

def hardlink(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try: os.link(src, dst)
    except OSError: shutil.copy2(src, dst)

def oversampled_yaml():
    dest = DATA / 'train_os'
    if dest.exists(): shutil.rmtree(dest)
    image_classes = {}
    freq = defaultdict(int)
    labels = DATA / 'train' / 'labels'
    for lab in labels.glob('*.txt'):
        cs = set()
        for line in lab.read_text(encoding='utf-8', errors='ignore').splitlines():
            parts = line.split()
            if parts:
                try: cs.add(int(parts[0]))
                except ValueError: pass
        image_classes[lab.stem] = cs
        for c in cs: freq[c] += 1
    scores = {stem: sum(1/math.sqrt(freq[c]) for c in cs)/len(cs) for stem,cs in image_classes.items() if cs}
    median = sorted(scores.values())[len(scores)//2]
    extra = 0
    src_img = DATA/'train'/'images'; src_lab = DATA/'train'/'labels'
    for img in src_img.iterdir():
        if not img.is_file(): continue
        lab = src_lab/(img.stem+'.txt')
        if not lab.exists(): continue
        hardlink(img, dest/'images'/img.name); hardlink(lab, dest/'labels'/lab.name)
        factor = max(1, min(3, int(round(scores.get(img.stem, median)/median))))
        for j in range(1,factor):
            hardlink(img, dest/'images'/f'{img.stem}__os{j}{img.suffix}')
            hardlink(lab, dest/'labels'/f'{img.stem}__os{j}.txt')
            extra += 1
    cfg = yaml.safe_load(DATA_YAML.read_text(encoding='utf-8'))
    cfg['train'] = 'train_os/images'
    p = BASE/'data-40class-pilot-oversampled.yaml'
    p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding='utf-8')
    return p, extra

def vec(x):
    if hasattr(x, 'detach'): x = x.detach().cpu().numpy()
    try: return np.asarray(x).reshape(-1).astype(float).tolist()
    except Exception: return []

def scalar_results(metrics):
    out = {}
    for k,v in metrics.results_dict.items():
        try: out[k] = float(v)
        except (TypeError, ValueError): pass
    return out

def class_metrics(metrics):
    b = metrics.box
    return {'precision_by_class':vec(b.p), 'recall_by_class':vec(b.r), 'f1_by_class':vec(b.f1),
            'map50_by_class':vec(b.ap50), 'map50_95_by_class':vec(b.ap),
            'class_indices':[int(x) for x in vec(b.ap_class_index)], 'class_names':metrics.names}

def write_outputs(state):
    (OUT/'experiment-state.json').write_text(json.dumps(state,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    runs=state['runs']; order=['resolution_640','resolution_960','resolution_1280','cls_pw_0_5','pcb_augmentation','multi_scale_25','rare_class_oversampling','inference_tta','inference_tiling']
    cols=['experiment','status','imgsz','epochs','batch','precision','recall','map50','map50_95','seconds','notes']
    with (OUT/'comparison.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for key in order:
            r=runs.get(key,{}); m=r.get('test_results',{})
            w.writerow({'experiment':r.get('label',key),'status':r.get('status','pending'),'imgsz':r.get('imgsz'),
                'epochs':r.get('epochs_completed',r.get('epochs_requested')),'batch':r.get('actual_batch'),
                'precision':m.get('metrics/precision(B)'),'recall':m.get('metrics/recall(B)'),
                'map50':m.get('metrics/mAP50(B)'),'map50_95':m.get('metrics/mAP50-95(B)'),
                'seconds':r.get('elapsed_seconds'),'notes':r.get('error','')})
    lines=['# YOLO26m 40-class quick pilot','',
      'This is a reduced-data comparison: a class-covering 5% train sample, 5% validation/test samples, and 10 training epochs per condition. Treat metrics as directional because the train sample is intentionally capped.','',
      '| Condition | Status | imgsz | epochs | batch | Test P | Test R | Test mAP50 | Test mAP50-95 | seconds |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key in order:
        r=runs.get(key,{}); m=r.get('test_results',{})
        def f(v): return '' if v is None else (f'{v:.4f}' if isinstance(v,(int,float)) else str(v))
        lines.append('| '+' | '.join([str(r.get('label',key)),str(r.get('status','pending')),f(r.get('imgsz')),
          f(r.get('epochs_completed',r.get('epochs_requested'))),f(r.get('actual_batch')),
          f(m.get('metrics/precision(B)')),f(m.get('metrics/recall(B)')),f(m.get('metrics/mAP50(B)')),
          f(m.get('metrics/mAP50-95(B)')),f(r.get('elapsed_seconds'))])+' |')
        if r.get('error'): lines.append(f"\n{r.get('label',key)} error: `{r['error']}`\n")
    lines += ['', '## Sampling and limits','',
      f"- Train: {SAMPLE_COUNTS.get('train')} of 18,418 images (5%); validation: {SAMPLE_COUNTS.get('valid')} of 2,302 (5%); test: {SAMPLE_COUNTS.get('test')} of 2,303 (5%).",
      '- Subsets are deterministic and selected to cover every class present in each split. No image crosses splits.',
      '- Same pretrained YOLO26l initialization, fixed sample, seed 42, one epoch, CUDA, AMP and automatic batch sizing.',
      '- `solder_joint` has one train image and one test image in the full source, so its pilot metric is not reliable.', '']
    (OUT/'comparison.md').write_text('\n'.join(lines),encoding='utf-8')
    with (OUT/'classwise-test-metrics.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f); w.writerow(['experiment','class','precision','recall','f1','map50','map50_95'])
        for key in order:
            r=runs.get(key,{})
            names=r.get('class_names',{}); idxs=r.get('class_indices',[])
            arrays=[r.get(k,[]) for k in ['precision_by_class','recall_by_class','f1_by_class','map50_by_class','map50_95_by_class']]
            for j,idx in enumerate(idxs):
                name=names.get(idx,names.get(str(idx),str(idx))) if isinstance(names,dict) else str(idx)
                w.writerow([r.get('label',key),name,*[a[j] if j<len(a) else '' for a in arrays]])

if not torch.cuda.is_available(): raise RuntimeError('CUDA is required for this short GPU pilot')
oversampled_data, oversampled_extra = oversampled_yaml()
state={'configuration':{'model':str(MODEL_PATH),'epochs':EPOCHS,'seed':42,'device':torch.cuda.get_device_name(0),
        'target_minutes_per_640_condition':15,'train_images':SAMPLE_COUNTS['train'],'valid_images':SAMPLE_COUNTS['valid'],'test_images':SAMPLE_COUNTS['test'],'oversampled_extra_images':oversampled_extra},'runs':{}}
experiments=[
 ('resolution_640','640 baseline',640,DATA_YAML,{}),
 ('resolution_960','960 baseline',960,DATA_YAML,{}),
 ('resolution_1280','1280 baseline',1280,DATA_YAML,{}),
 ('cls_pw_0_5','cls_pw=0.5',640,DATA_YAML,{'cls_pw':0.5}),
 ('pcb_augmentation','PCB augmentation',640,DATA_YAML,{'hsv_h':0.01,'hsv_s':0.25,'hsv_v':0.30,'degrees':180.0,'translate':0.05,'scale':0.15,'flipud':0.5,'fliplr':0.5,'mosaic':0.5,'mixup':0.0,'copy_paste':0.0}),
 ('multi_scale_25','Extra: multi-scale ±25%',640,DATA_YAML,{'multi_scale':0.25}),
 ('rare_class_oversampling',f'Extra: rare-class oversampling (+{oversampled_extra} repeats)',640,oversampled_data,{}),
]
common=dict(epochs=EPOCHS,patience=EPOCHS,batch=-1,device=0,workers=0,amp=True,cache=False,seed=42,deterministic=True,
   project=str(RUNS),exist_ok=True,verbose=False,plots=False,save=True,val=True,close_mosaic=0,conf=0.001,iou=0.7,max_det=300)
for key,label,imgsz,data,args in experiments:
    t=time.monotonic(); rec={'label':label,'status':'running','imgsz':imgsz,'epochs_requested':EPOCHS,'args':args}; state['runs'][key]=rec; write_outputs(state)
    try:
        model=YOLO(str(MODEL_PATH))
        tr=model.train(data=str(data),imgsz=imgsz,name=key,**common,**args)
        best=Path(tr.save_dir)/'weights'/'best.pt'
        if not best.exists(): raise FileNotFoundError(best)
        m=YOLO(str(best)).val(data=str(DATA_YAML),split='test',imgsz=imgsz,batch=1,device=0,workers=0,plots=False,
               conf=0.001,iou=0.7,max_det=300,project=str(RUNS),name=key+'-test',exist_ok=True)
        rec.update({'status':'complete','best_weights':str(best),'test_results':scalar_results(m),**class_metrics(m),
               'actual_batch':getattr(getattr(model,'trainer',None),'batch_size',None),'epochs_completed':EPOCHS,
               'elapsed_seconds':round(time.monotonic()-t,1)})
        print('DONE',key,rec['test_results'],flush=True)
        del m,model; gc.collect(); torch.cuda.empty_cache()
    except BaseException as e:
        rec.update({'status':'failed','error':repr(e),'elapsed_seconds':round(time.monotonic()-t,1)})
        print('FAILED',key,repr(e),flush=True)
        gc.collect(); torch.cuda.empty_cache()
    write_outputs(state)

# Compare TTA and native tiled inference against the trained 640 checkpoint, using the same small test subset.
base=state['runs'].get('resolution_640',{})
if base.get('status')=='complete':
    for key,label,opts in [('inference_tta','640 + test-time augmentation',{'augment':True}),
                           ('inference_tiling','640 + tiled inference',{'tile':True})]:
        t=time.monotonic(); rec={'label':label,'status':'running','imgsz':640};state['runs'][key]=rec;write_outputs(state)
        try:
            model=YOLO(base['best_weights'])
            m=model.val(data=str(DATA_YAML),split='test',imgsz=640,batch=1,device=0,workers=0,plots=False,
                 conf=0.001,iou=0.7,max_det=300,project=str(RUNS),name=key,exist_ok=True,**opts)
            rec.update({'status':'complete','test_results':scalar_results(m),**class_metrics(m),'elapsed_seconds':round(time.monotonic()-t,1)})
            del m,model;gc.collect();torch.cuda.empty_cache()
        except BaseException as e: rec.update({'status':'failed','error':repr(e),'elapsed_seconds':round(time.monotonic()-t,1)})
        write_outputs(state)
state['elapsed_total_seconds']=round(time.monotonic()-started,1)
state['finished_at']=time.strftime('%Y-%m-%d %H:%M:%S')
write_outputs(state)
print('PILOT_FINISHED',state['elapsed_total_seconds'],OUT,flush=True)

