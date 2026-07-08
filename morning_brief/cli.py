"""명령줄 진입점.

예)
  python -m morning_brief.cli run                 # 오늘(KST) 브리핑 생성
  python -m morning_brief.cli run --date 2026-07-08
  python -m morning_brief.cli run --fixtures      # 샘플 데이터로 강제 실행
  python -m morning_brief.cli serve               # 생성된 사이트 로컬 서빙 (개발용)
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path

from .config import Config
from .pipeline import run


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = Config.from_env(output_dir=args.out, channel=args.channel)
    index_path = run(cfg, date_str=args.date, use_fixtures=args.fixtures)
    rel = index_path
    print(f"\n✅ 생성 완료: {rel}")
    print(f"   아카이브: {Path(cfg.output_dir) / 'index.html'}")
    print(f"   로컬 확인: python -m morning_brief.cli serve --out {cfg.output_dir}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    directory = str(Path(args.out).resolve())
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    with socketserver.TCPServer(("", args.port), handler) as httpd:
        print(f"Serving {directory} at http://localhost:{args.port} (Ctrl+C 종료)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n종료합니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="morning_brief", description="텔레그램 시황 브리핑 요약 사이트 생성기")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="브리핑을 수집·요약해 사이트를 생성")
    p_run.add_argument("--date", help="대상 일자 YYYY-MM-DD (기본: 오늘 KST)")
    p_run.add_argument("--out", default="site", help="출력 디렉터리 (기본: site)")
    p_run.add_argument("--channel", default="ehdwl", help="텔레그램 채널 username")
    p_run.add_argument("--fixtures", action="store_true", help="샘플 데이터로 강제 실행")
    p_run.set_defaults(func=_cmd_run)

    p_serve = sub.add_parser("serve", help="생성된 사이트를 로컬에서 서빙")
    p_serve.add_argument("--out", default="site", help="사이트 디렉터리 (기본: site)")
    p_serve.add_argument("--port", type=int, default=8000, help="포트 (기본: 8000)")
    p_serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
