import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv('/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/.env')
e=create_engine(os.environ['DATABASE_URL'])
q=text("""SELECT LEFT(bid_ntce_dt,7) ym, COUNT(*) n,
 SUM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.prdctClsfcLmtYn'))='Y') y,
 SUM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.prdctClsfcLmtYn'))='N') nn,
 SUM(JSON_EXTRACT(raw_data,'$.prdctClsfcLmtYn') IS NULL) missing
 FROM bid_announcements
 WHERE category='Servc' AND raw_data IS NOT NULL AND bid_ntce_dt >= '2023-01-01'
 GROUP BY ym ORDER BY ym""")
print(f"{'월':<9}{'건수':>8}{'Y':>8}{'N':>8}{'Y비율':>8}{'키없음':>8}")
prev=None
with e.connect() as c:
    for ym,n,y,nn,ms in c.execute(q):
        r=100*int(y)/n if n else 0
        mark=''
        if prev is not None and abs(r-prev)>15: mark='  <== 급변'
        print(f"{ym:<9}{n:>8,}{int(y):>8,}{int(nn):>8,}{r:>7.1f}%{int(ms):>8}{mark}")
        prev=r
