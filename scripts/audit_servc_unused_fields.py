import json, os, statistics as st
from collections import defaultdict
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
BASE='/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box'
load_dotenv(f'{BASE}/.env')
e=create_engine(os.environ['DATABASE_URL'])
FLAGS=['indstrytyLmtYn','prdctClsfcLmtYn','cmmnSpldmdMethdNm','dsgntCmptYn','arsltCmptYn','rbidPermsnYn']
g=defaultdict(lambda: defaultdict(list))
q=text("""SELECT a.raw_data, r.sucsf_bid_rate
 FROM bid_results r JOIN bid_announcements a
   ON a.bid_ntce_no=r.bid_ntce_no AND a.category=r.category
 WHERE r.category='Servc' AND r.sucsf_bid_rate BETWEEN 70 AND 110
   AND a.raw_data IS NOT NULL
 ORDER BY r.id DESC LIMIT 40000""")
n=0
with e.connect() as c:
    for raw, rate in c.execute(q):
        d=json.loads(raw) if isinstance(raw,str) else raw
        if not d: continue
        n+=1; y=float(rate)
        for f in FLAGS:
            v=d.get(f)
            if v not in (None,'',' '): g[f][str(v)[:22]].append(y)
print(f"조인 표본 {n:,}건\n")
for f in FLAGS:
    grp={k:v for k,v in g[f].items() if len(v)>=200}
    if len(grp)<2: print(f"{f}: 유효 수준 부족"); continue
    tot=[x for v in grp.values() for x in v]
    om=st.mean(tot)
    print(f"[{f}]  전체 평균 {om:.3f}")
    for k,v in sorted(grp.items(), key=lambda x:-len(x[1]))[:4]:
        m=st.mean(v); sd=st.pstdev(v); se=sd/len(v)**0.5
        print(f"   {k:<24} n={len(v):>6}  평균 {m:.3f}  차 {m-om:+.3f}  SE {se:.3f}  t {(m-om)/se:+.1f}")
    print()
