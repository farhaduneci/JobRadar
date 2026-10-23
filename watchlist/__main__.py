"""python3 -m watchlist <command>. See README.md; `run` polls, `add` registers a company, `report` is the health digest."""
import argparse, os, sys

from . import core
from .paths import STATE


def main():
    ap = argparse.ArgumentParser(prog="watchlist", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="poll every enabled company (or one); a company with no state gets a silent baseline")
    r.add_argument("--company"); r.add_argument("--rescreen", action="store_true", help="re-run the gates on every open posting")
    r.add_argument("--dry", action="store_true", help="no alerts; state is still written")
    a = sub.add_parser("add", help="probe each board, then register the company")
    a.add_argument("--name", required=True); a.add_argument("--board", action="append", required=True, help="<ats>:<token>, repeatable")
    a.add_argument("--careers-url"); a.add_argument("--titles", help="comma-separated extra include words for this company")
    rm = sub.add_parser("remove", help="stop watching (state is kept)"); rm.add_argument("slug")
    sub.add_parser("list", help="companies, boards, open/matching counts, last run")
    rp = sub.add_parser("report", help="health digest of runs.jsonl; exit 1 when something needs a look"); rp.add_argument("--days", type=int, default=7)
    sc = sub.add_parser("scout", help="rank candidate companies (file of 'Name | url' lines) by roles passing the gates now"); sc.add_argument("file")
    args = ap.parse_args()
    os.makedirs(STATE, exist_ok=True)
    cmds = {"run": core.cmd_run, "add": core.cmd_add, "remove": core.cmd_remove, "list": core.cmd_list, "report": core.cmd_report, "scout": core.cmd_scout}
    sys.exit(cmds[args.cmd](args) or 0)


if __name__ == "__main__":
    main()
