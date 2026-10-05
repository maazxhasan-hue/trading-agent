import csv,sys,statistics
from signals import build_signal

def evaluate(prices,train=30,test=10,edge=.08,confidence=.80):
    results=[]
    start=train
    while start+test<len(prices):
        # Parameters are fixed inside each window; no future data is used.
        wins=trades=0
        for i in range(start,start+test):
            history=[{"p":p} for p in prices[max(0,i-train):i]]
            s=build_signal(prices[i],history)
            if abs(s.edge)<edge or s.confidence<confidence:continue
            trades+=1
            correct=(s.side=="YES")== (prices[i+1]>prices[i])
            wins+=int(correct)
        results.append({"start":start,"test":test,"trades":trades,"wins":wins,"accuracy":wins/trades if trades else 0})
        start+=test
    total=sum(x["trades"] for x in results)
    wins=sum(x["wins"] for x in results)
    print("windows=",len(results),"trades=",total,"wins=",wins,"accuracy=",format(wins/total if total else 0,".2%"))
    return results

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: python walk_forward.py history.csv")
    with open(sys.argv[1],encoding="utf-8") as f: prices=[float(x["price"]) for x in csv.DictReader(f)]
    evaluate(prices)
