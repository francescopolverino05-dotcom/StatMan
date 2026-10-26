import sys,json,statistics as st;sys.path.insert(0,'/workspace/StatMan')
from statman.detect import evaluate as E
M=json.load(open('moments_u8_1280.json'));L={int(k):v for k,v in json.load(open('lab/labels.json'))['labels'].items()}
H=[h for h in E.load_hand('/workspace/at-test/hand.txt') if 960<=h.t<1140];OFF,lo,hi=960,960,1140
TY={'PASS':'pass','SHOT':'shot','TACKLE':'tackle','INTERCEPT':'interception','CLEAR':'clearance','RECOVERY':'recovery','THROW':'throw-in'}
C=[dict(t=M[i]['t']+OFF,**L[i]) for i in sorted(L) if str(L[i].get('event','')).lower()!='no event']
print('labelled',len(L),'events kept',len(C),'no-event',len(L)-len(C))
ht=[h.t for h in H];ct=[c['t'] for c in C]
def attrs(pairs,cands):
  r={}
  def acc(f,valid=lambda h,c:True):
    v=[(h,c) for i,j in pairs for h,c in [(H[i],cands[j])] if valid(h,c)]
    return sum(f(h,c) for h,c in v),len(v)
  r['team']=acc(lambda h,c:c['team']==h.team,lambda h,c:c['team'] in('home','away'))
  r['type']=acc(lambda h,c:str(c['event']).lower()==TY.get(h.type,h.type.lower()))
  r['outcome']=acc(lambda h,c:str(c['outcome']).lower()==('success' if h.outcome in('success','goal') else 'fail'),lambda h,c:c['outcome'] in('success','fail'))
  r['shirt_answered']=acc(lambda h,c:str(c['shirt'])==str(h.shirt),lambda h,c:h.shirt and str(c['shirt']).isdigit())
  r['shirt_all']=acc(lambda h,c:str(c['shirt'])==str(h.shirt),lambda h,c:bool(h.shirt))
  return r
for w in (1,2):
  p=E.match(ht,ct,w);ch=E.chance(ht,ct,w,lo,hi)
  print(f'±{w}s matched {len(p)} recall {len(p)/len(H):.3f} (chance {ch/len(H):.3f}) precision {len(p)/len(C):.3f} (chance {ch/len(C):.3f})')
  a=attrs(p,C);print(' real',{k:(f'{x}/{n}',round(x/max(n,1),2)) for k,(x,n) in a.items()})
  # chance: shift label sequence relative to times (labels permuted circularly among candidates)
  agg={k:[0,0] for k in a}
  for s in range(1,len(C)):
    Cs=[dict(C[j],t=C[j]['t']) for j in range(len(C))];lab=[C[(j+s)%len(C)] for j in range(len(C))]
    Cs=[dict(lab[j],t=C[j]['t']) for j in range(len(C))]
    for k,(x,n) in attrs(p,Cs).items():agg[k][0]+=x;agg[k][1]+=n
  print(' label-shuffle chance',{k:round(x/max(n,1),2) for k,(x,n) in agg.items()})
  tm=[H[i].team for i,j in p if C[j]['team'] in('home','away')];print(' team majority',round(max(tm.count('home'),tm.count('away'))/len(tm),2))
  ty=[TY.get(H[i].type) for i,j in p];print(' type majority(pass)',round(ty.count('pass')/len(ty),2))
  oc=[H[i].outcome for i,j in p];print(' outcome majority(success)',round(sum(o!='fail' for o in oc)/len(oc),2))
# possession changes
hp=E.possession_changes(H);tc=[c for c in C if c['team'] in('home','away')]
cp=[b['t'] for a,b in zip(tc,tc[1:]) if a['team']!=b['team']]
print('poss changes hand',len(hp),'pred',len(cp))
for w in (1,2,3):print(f' ±{w}s matched {len(E.match(hp,cp,w))} chance {E.chance(hp,cp,w,lo,hi):.1f}')
from collections import Counter;print(Counter(str(l.get('event')) for l in L.values()),Counter(str(l.get('team')) for l in L.values()),Counter(str(l.get('shirt')) for l in L.values()).most_common(5))
