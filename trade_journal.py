"""Append-only JSONL journal for auditable paper/live decision records."""
from __future__ import annotations
import json, os, time
from pathlib import Path

class TradeJournal:
    def __init__(self, path=None):
        self.path=path or os.getenv("TRADE_JOURNAL_FILE","data/nse_trade_journal.jsonl")
        Path(os.path.dirname(self.path) or ".").mkdir(parents=True,exist_ok=True)
    def record(self,event,**fields):
        row={"ts":time.time(),"event":event,**fields}
        with open(self.path,"a",encoding="utf-8") as f:
            f.write(json.dumps(row,separators=(",",":"),sort_keys=True)+"\n")
        return row
