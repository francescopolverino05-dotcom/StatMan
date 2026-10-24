import json, sys, glob
GT = json.load(open('/workspace/bench/gt.json'))['clips']
KEY = {'goal','shot','corner','free_kick','foul','card','save'}
SLACK = 2.0
def score(run):
    by = {}
    for r in run['results']:
        by.setdefault(r['clip'], []).extend(r['events'])
    tp = {}; fn = {}; fp = 0; kp = 0; perr = []; pcount = {}
    for k, g in GT.items():
        pred = [e for e in by.get(k, [])]
        used = set()
        for ge in g['events']:
            hit = None
            for i, e in enumerate(pred):
                if i in used or e['type'] != ge['type']: continue
                t = e.get('t_clip_seconds') or 0
                if ge['t'][0]-SLACK <= t <= ge['t'][1]+SLACK: hit = i; break
            if hit is None:
                for i, e in enumerate(pred):  # lenient: right type anywhere in clip
                    if i not in used and e['type'] == ge['type']: hit = i; break
            (tp if hit is not None else fn).setdefault(ge['type'], 0)
            if hit is not None: tp[ge['type']] += 1; used.add(hit)
            else: fn[ge['type']] += 1
        opt = {o['type'] for o in g.get('optional', [])}
        for i, e in enumerate(pred):
            if i in used or e['type'] not in KEY: continue
            if e['type'] in opt: continue
            if e['type'] == 'save' and 'shot' in opt: continue
            fp += 1
        kp += sum(1 for i,e in enumerate(pred) if e['type'] in KEY and (i in used or e['type'] not in opt))
        np_ = sum(1 for e in pred if e['type'] == 'pass')
        pcount[k] = np_
        if g.get('passes'):
            lo, hi = g['passes']; perr.append(0 if lo <= np_ <= hi else min(abs(np_-lo), abs(np_-hi)))
    rec = {t: f"{tp.get(t,0)}/{tp.get(t,0)+fn.get(t,0)}" for t in sorted(set(tp)|set(fn))}
    ntp = sum(tp.values())
    prec = ntp/(ntp+fp) if ntp+fp else None
    cost = sum(r['cost'] for r in run['results']); n_clip = len(GT)
    dur = 15.0
    return {'name': run['name'], 'recall': rec, 'key_recall': f"{ntp}/{ntp+sum(fn.values())}", 'key_prec': None if prec is None else round(prec,2), 'FP': fp,
            'passes': pcount, 'open_pass_in_range': sum(1 for x in perr if x==0), 'cost_clip': round(cost/n_clip,4),
            'match_cost': round(cost/(n_clip*15) * 5400 * (1.5 if not run['variant'].get('short') else 1.5), 2),
            'errs': sum(1 for r in run['results'] if r['err'])}
if __name__ == '__main__':
    for f in sorted(glob.glob('/workspace/bench/runs/*.json')):
        s = score(json.load(open(f)))
        print(json.dumps(s, ensure_ascii=False))
