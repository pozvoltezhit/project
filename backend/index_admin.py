"""Explicit operator commands; build/rollback preserve existing index versions."""
import argparse
import json
import os
from pathlib import Path
from backend.core import Store
from backend.adapters import Indexes


def configured():
    return Indexes(Store(os.environ['DB_PATH']),os.environ['QDRANT_URL'],os.environ['NEO4J_URL'],
                   Path(os.environ['NEO4J_PASSWORD_FILE']).read_text().strip())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=('build','status','rollback','retire'))
    parser.add_argument('--version')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--force-new',action='store_true')
    args=parser.parse_args()
    index=configured()
    try:
        if args.command=='build':result=index.sync(args.force_new)
        elif args.command=='status':result={'active':index.active_release(),'ready':index.ready()}
        elif args.command=='rollback':
            if not args.version:parser.error('--version required')
            index.rollback(args.version);result=index.active_release()
        else:
            if not args.version:parser.error('--version required')
            result=index.retire(args.version,apply=args.apply)
        print(json.dumps(result))
    finally:
        index.qdrant.close();index.neo4j.close()


if __name__=='__main__':main()
