import csv,sys
from signals import build_signal
def run(path,edge_min=0.08,confidence_min=0.80):
    with open(path,encoding="utf-8") as f: data=list(csv.DictReader(f))
    prices=[float(x["price"]) for x in data]; wins=trades=0
    for i in range(12,len(prices)-1):
        s=build_signal(prices[i],[{"p":p} for p in prices[:i]])
        if abs(s.edge)<edge_min or s.confidence<confidence_min: continue
        trades+=1
        if (s.side=="YES")== (prices[i+1]>prices[i]): wins+=1
    rate=wins/trades if trades else 0
    print("trades=",trades,"wins=",wins,"win_rate=",format(rate,".2%")); return rate
if __name__=="__main__":
    if len(sys.argv)!=2: print("usage: python backtest.py history.csv"); raise SystemExit(2)
    run(sys.argv[1])
