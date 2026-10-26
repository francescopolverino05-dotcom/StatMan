import sys,json,os,pickle,requests;sys.path.insert(0,'/workspace/StatMan')
from statman.detect import label
from statman.autotag.scorebug import llm_endpoint
k=os.environ['TAGGER_API_KEY'];ep=llm_endpoint();base=ep.split('/chat')[0]
def usage():
  try:return requests.get(base+'/key',headers={'Authorization':f'Bearer {k}'},timeout=30).json()['data'].get('usage')
  except Exception as e:return None
u0=usage();print('key usage before',u0)
B=pickle.load(open('lab/batches.pkl','rb'))
L,spent,calls=label.run(B,k,0.40,ep,log=print)
u1=usage();print('key usage after',u1,'delta',(u1-u0) if u0 is not None and u1 is not None else None)
json.dump({'labels':L,'spent_usage_cost':spent,'calls':calls,'key_usage_before':u0,'key_usage_after':u1},open('lab/labels.json','w'),indent=1)
print(len(L),'labels')
