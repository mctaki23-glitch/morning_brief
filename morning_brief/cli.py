"""명령줄 진입점.

예)
  python -m morning_brief run --fixtures --out site        # 샘플 데이터로 사이트 생성 (개발)
  python -m morning_brief run --production                 # 오늘(KST) 브리핑을 즉시 1회 수집·생성
  python -m morning_brief run --production --scheduled     # 06:30 목표 게시 감지 대기 루프 (GitHub Actions 용)
  python -m morning_brief run --date 2026-09-08 --production
  python -m morning_brief rebuild --out site                # 아카이브 전체로 사이트 재생성
  python -m morning_brief notify --status site/status.json  # 상태 기반 알림(옵션)
  python -m morning_brief serve --out site                  # 로컬 서빙
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path

from .config import Config


def _cfg(args: argparse.Namespace) -> Config:
    cfg = Config.from_env(output_dir=getattr(args, "out", None), channel=getattr(args, "channel", None),
                          base_url=getattr(args, "base_url", None), logo_path=getattr(args, "logo", None),
                          archive_dir=getattr(args, "archive", None))
    if getattr(args, "production", False):
        cfg.production = True
    return cfg


def _cmd_run(args: argparse.Namespace) -> int:
    from .pipeline import run
    from .scheduler import run_scheduled

    cfg = _cfg(args)
    if args.scheduled:
        index_path = run_scheduled(cfg, date_str=args.date, target=args.target, deadline=args.deadline,
                                   poll_sec=args.poll, max_wait_sec=args.max_wait)
    else:
        index_path = run(cfg, date_str=args.date, use_fixtures=args.fixtures)
    print(f"\n생성 완료: {index_path}")
    print(f"   상태: {Path(cfg.output_dir) / 'status.json'}")
    print(f"   로컬 확인: python -m morning_brief.cli serve --out {cfg.output_dir}")
    return 0


def _cmd_rebuild(args: argparse.Namespace) -> int:
    from . import render
    from .pipeline import rebuild_site

    cfg = _cfg(args)
    n = rebuild_site(cfg)
    render.write_shared_pages(Path(cfg.output_dir), logo_svg=cfg.logo_svg())
    print(f"아카이브 {n}일치 재생성 완료: {cfg.output_dir}")
    return 0


def _cmd_notify(args: argparse.Namespace) -> int:
    from .notify import message_from_status, send_telegram

    if args.text:
        text = args.text
    else:
        text = message_from_status(Path(args.status), site_url=args.site_url or Config.from_env().base_url)
    if not text:
        print("알림 필요 없음")
        return 0
    sent = send_telegram(text)
    print("알림 전송" if sent else "알림 미전송")
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


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", default=None, help="출력 디렉터리 (기본: site)")
    p.add_argument("--archive", default=None, help="아카이브 디렉터리 (기본: archive)")
    p.add_argument("--base-url", dest="base_url", help="사이트 기본 URL (OG 절대 링크용)")
    p.add_argument("--logo", help="공식 로고 SVG 경로 (없으면 로고 영역 비움)")
    p.add_argument("--production", action="store_true", help="운영 모드 (샘플·합성 데이터 폴백 금지)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="morning_brief", description="텔레그램 시황 브리핑 → 미래에셋 CI 데일리 리포트 사이트 생성기")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="브리핑을 수집·요약해 사이트를 생성")
    _common(p_run)
    p_run.add_argument("--date", help="대상 일자 YYYY-MM-DD (기본: 오늘 KST)")
    p_run.add_argument("--channel", default=None, help="텔레그램 채널 username (기본: ehdwl)")
    p_run.add_argument("--fixtures", action="store_true", help="샘플 데이터로 강제 실행")
    p_run.add_argument("--scheduled", action="store_true", help="게시 감지 대기 루프로 실행 (06:30 목표)")
    p_run.add_argument("--target", default="06:30", help="목표 생성 시각 HH:MM KST (기본 06:30)")
    p_run.add_argument("--deadline", default="09:00", help="이후 미게시면 '브리핑 없음' 처리 HH:MM (기본 09:00)")
    p_run.add_argument("--poll", type=int, default=300, help="게시 감지 간격(초, 기본 300)")
    p_run.add_argument("--max-wait", dest="max_wait", type=int, default=2700, help="잡당 최대 대기(초, 기본 2700)")
    p_run.set_defaults(func=_cmd_run)

    p_rebuild = sub.add_parser("rebuild", help="아카이브 전체로 사이트 재생성")
    _common(p_rebuild)
    p_rebuild.set_defaults(func=_cmd_rebuild)

    p_notify = sub.add_parser("notify", help="status.json 기반 텔레그램 알림(옵션)")
    p_notify.add_argument("--status", default="site/status.json")
    p_notify.add_argument("--site-url", dest="site_url", default=None)
    p_notify.add_argument("--text", default=None, help="지정 시 이 문구를 그대로 전송")
    p_notify.set_defaults(func=_cmd_notify)

    p_serve = sub.add_parser("serve", help="생성된 사이트를 로컬에서 서빙")
    p_serve.add_argument("--out", default="site")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
