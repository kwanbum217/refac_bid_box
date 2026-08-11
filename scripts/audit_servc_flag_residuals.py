import os, pandas as pd, numpy as np
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import sys
YEAR=sys.argv[1] if len(sys.argv)>1 else '2025'
BASE='/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box'
load_dotenv(f'{BASE}/.env')
F=['prdctClsfcLmtYn','cmmnSpldmdMethdNm','dsgntCmptYn','indstrytyLmtYn','rbidPermsnYn']
df=pd.read_parquet(f'{BASE}/data/analysis/servc_residuals/servc_residuals_{YEAR}.parquet',
                   columns=['bid_ntce_no','actual','pred','err','abs_err','sucsfbid_mthd_nm','cntrct_mthd_nm'])
print('잔차 표본', len(df))
e=create_engine(os.environ['DATABASE_URL'])
sel=", ".join([f"JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.{k}')) AS {k}" for k in F])
nos=df['bid_ntce_no'].dropna().unique().tolist()
rows=[]
with e.connect() as c:
    for i in range(0,len(nos),5000):
        ch=nos[i:i+5000]
        q=text(f"SELECT bid_ntce_no, {sel} FROM bid_announcements WHERE category='Servc' AND bid_ntce_no IN :ns")
        rows += [dict(r._mapping) for r in c.execute(q.bindparams(), {'ns':tuple(ch)})]
m=pd.DataFrame(rows).drop_duplicates('bid_ntce_no')
d=df.merge(m,on='bid_ntce_no',how='inner')
print('조인 성공', len(d), f'({100*len(d)/len(df):.1f}%)')
print(f"\n전체 err 평균 {d['err'].mean():+.4f}  MAE {d['abs_err'].mean():.4f}\n")
for f in F:
    s=d[d[f].notna() & (d[f]!='')]
    if len(s)<500: print(f'{f}: 표본 부족'); continue
    print(f"[{f}]")
    for v,g in sorted(s.groupby(f), key=lambda x:-len(x[1]))[:4]:
        if len(g)<200: continue
        mu=g['err'].mean(); se=g['err'].std(ddof=1)/len(g)**0.5
        print(f"   {str(v)[:22]:<24} n={len(g):>6}  err {mu:+.4f}  SE {se:.4f}  t {mu/se:+.2f}  MAE {g['abs_err'].mean():.4f}")
    print()
