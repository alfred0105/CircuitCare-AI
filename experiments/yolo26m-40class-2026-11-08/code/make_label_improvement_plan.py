import os
from pathlib import Path
from collections import Counter
import csv, yaml

ROOT=Path(os.environ.get('CIRCUITCARE_EXPERIMENT_ROOT', Path(__file__).resolve().parents[3]))
DATA=ROOT/'work'/'yolo26-benchmark'/'dataset-40class-quality'
PILOT=ROOT/'work'/'yolo26-benchmark'/'dataset-40class-pilot'
OUT=ROOT/'outputs'/'yolo26m-40class-experiments'
names=yaml.safe_load((DATA/'data.yaml').read_text(encoding='utf-8'))['names']

train_boxes=Counter();train_images=Counter()
for f in (DATA/'train'/'labels').glob('*.txt'):
    cs=[]
    for line in f.read_text(encoding='utf-8',errors='ignore').splitlines():
        q=line.split()
        if not q:continue
        try: c=int(q[0])
        except ValueError:continue
        train_boxes[c]+=1;cs.append(c)
    train_images.update(set(cs))

test_boxes=Counter();test_images=Counter()
for f in (PILOT/'test'/'labels').glob('*.txt'):
    cs=[]
    for line in f.read_text(encoding='utf-8',errors='ignore').splitlines():
        q=line.split()
        if not q:continue
        try:c=int(q[0])
        except ValueError:continue
        test_boxes[c]+=1;cs.append(c)
    test_images.update(set(cs))

rows=list(csv.DictReader((OUT/'classwise-test-metrics.csv').open(encoding='utf-8-sig')))
best={r['class']:r for r in rows if r['experiment'].startswith('Extra: rare-class oversampling')}
base={r['class']:r for r in rows if r['experiment']=='640 baseline'}

def action(name, ap, nimg, nbox, train_n):
    if name=='text_noncomponent':
        return '주석 정의·박스 밀도 감사: test 3장에 1,376개. 누락보다 과주석/일관성 확인 우선.'
    if nimg<5:
        return '표본 부족: 점수 판단 보류. 서로 다른 보드·촬영 조건의 독립 이미지 추가.'
    if name in {'resistor','battery','capacitor','transistor'} and ap is not None and ap<.15:
        return f'데이터는 이미 많음({train_n:,} train 박스). 무작위 추가 대신 오탐·미탐 사례와 작은/가림 부품 보강.'
    if name in {'pin','solder_pad','test_point','solder_joint','good','exc_solder','spike','no_good','poor_solder'} and (ap is None or ap<.15):
        return '구조/납땜 클래스 보강: 박스 기준을 점검하고 서로 다른 PCB의 독립 표본 추가.'
    if ap is None or ap<.10:
        return '우선 검토: 미탐 이미지의 크기·가림·초점·라벨 경계를 확인하고 hard example 추가.'
    if ap<.25:
        if train_n>5000:
            return '데이터 총량보다 혼동 사례를 우선 보강; 클래스 정의와 박스 경계 점검.'
        return '중간 우선순위: 혼동이 잦은 모양·크기·조명 사례를 보강.'
    return '현재 표본에서는 유지. 대량 추가보다 독립 보드 표본으로 재검증.'

out=[]
for i,name in enumerate(names):
    b=best.get(name,{}); z=base.get(name,{})
    ap=float(b['map50_95']) if b.get('map50_95') not in ('',None) else None
    rec=float(b['recall']) if b.get('recall') not in ('',None) else None
    bap=float(z['map50_95']) if z.get('map50_95') not in ('',None) else None
    delta=ap-bap if ap is not None and bap is not None else None
    out.append({'id':i,'label':name,'train_boxes':train_boxes[i],'train_images':train_images[i],
       'test_images':test_images[i],'test_boxes':test_boxes[i],'precision':float(b['precision']) if b.get('precision') else None,
       'recall':rec,'ap':ap,'delta_ap_vs_640':delta,
       'action':action(name,ap,test_images[i],test_boxes[i],train_boxes[i])})

def fmt(x): return '—' if x is None else f'{x:.3f}'
with (OUT/'label-improvement-plan.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
lines=['# 40개 라벨별 개선 계획','',
 '모델: YOLO26m, 최상위 전체 조건인 희귀 클래스 오버샘플링 기준. train은 5% 표본 921장, test는 5% 표본 116장. AP=class mAP50–95. test 이미지가 적은 라벨의 점수는 결론으로 사용하지 않습니다.','',
 '| 라벨 | 전체 train 주석 | train 이미지 | test 이미지/주석 | AP | recall | AP 변화(640 대비) | 다음 조치 |',
 '|---|---:|---:|---:|---:|---:|---:|---|']
for r in out:
    lines.append(f"| `{r['label']}` | {r['train_boxes']:,} | {r['train_images']:,} | {r['test_images']}/{r['test_boxes']} | {fmt(r['ap'])} | {fmt(r['recall'])} | {fmt(r['delta_ap_vs_640'])} | {r['action']} |")
lines += ['', '## 우선 처리 순서','',
 '- **많이 있는데도 낮음:** `resistor`, `battery`, `capacitor`, `transistor`는 무작위 데이터를 더 모으기보다 미탐 사례의 크기·가림·초점·각도와 라벨 경계를 확인합니다.',
 '- **주석 감사:** `text_noncomponent`는 test 3장에 박스 1,376개가 몰려 있어 정의와 박스 기준을 먼저 확인합니다.',
 '- **표본 부족:** test 이미지가 5장 미만인 라벨은 정확도 순위를 매기지 않고, 서로 다른 PCB·촬영 환경의 독립 이미지를 추가합니다.',
 '- **개선 가설:** 다음 비교는 희귀 클래스 오버샘플링 + `cls_pw=0.5` 결합을 먼저 봅니다. 단, 아래 라벨별 지표처럼 중복 가중이 특정 클래스를 더 악화시키는지 함께 확인합니다.', '']
(OUT/'label-improvement-plan.md').write_text('\n'.join(lines),encoding='utf-8')
print(OUT/'label-improvement-plan.md')


