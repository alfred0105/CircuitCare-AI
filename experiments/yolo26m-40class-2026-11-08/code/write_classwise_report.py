import os
from pathlib import Path
from collections import Counter
import json, time, yaml

ROOT = Path(os.environ.get('CIRCUITCARE_EXPERIMENT_ROOT', Path(__file__).resolve().parents[3]))
DATA = ROOT/'work'/'yolo26-benchmark'/'dataset-40class-pilot'
OUT = ROOT/'outputs'/'yolo26m-40class-experiments'
STATE = OUT/'experiment-state.json'

def get_support():
    y=yaml.safe_load((DATA/'data.yaml').read_text(encoding='utf-8'))
    names=y['names']; boxes=Counter(); images=Counter()
    for f in (DATA/'test'/'labels').glob('*.txt'):
        cs=set()
        for line in f.read_text(encoding='utf-8',errors='ignore').splitlines():
            z=line.split()
            if not z: continue
            try: c=int(z[0])
            except ValueError: continue
            boxes[c]+=1; cs.add(c)
        images.update(cs)
    return names, boxes, images

def metric_by_class(run, names):
    ids=run.get('class_indices',[])
    fields=['precision_by_class','recall_by_class','f1_by_class','map50_by_class','map50_95_by_class']
    arrays=[run.get(k,[]) for k in fields]
    out={}
    for j,c in enumerate(ids):
        name=names[int(c)] if int(c)<len(names) else str(c)
        out[name]={field: (arr[j] if j<len(arr) else None) for field,arr in zip(fields,arrays)}
    return out

def fmt(x): return '—' if x is None else f'{float(x):.3f}'

def build(state):
    names, boxes, images=get_support(); runs=state.get('runs',{})
    complete={k:v for k,v in runs.items() if v.get('status')=='complete' and v.get('test_results')}
    label_metrics={k:metric_by_class(v,names) for k,v in complete.items()}
    baseline=label_metrics.get('resolution_640',{})
    scores={k:v.get('test_results',{}).get('metrics/mAP50-95(B)',0) for k,v in complete.items()}
    best_key=max(scores,key=scores.get) if scores else None
    best=label_metrics.get(best_key,{})
    lines=['# YOLO26m label-level findings','',
      'Metrics are from the held-out 5% test sample (116 images). “AP” below is class mAP50–95. Low scores on rare classes are especially uncertain.', '',
      f"Best overall completed condition by test mAP50–95: **{complete.get(best_key,{}).get('label',best_key)}** ({fmt(scores.get(best_key))}).", '']
    # Ranking at the best condition.
    ranked=sorted(((name,m.get('map50_95_by_class'),m.get('recall_by_class')) for name,m in best.items()),key=lambda x: (x[1] is not None, -(x[1] or 0)))
    weak=[x for x in ranked if x[1] is None or x[1] < .10]
    lines += ['## Labels with low AP or missed detections','',
      '| Label | P | R | AP50 | AP50–95 | Test images | Test boxes |','|---|---:|---:|---:|---:|---:|---:|']
    for name,ap,rec in weak:
        m=best[name]
        cid=names.index(name)
        lines.append(f"| {name} | {fmt(m['precision_by_class'])} | {fmt(rec)} | {fmt(m['map50_by_class'])} | {fmt(ap)} | {images[cid]} | {boxes[cid]} |")
    if not weak: lines.append('| None below AP 0.10 | | | | | | |')
    lines += ['', '## Change from baseline 640','',
      'Largest class-level AP changes by condition; negative values identify labels whose AP fell versus baseline.', '']
    for key, metrics in label_metrics.items():
        if key=='resolution_640': continue
        deltas=[]
        for name,m in metrics.items():
            a=baseline.get(name,{}).get('map50_95_by_class')
            b=m.get('map50_95_by_class')
            if a is not None and b is not None: deltas.append((name,b-a,a,b))
        if not deltas: continue
        label=complete[key].get('label',key)
        lines += [f'### {label}','', '| Largest drops | ΔAP | Base → condition | Support images / boxes |','|---|---:|---:|---:|']
        for name,d,a,b in sorted(deltas,key=lambda z:z[1])[:5]:
            cid=names.index(name)
            lines.append(f'| {name} | {d:+.3f} | {a:.3f} → {b:.3f} | {images[cid]} / {boxes[cid]} |')
        lines += ['', '| Largest gains | ΔAP | Base → condition | Support images / boxes |','|---|---:|---:|---:|']
        for name,d,a,b in sorted(deltas,key=lambda z:z[1],reverse=True)[:5]:
            cid=names.index(name)
            lines.append(f'| {name} | {d:+.3f} | {a:.3f} → {b:.3f} | {images[cid]} / {boxes[cid]} |')
        lines.append('')
    lines += ['## Test support and interpretation','',
      '- `solder_joint` has only one image in this test subset, matching the one test image in the full source; its score cannot support a reliable conclusion.',
      '- Classes with fewer than 10 test images are listed with their support counts; treat their per-class scores as exploratory.',
      '- No predictions for a class appear as zero precision/recall/AP in the metric export; missing class metrics are marked with an em dash.', '']
    (OUT/'classwise-findings.md').write_text('\n'.join(lines),encoding='utf-8')

def main():
    while True:
        try:
            state=json.loads(STATE.read_text(encoding='utf-8'))
            if state.get('finished_at'):
                build(state)
                print('Classwise report written:',OUT/'classwise-findings.md',flush=True)
                return
        except Exception as e: print('Waiting for final metrics:',repr(e),flush=True)
        time.sleep(30)

if __name__=='__main__': main()

