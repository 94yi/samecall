"""Replay the release check or submit an order to the local example service."""
import argparse
import json
from pathlib import Path
import sqlite3
import tempfile

from adapter import ParcelDesk
from binding import METHOD
from check_route import check


def main():
    parser = argparse.ArgumentParser(description="SameCall 本地包裹分发台；不带参数时复验适配包。")
    commands = parser.add_subparsers(dest="command")
    dispatch = commands.add_parser("dispatch", help="用旧接口提交订单，返回落库后的回执号")
    dispatch.add_argument("--db", type=Path, required=True, help="示例数据库文件")
    for name in ("lane", "request", "parcel"):
        dispatch.add_argument(name)
    args = parser.parse_args()
    if not args.command:
        with tempfile.TemporaryDirectory() as root:
            result = dict(method=METHOD, **check(ParcelDesk, "dispatch", Path(root)))
    else:
        try:
            desk = ParcelDesk(args.db)
            try:
                result = {"receipt": desk.dispatch(args.lane, args.request, args.parcel)}
            finally:
                desk.db.close()
        except (ValueError, sqlite3.Error) as exc:
            parser.exit(1, f"dispatch: {exc}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
