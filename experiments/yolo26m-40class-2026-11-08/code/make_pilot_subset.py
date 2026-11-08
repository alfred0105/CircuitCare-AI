from pathlib import Path
from collections import Counter
import math, random, json, os, shutil, yaml

ROOT = Path(os.environ.get('CIRCUITCARE_EXPERIMENT_ROOT', Path(__file__).resolve().parents[3]))
SRC = ROOT / 'work' / 'yolo26-benchmark' / 'dataset-40class-quality'
DEST = ROOT / 'work' / 'yolo26-benchmark' / 'dataset-40class-pilot'
FRACTIONS = {'train': 0.05, 'valid': 0.05, 'test': 0.05}
SEED = 42
IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tif', '.tiff'}

def select_split(split, fraction):
    imgdir, labdir = SRC / split / 'images', SRC / split / 'labels'
    items = []
    class_freq = Counter()
    for img in sorted(p for p in imgdir.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTS):
        lab = labdir / (img.stem + '.txt')
        if not lab.exists():
            continue
        classes = set()
        for line in lab.read_text(encoding='utf-8', errors='ignore').splitlines():
            parts = line.split()
            if parts:
                try: classes.add(int(parts[0]))
                except ValueError: pass
        if classes:
            items.append((img, lab, classes))
            class_freq.update(classes)
    target_n = max(1, math.ceil(len(items) * fraction))
    target_per_class = {c: max(1, math.ceil(n * fraction)) for c, n in class_freq.items()}
    remaining = dict(target_per_class)
    rng = random.Random(SEED + {'train': 0, 'valid': 1, 'test': 2}[split])
    tie_order = {i: rng.random() for i in range(len(items))}
    selected = []
    pool = set(range(len(items)))
    # Greedily cover class quotas, prioritizing rare classes; then fill to the requested sample size.
    while pool and (len(selected) < target_n or any(v > 0 for v in remaining.values())):
        best_i, best_score = None, -1.0
        for i in pool:
            score = sum((1 / math.sqrt(class_freq[c])) for c in items[i][2] if remaining.get(c, 0) > 0)
            if score > best_score or (score == best_score and tie_order[i] < tie_order.get(best_i, 2)):
                best_i, best_score = i, score
        if best_i is None or (best_score <= 0 and len(selected) >= target_n):
            break
        selected.append(items[best_i]); pool.remove(best_i)
        for c in items[best_i][2]:
            if remaining.get(c, 0) > 0: remaining[c] -= 1
        if len(selected) >= target_n and not any(v > 0 for v in remaining.values()):
            break
    if len(selected) < target_n:
        leftovers = sorted(pool, key=lambda i: tie_order[i])
        selected.extend(items[i] for i in leftovers[:target_n-len(selected)])
    return selected, class_freq

def link_or_copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try: os.link(src, dst)
    except OSError: shutil.copy2(src, dst)

if DEST.exists():
    shutil.rmtree(DEST)
manifest = {'fractions_requested': FRACTIONS, 'seed': SEED, 'splits': {}}
for split, fraction in FRACTIONS.items():
    selected, class_freq = select_split(split, fraction)
    for img, lab, _ in selected:
        link_or_copy(img, DEST / split / 'images' / img.name)
        link_or_copy(lab, DEST / split / 'labels' / lab.name)
    selected_counts = Counter(c for _, _, cs in selected for c in cs)
    manifest['splits'][split] = {
        'source_images_with_labels': sum(class_freq.values()) if False else len(list((SRC / split / 'images').glob('*'))),
        'selected_images': len(selected), 'target_fraction': fraction,
        'classes_in_source': len(class_freq), 'classes_in_sample': len(selected_counts),
        'class_image_frequency_source': dict(sorted(class_freq.items())),
        'class_image_frequency_sample': dict(sorted(selected_counts.items()))
    }

cfg = yaml.safe_load((SRC / 'data.yaml').read_text(encoding='utf-8'))
cfg['path'] = str(DEST).replace('\\', '/')
cfg['train'], cfg['val'], cfg['test'] = 'train/images', 'valid/images', 'test/images'
(DEST / 'data.yaml').write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding='utf-8')
(DEST / 'sample-manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps({s: {'images':v['selected_images'], 'source_classes':v['classes_in_source'], 'sample_classes':v['classes_in_sample']} for s,v in manifest['splits'].items()}, indent=2))

