import base64, json, os, subprocess, sys, time, hashlib
from concurrent.futures import ThreadPoolExecutor
import httpx
sys.path.insert(0, '/workspace/statman-p2')
from statman.autotag.taxonomy import json_schema, TAXONOMY, EVENT_TYPES
from statman.autotag import tagger as T
from statman.autotag.clips import Clip

GT = json.load(open('/workspace/bench/gt.json'))
KEY = os.environ['TAGGER_API_KEY']
URL = 'https://openrouter.ai/api/v1/chat/completions'

def frames(path, dur, n=None, fps=None, width=768, src_h=None, crop=None):
    ts = [round(dur*(i+0.5)/n, 3) for i in range(n)] if n else [round(i/fps + 0.5/fps, 3) for i in range(int(dur*fps))]
    out = []
    for t in ts:
        vf = []
        if src_h: vf.append(f'scale=-2:{src_h}')
        if crop: vf.append(crop)
        vf.append(f'scale={width}:-2')
        p = subprocess.run(['ffmpeg','-v','error','-ss',f'{t:.3f}','-i',path,'-frames:v','1','-vf',','.join(vf),'-q:v','4','-f','image2','-c:v','mjpeg','pipe:1'],capture_output=True,check=True)
        out.append((t, p.stdout))
    return out

def prompt_v2():
    base = T._system_prompt()
    return base + "\n" + "\n".join([
        "CAMERA: single wide elevated sideline camera, 720p; players are small (20-40 px tall) and the ball is tiny (2-4 px, white).",
        "Track the ball frame by frame. Infer passes from the ball moving between players AND from which player is in possession in consecutive frames (the player closest to the ball / the player the others react to).",
        "METHOD: first, for every frame, silently note who (team colour) has the ball and where. Then list EVERY touch-to-touch transfer of possession as an event:",
        "- each pass between team-mates = one pass event (completed true); a pass that ends with an opponent = pass completed false followed by interception for the other team;",
        "- set pieces: a corner is taken from the corner arc with players crowded in the box; a free kick is a dead-ball restart with a wall or players lined up; tag the restart itself (corner / free_kick) AND the delivery pass (cross true).",
        "- shots: any strike toward goal; goal = ball in the net, followed by celebration, players walking back, or a restart from the centre spot.",
        "Do NOT omit passes because you are unsure of the exact player: give team, null shirt and a lower confidence instead. But never invent evenly spaced events: only tag a pass when you can see the ball (or possession) move between two players.",
        "Empty output is only correct if the ball is out of play for the whole clip.",
        'Each event object MUST use the key "type" (not event_type), e.g. {"type":"pass","team":"home","shirt":null,"t_clip_seconds":3.5,"x":40,"y":60,"attributes":{"completed":true},"confidence":0.6}.',
    ])

def ctx_text(c, dur, v2):
    s = f"Clip of {dur:.1f} s. home = {GT['teams']['home']}; away = {GT['teams']['away']}. Report t_clip_seconds between 0 and {dur:.1f}."
    if v2:
        s += (f" Half {c['half']}: home (light blue) attacks the goal on the {c['home_attacks'].upper()} of the image; away (yellow) attacks the other goal."
              " Referee wears red/black; goalkeepers wear different colours (purple/green/grey). A score bug top-left shows the match clock and score: read it to anchor timing and to confirm goals (it may update a few seconds late).")
    return s

def norm(e):
    e = dict(e)
    if 'type' not in e:
        for k in ('event_type','event','kind'):
            if k in e: e['type'] = e.pop(k); break
    if isinstance(e.get('type'), str): e['type'] = e['type'].strip().lower().replace(' ', '_').replace('-', '_')
    return e

def call(body):
    for a in range(3):
        try:
            r = httpx.post(URL, json=body, headers={'Authorization': f'Bearer {KEY}'}, timeout=300)
            j = r.json()
            if 'choices' in j: return j
            err = j
        except Exception as e:
            err = str(e)
        time.sleep(3)
    return {'error': err}

def run(variant, clip_key, part=None):
    c = GT['clips'][clip_key]
    name = clip_key + (f'_h{part}' if part is not None else '')
    path = f'/workspace/bench/clips/{name}.mp4'
    dur = 7.5 if part is not None else 15.0
    v = variant
    v2 = v.get('prompt') == 'v2'
    content = [{'type':'text','text':ctx_text(c, dur, v2)}]
    if v.get('input') == 'video':
        src = path
        if v.get('vid_h'):
            src = f'/tmp/{name}_{v["vid_h"]}.mp4'
            if not os.path.exists(src):
                subprocess.run(['ffmpeg','-v','error','-y','-i',path,'-vf',f'scale=-2:{v["vid_h"]}','-c:v','libx264','-crf','26','-an',src],check=True)
        content.append({'type':'video_url','video_url':{'url':'data:video/mp4;base64,'+base64.b64encode(open(src,'rb').read()).decode()}})
    else:
        n = v.get('frames'); fps = v.get('fps')
        if n and part is not None and v.get('scale_n'): n = max(1, n//2)
        for t, jpg in frames(path, dur, n=n, fps=fps, width=v.get('width', 768), src_h=v.get('src_h'), crop=v.get('crop')):
            content.append({'type':'text','text':f'frame t={t:.2f}s'})
            content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(jpg).decode()}})
    sysmsg = prompt_v2() if v2 else T._system_prompt()
    body = {'model': v['model'], 'temperature': 0, 'messages':[{'role':'system','content':sysmsg},{'role':'user','content':content}], 'usage':{'include':True}}
    if v.get('fmt','json_schema') == 'json_schema':
        body['response_format'] = {'type':'json_schema','json_schema':{'name':'statman_events','strict':True,'schema':json_schema()}}
    elif v['fmt'] == 'json_object':
        body['response_format'] = {'type':'json_object'}
    if v.get('reasoning'): body['reasoning'] = v['reasoning']
    t0 = time.time(); j = call(body); el = time.time()-t0
    ev, err = [], None
    try:
        txt = j['choices'][0]['message']['content']
        d = T._parse_json(txt or '')
        ev = d.get('events') if isinstance(d, dict) else d
        ev = [norm(e) for e in ev if isinstance(e, dict)]
        ev = [e for e in ev if e.get('type') in EVENT_TYPES]
    except Exception as e:
        err = repr(e)[:300] + ' ' + json.dumps(j)[:400]
    off = 7.5*part if part is not None else 0
    for e in ev:
        try: e['t_clip_seconds'] = float(e.get('t_clip_seconds') or 0) + off
        except Exception: e['t_clip_seconds'] = off
    u = j.get('usage') or {}
    raw = (j.get('choices') or [{}])[0].get('message',{}).get('content') if isinstance(j, dict) else None
    return {'raw': (raw or '')[:6000], 'clip': clip_key, 'part': part, 'events': ev, 'err': err, 'cost': u.get('cost') or 0, 'ptok': u.get('prompt_tokens'), 'ctok': u.get('completion_tokens'), 'sec': round(el,1)}

def run_variant(vname, v, clips=None, workers=7):
    clips = clips or list(GT['clips'])
    jobs = []
    for k in clips:
        if v.get('short'): jobs += [(k,0),(k,1)]
        else: jobs.append((k,None))
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda a: run(v, *a), jobs))
    out = {'name': vname, 'variant': v, 'results': res}
    json.dump(out, open(f'/workspace/bench/runs/{vname}.json','w'), indent=1)
    return out

if __name__ == '__main__':
    V = json.load(open('/workspace/bench/variants.json'))
    for name in sys.argv[1:]:
        o = run_variant(name, V[name])
        print(name, 'cost', round(sum(r['cost'] for r in o['results']),4), 'errs', sum(1 for r in o['results'] if r['err']), 'events', [len(r['events']) for r in o['results']])
