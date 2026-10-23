"""Explicit retention. Unknown legacy dates and audit chain are preserved."""
import argparse
import json
import os
import time
from backend.core import Store


def retain(store, history_days=30, audit_days=365, apply=False):
    if min(history_days,audit_days)<1: raise ValueError('Retention must be at least one day')
    now=time.time()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        eligible=[r[0] for r in db.execute('SELECT history_id FROM history_time WHERE created_at<?',(now-history_days*86400,))]
        audit_count=db.execute('SELECT count(*) FROM audit_chain WHERE created_at<?',(now-audit_days*86400,)).fetchone()[0]
        if apply:
            db.executemany('DELETE FROM history WHERE id=?',[(i,) for i in eligible])
    return {'dry_run':not apply,'history_expired':len(eligible),'history_deleted':len(eligible) if apply else 0,
            'audit_archive_eligible':audit_count,'audit_deleted':0,
            'audit_policy':'Preserve complete integrity chain; external archive/disposal approval required',
            'legacy_history':'Rows without trusted timestamps are retained'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',default=os.environ.get('DB_PATH','data/knowledge.db'))
    parser.add_argument('--history-days',type=int,default=30)
    parser.add_argument('--audit-days',type=int,default=365)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(retain(Store(args.db),args.history_days,args.audit_days,args.apply)))


if __name__=='__main__': main()
