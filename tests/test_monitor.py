"""monitor.py 동작 테스트

실제 교육청·학교 사이트에 접속하지 않고, 실제 게시판 구조를 본떠 만든 가짜 페이지로 검증한다.
날짜는 2026-09-29 09:00 (KST)으로 고정한다.

실행: python -m pytest -q
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor  # noqa: E402

FIXED_NOW = datetime(2026, 9, 29, 9, 0, tzinfo=monitor.KST)


# ─────────────────────────── 가짜 페이지 ───────────────────────────
VIEW = (
    "https://www.jbe.go.kr/board/view.jbe?boardId={b}&amp;menuCd=X&amp;paging=ok"
    "&amp;startPage=1&amp;searchOperation=AND&amp;dataSid={sid}"
)
DOWNLOAD = "https://www.jbe.go.kr/board/download.jbe?boardId={b}&amp;dataSid={sid}&amp;fileSid=1"
VIEWER = "https://www.jbe.go.kr/board/SynapViewer.jbe?boardId={b}&amp;dataSid={sid}&amp;fileSid=1"


def recruit_page(rows):
    """인력풀 > 채용공고. rows: (번호, 구분, 학교, 과목, 접수기간, dataSid)"""
    trs = "".join(
        f"<tr><td>{n}</td><td>{kind}</td>"
        f"<td class='subject'><a href='{VIEW.format(b='BBS_0000130', sid=sid)}' title='{school}'>{school}</a></td>"
        f"<td>{subject}</td><td>{period}</td></tr>"
        for n, kind, school, subject, period, sid in rows
    )
    return (
        "<html><head><title>학교/기관별 채용공고 &gt; 채용공고 | 인력풀</title></head><body><table>"
        "<thead><tr><th>번호</th><th>구분</th><th>학교/기관명</th><th>과목/분야</th><th>접수기간</th></tr></thead>"
        f"<tbody>{trs}</tbody></table></body></html>"
    )


PREPLAN_TITLE = "학교/기관별 채용공고 &gt; 채용계획 사전공개 : 기간제교사인력풀"


def preplan_page(rows, title=PREPLAN_TITLE):
    """인력풀 > 채용계획 사전공개. rows: (번호, 제목, 첨부파일명, 작성, 날짜, dataSid)"""
    trs = ""
    for n, title_, fname, author, day, sid in rows:
        trs += (
            f"<tr><td>{n}</td>"
            f"<td class='subject'><a href='{VIEW.format(b='BBS_0000053', sid=sid)}' title='{title_}'>{title_}</a></td>"
            f"<td><a href='{DOWNLOAD.format(b='BBS_0000053', sid=sid)}' title='{fname} 다운로드'><img alt='첨부파일'></a>"
            f"<a href='{VIEWER.format(b='BBS_0000053', sid=sid)}' title='{fname} 문서보기 새창으로 열림'>문서보기</a></td>"
            f"<td>{author}</td><td>{day}</td><td>3</td></tr>"
        )
    return f"<html><head><title>{title}</title></head><body><table><tbody>{trs}</tbody></table></body></html>"


EXAM_TITLE = "알림마당 &gt; 시험/채용/구직 &gt; 중등임용시험 &gt; 목록 화면| 전북특별자치도교육청"
GOSI_TITLE = "알림마당 &gt; 고시/공고 &gt; 목록 화면| 전북특별자치도교육청"


def exam_page(rows, title=EXAM_TITLE, board="BBS_0000043"):
    """도교육청 > 중등임용시험 / 고시/공고. rows: (번호, 제목, 날짜, dataSid)"""
    trs = "".join(
        f"<tr><td>{n}</td><td class='subject'><a href='{VIEW.format(b=board, sid=sid)}'>{t}</a></td>"
        f"<td>첨부파일</td><td>교원인사과</td><td>{day}</td><td>10</td></tr>"
        for n, t, day, sid in rows
    )
    return f"<html><head><title>{title}</title></head><body><table><tbody>{trs}</tbody></table></body></html>"


def gosi_page(rows):
    return exam_page(rows, title=GOSI_TITLE, board="BBS_0000001")


def platform_home(code, posts, menus=("채용공고",)):
    """전북 학교 통합 홈페이지(school.jbedu.kr) 첫 화면."""
    menu = "".join(
        f'<li><a href="https://school.jbedu.kr/{code}/MAB{i}/index.do">{m}</a></li>' for i, m in enumerate(menus)
    )
    menu += f'<li><a href="https://school.jbedu.kr/{code}/MCLUB/index.do">미술부</a></li>'
    menu += "".join(f'<li><a href="/{code}/M{i}/index.do">메뉴{i}</a></li>' for i in range(12))
    widget = "".join(
        f'<a href="https://school.jbedu.kr/{code}/M010301/view/{pid}.do">{t}</a>' for pid, t in posts
    )
    return f"<html><head><title>{code}</title></head><body><ul>{menu}</ul><div>{widget}</div></body></html>"


def school_board(code, posts):
    rows = "".join(
        f'<tr><td>{pid}</td><td><a href="/{code}/MAB0/view/{pid}.do">{t}</a></td><td>2026.09.20</td></tr>'
        for pid, t in posts
    )
    return f"<html><body><table>{rows}</table></body></html>"


def neis_row(name, kind, code, url, fond="사립"):
    return {"FOND_SC_NM": fond, "SCHUL_KND_SC_NM": kind, "SCHUL_NM": name, "SD_SCHUL_CODE": code, "HMPG_ADRES": url}


# ─────────────────────────── 실행 환경 ───────────────────────────
class Harness:
    def __init__(self, monkeypatch, tmp_path):
        self.pages: dict[str, str] = {}   # 교육청 게시판: URL 일부 → HTML
        self.sites: dict = {}             # 학교 홈페이지: URL 앞부분 → HTML | (최종URL, HTML) | 예외
        self.neis_rows: list[dict] = []
        self.neis_calls = 0
        self.sent: list[str] = []
        self.state_file = tmp_path / "seen.json"

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return FIXED_NOW

        monkeypatch.setattr(monitor, "datetime", FixedDatetime)
        monkeypatch.setattr(monitor, "STATE_FILE", self.state_file)
        monkeypatch.setattr(monitor.time, "sleep", lambda s: None)
        monkeypatch.setattr(monitor, "fetch", self._fetch)
        monkeypatch.setattr(monitor, "get_html", self._get_html)
        monkeypatch.setattr(monitor, "neis_get", self._neis)
        monkeypatch.setattr(monitor, "send_telegram", lambda token, chats, msg: self.sent.append(msg))
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        monkeypatch.delenv("NEIS_API_KEY", raising=False)
        self.monkeypatch = monkeypatch

        # 기본 게시판 (관련 글 없음)
        self.pages["BBS_0000130"] = recruit_page([(1, "초등학교", "가나초등학교", "조리실무사", "2026-09-29 ~ 2026-10-06", "r1")])
        self.pages["BBS_0000053"] = preplan_page([(1, "다라중학교 영어과 사전공개", "a.hwp", "다라중학교", "26.09.28", "p1")])
        self.pages["DOM_000000103004002000"] = exam_page([(1, "2027학년도 사전 예고", "2026-08-05", "e1")])
        self.pages["DOM_000000103002000000"] = gosi_page([(1, "부정당업자 입찰참가자격 제한 공고", "2026-09-27", "g1")])
        self.fetched: list[str] = []

    def _fetch(self, url):
        self.fetched.append(url)
        keys = sorted((k for k in self.pages if k in url), key=len, reverse=True)  # 더 구체적인 주소가 우선
        if not keys:
            raise RuntimeError(f"접속 실패: 404 {url}")
        page = self.pages[keys[0]]
        if isinstance(page, Exception):
            raise page
        return page

    def _get_html(self, url, timeout=15):
        for prefix, value in self.sites.items():
            if url.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return value if isinstance(value, tuple) else (url, value)
        raise RuntimeError(f"404 {url}")

    def _neis(self, params):
        self.neis_calls += 1
        rows = self.neis_rows
        return {"schoolInfo": [{"head": [{"list_total_count": len(rows)}, {"RESULT": {"CODE": "INFO-000"}}]}, {"row": rows}]}

    def enable_schools(self):
        self.monkeypatch.setenv("NEIS_API_KEY", "test-key")

    def run(self, *args):
        self.sent.clear()
        self.monkeypatch.setattr(monitor.sys, "argv", ["monitor.py", *args])
        assert monitor.main() == 0
        return list(self.sent)

    def state(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))


@pytest.fixture
def h(monkeypatch, tmp_path):
    return Harness(monkeypatch, tmp_path)


def alerts_only(messages):
    """시작·첫 확인 요약 메시지를 뺀 실제 알림만."""
    return [m for m in messages if "알리미 시작" not in m and "첫 확인" not in m]


# ─────────────────────────── 교육청 게시판 ───────────────────────────
def test_first_run_sends_start_message_and_only_recent_relevant_posts(h):
    h.pages["BBS_0000130"] = recruit_page([
        (3, "중학교", "원광중학교", "미술(1개월)", "2026-09-29 ~ 2026-10-01", "r3"),      # 접수 중 → 알림
        (2, "초등학교", "전주중산초등학교", "조리실무사", "2026-09-29 ~ 2026-10-06", "r2"),
        (1, "고등학교", "전주예술고등학교", "시간강사(미술)", "2026-09-10 ~ 2026-09-15", "r1"),  # 마감 → 제외
    ])
    h.pages["BBS_0000053"] = preplan_page([
        (4, "2026학년도 남원고등학교 계약제교원 채용계획 사전 공개", "계약제교원 채용계획(남원고).hwp", "남원고등학교", "26.09.29", "p4"),
        (3, "삼례중학교 기간제교원 채용 사전공개(영어과)", "삼례중-영어.hwp", "삼례중학교", "26.09.11", "p3"),
        (2, "전주솔내유치원 계약제교원(영양기간제교사) 채용 사전공고", "x.hwp", "전주솔내유치원", "26.09.15", "p2"),
    ])

    sent = h.run()

    assert "미술 티오 알리미 시작" in sent[0]
    body = alerts_only(sent)
    assert len(body) == 2
    assert "미술 채용공고" in body[0] and "원광중학교" in body[0]
    assert "과목 미기재" in body[1] and "남원고등학교" in body[1]
    # 14일보다 오래된 임용 게시판 글은 첫 실행에 보내지 않는다
    assert not any("중등임용시험 게시판 새 글" in m for m in sent)


def test_new_posts_after_first_run(h):
    h.run()
    h.pages["BBS_0000130"] = recruit_page([
        (5, "고등학교", "우석고등학교", "미술 기간제교사 1명", "2026-10-02 ~ 2026-10-07", "r5"),
        (4, "중학교", "이리중학교", "국어", "2026-10-02 ~ 2026-10-05", "r4"),
        (1, "초등학교", "가나초등학교", "조리실무사", "2026-09-29 ~ 2026-10-06", "r1"),
    ])
    h.pages["BBS_0000053"] = preplan_page([
        (3, "우석고등학교 기간제교사 채용 사전공고", "2학기 3차 기간제교사 채용 사전공개.hwpx", "우석고등학교", "26.10.01", "p3"),
        (2, "전주여고 기간제교원 채용계획", "사전공개(미술).hwp", "전주여자고등학교", "26.10.01", "p2"),
        (1, "다라중학교 영어과 사전공개", "a.hwp", "다라중학교", "26.09.28", "p1"),
    ])
    h.pages["DOM_000000103004002000"] = exam_page([
        (2, "2027학년도 중등학교교사 등 임용후보자 선정경쟁시험 시행계획 공고", "2026-09-30", "e2"),
        (1, "2027학년도 사전 예고", "2026-08-05", "e1"),
    ])
    h.pages["DOM_000000103002000000"] = gosi_page([
        (5, "2027학년도 전북특별자치도 중등학교교사 임용후보자 선정경쟁시험 시행계획 공고", "2026-09-30", "g5"),
        (4, "2027학년도 공립 유치원·초등학교 교사 임용후보자 선정경쟁시험 시행계획 공고", "2026-09-30", "g4"),
        (3, "2026학년도 교육공무원(장학사) 임용후보자 공개전형 공고", "2026-09-29", "g3"),
        (2, "학교 미술품 매각 공고", "2026-09-29", "g2"),
        (1, "부정당업자 입찰참가자격 제한 공고", "2026-09-27", "g1"),
    ])

    sent = h.run()

    joined = "\n".join(sent)
    assert len(sent) == 6
    assert "우석고등학교 · " in joined and "미술 기간제교사" in joined
    assert "이리중학교" not in joined
    assert "미술 채용계획 사전공개" in joined and "전주여고" in joined          # 첨부파일명으로 잡음
    assert "과목 미기재" in joined and "우석고등학교 기간제교사 채용 사전공고" in joined
    assert "중등임용시험 게시판 새 글" in joined and "시행계획 공고" in joined and "게시: 2026-09-30" in joined
    gosi = [m for m in sent if "고시/공고" in m]
    assert len(gosi) == 2
    assert "미술품 매각" in gosi[0] and "중등학교교사 임용후보자" in gosi[1]  # 오래된 글부터, 미술 키워드도 알림
    assert "초등학교 교사" not in joined and "장학사" not in joined

    assert h.run() == []  # 같은 글은 다시 보내지 않음


def test_board_falls_back_to_next_address_when_first_fails(h):
    h.run()
    h.pages["pool/board/list.jbe?boardId=BBS_0000130"] = RuntimeError("접속 실패: 500")   # 인력풀 사이트 고장
    h.pages["board/list.jbe?boardId=BBS_0000130&menuCd=DOM_000000103004006000"] = recruit_page([
        (2, "중학교", "원광중학교", "미술", "2026-10-02 ~ 2026-10-07", "r2"),
        (1, "초등학교", "가나초등학교", "조리실무사", "2026-09-29 ~ 2026-10-06", "r1"),
    ])

    sent = h.run()

    assert len(sent) == 1 and "원광중학교" in sent[0]
    assert h.state()["fails"]["recruit"] == 0


def test_board_rejects_wrong_board_even_if_it_has_posts(h):
    # 사전공개 주소에서 채용공고 게시판이 열리면(제목이 다름) 실패로 처리해야 함
    h.pages["BBS_0000053"] = preplan_page(
        [(1, "미술 기간제", "x.hwp", "원광중학교", "26.09.28", "p9")], title="학교/기관별 채용공고 &gt; 채용공고 | 인력풀"
    )
    sent = h.run()
    assert "❌ 채용계획 사전공개" in sent[0] and "다른 게시판이 열림" in sent[0]
    assert len(sent) == 1


def test_later_pages_failing_still_uses_first_page(h):
    h.run()
    h.pages["BBS_0000130&menuCd=DOM_000001601002000000&listRow=50&listCel=1&paging=ok&searchOperation=AND&startPage=2"] = RuntimeError("접속 실패: timeout")
    h.pages["BBS_0000130"] = recruit_page([(2, "중학교", "원광중학교", "미술", "2026-10-02 ~ 2026-10-07", "r2")])
    h.fetched.clear()
    sent = h.run()
    assert len(sent) == 1 and "원광중학교" in sent[0]
    recruit_urls = [u for u in h.fetched if "BBS_0000130" in u]
    assert len(recruit_urls) == 2 and "startPage=3" not in recruit_urls[-1]  # 2페이지 실패 뒤 3페이지는 시도하지 않음


def test_wrong_exam_board_warns_after_two_failures_and_not_again_within_12h(h):
    h.run()
    h.pages["DOM_000000103004002000"] = exam_page([(1, "x", "2026-01-01", "z")], title="알림마당 &gt; 지방공무원시험")

    first = h.run()
    second = h.run()
    third = h.run()

    assert first == []
    assert len(second) == 1 and "알리미 점검 필요" in second[0] and "중등임용시험 게시판 2회 연속 실패" in second[0]
    assert third == []
    assert h.state()["fails"]["exam"] == 3


def test_telegram_failure_keeps_state_so_alerts_are_retried(h, monkeypatch):
    h.run()
    h.pages["BBS_0000130"] = recruit_page([(9, "중학교", "원광중학교", "미술", "2026-10-02 ~ 2026-10-07", "r9")])

    def broken(token, chats, msg):
        raise RuntimeError("텔레그램 전송 실패")

    monkeypatch.setattr(monitor, "send_telegram", broken)
    monkeypatch.setattr(monitor.sys, "argv", ["monitor.py"])
    assert monitor.main() == 1

    monkeypatch.setattr(monitor, "send_telegram", lambda t, c, m: h.sent.append(m))
    assert any("원광중학교" in m for m in h.run())


def test_page_title_check_also_looks_at_headings():
    page = "<html><head><title>전북특별자치도교육청</title></head><body><h3>채용계획 사전공개</h3></body></html>"
    title, _ = monitor.parse_page(page, "https://www.jbe.go.kr/")
    monitor.check_board_title(monitor.BOARDS["preplan"], title)
    with pytest.raises(RuntimeError):
        monitor.check_board_title(monitor.BOARDS["recruit"], title)


@pytest.mark.parametrize("title, expected", [
    ("2027학년도 전북특별자치도 중등학교교사 임용후보자 선정경쟁시험 시행계획 공고", "exam"),
    ("2027학년도 중등학교교사 임용시험 사립학교 위탁 채용 과목 안내", "exam"),
    ("2027학년도 공립 유치원·초등학교 교사 임용후보자 선정경쟁시험 시행계획 공고", None),
    ("2027학년도 유·초·중등 교사 임용시험 사전 예고", "exam"),
    ("2026학년도 교육공무원(장학사) 임용후보자 공개전형 공고", None),
    ("전주○○고등학교 미술 교사 채용 공고", "match"),
    ("부정당업자 입찰참가자격 제한 공고", None),
])
def test_classify_gosi(title, expected):
    row = {"title": title, "text": title, "cells": [], "link_idx": -1}
    assert monitor.classify("gosi", row) == expected


def test_telegram_retries_after_rate_limit(monkeypatch):
    calls = []

    class Resp:
        def __init__(self, status):
            self.status_code, self.ok, self.text = status, status == 200, "{}"

        def json(self):
            return {"parameters": {"retry_after": 7}} if self.status_code == 429 else {}

    def fake_post(url, data, timeout):
        calls.append(data["chat_id"])
        return Resp(429 if len(calls) == 1 else 200)

    waits = []
    monkeypatch.setattr(monitor.requests, "post", fake_post)
    monkeypatch.setattr(monitor.time, "sleep", waits.append)
    monitor.send_telegram("t", ["1", "2"], "hi")
    assert calls == ["1", "1", "2"]
    assert waits[0] == 7  # 텔레그램이 알려 준 시간만큼 기다림

    monkeypatch.setattr(monitor.requests, "post", lambda url, data, timeout: Resp(400))
    with pytest.raises(RuntimeError):
        monitor.send_telegram("t", ["1"], "hi")


def test_preplan_parse_finds_author_cell_despite_attachment_links():
    url = "https://www.jbe.go.kr/pool/board/list.jbe"
    _, rows = monitor.parse_page(preplan_page([(1, "제목", "파일(미술).hwp", "전주여자고등학교", "26.10.01", "p1")]), url)
    assert len(rows) == 1
    assert monitor.cell(rows[0], 2) == "전주여자고등학교"
    assert "파일(미술).hwp" in rows[0]["text"]  # 첨부파일명도 판정 대상


# ─────────────────────────── 사립 중·고 홈페이지 ───────────────────────────
@pytest.mark.parametrize("title, expected", [
    ("2027학년도 미술 교사 채용 공고", "match"),
    ("미술 시간강사 모집 공고", "match"),
    ("미술 동아리 부원 모집 공고", None),
    ("2027학년도 신규교사 채용 공고", "unspecified"),
    ("2027학년도 교원 신규채용 공개전형(영어)", None),
    ("가정통신문 9월", None),
])
def test_classify_school_title(title, expected):
    assert monitor.classify_school_title(title) == expected


def setup_schools(h):
    h.enable_schools()
    h.neis_rows = [
        neis_row("우석고등학교", "고등학교", "1", "http://woosuk.hs.kr"),
        neis_row("우석중학교", "중학교", "2", "woosuk.hs.kr"),                       # 고등학교와 홈페이지 공유
        neis_row("원광중학교", "중학교", "3", "https://school.jbedu.kr/wonkwangms"),
        neis_row("옛사이트고등학교", "고등학교", "4", "http://old.hs.kr"),
        neis_row("접속실패고등학교", "고등학교", "5", "http://down.hs.kr"),
        neis_row("주소없는중학교", "중학교", "6", ""),
        neis_row("사립초등학교", "초등학교", "7", "http://x.es.kr"),                  # 대상 아님
    ]
    h.woosuk_posts = [
        (101, "2027학년도 미술 교사 채용 공고"),
        (90, "2024학년도 미술 기간제교사 채용"),   # 옛 글 → 처음 볼 때 제외
        (95, "미술 동아리 부원 모집 공고"),        # 채용 아님
    ]
    h.sites["http://woosuk.hs.kr"] = ("https://school.jbedu.kr/woosuk/index.do", platform_home("woosuk", [(50, "가정통신문 9월")]))
    h.sites["https://school.jbedu.kr/woosuk/MAB0"] = school_board("woosuk", h.woosuk_posts)
    h.sites["https://school.jbedu.kr/wonkwangms/MAB0"] = school_board("wonkwangms", [])
    h.sites["https://school.jbedu.kr/wonkwangms"] = platform_home(
        "wonkwangms", [(7, "2026학년도 2학기 국어 기간제교사 채용"), (8, "학부모 상담 주간 안내")]
    )
    # 자동 이동 → 프레임 → 실제 첫 화면 (옛날식 사이트)
    h.sites["http://old.hs.kr/main.html"] = (
        '<html><body><a href="/bbs/list?id=notice">공지</a>'
        '<a href="javascript:view(3)">2027학년도 미술과 기간제 교원 채용 공고</a></body></html>'
    )
    h.sites["http://old.hs.kr/frame"] = '<html><frameset><frame src="/main.html"></frameset></html>'
    h.sites["http://old.hs.kr"] = '<html><head><meta http-equiv="Refresh" content="0; URL=/frame"></head></html>'
    h.sites["http://down.hs.kr"] = RuntimeError("Connection timed out")


def test_school_first_scan(h):
    setup_schools(h)
    sent = h.run()

    summary = next(m for m in sent if "사립 중·고 홈페이지 첫 확인" in m)
    assert "대상 6곳 (중 3, 고 3)" in summary
    assert "정상 4곳" in summary and "접속 실패 1곳: 접속실패고등학교" in summary and "주소 없음 1곳" in summary

    school = [m for m in sent if m.startswith("🏫🎨") or m.startswith("🏫🟡")]
    assert len(school) == 2
    joined = "\n".join(school)
    assert "우석고등학교 · 우석중학교" in joined          # 같은 글은 한 번만, 학교 이름은 합쳐서
    assert "2027학년도 미술 교사 채용 공고" in joined
    assert "2027학년도 미술과 기간제 교원 채용 공고" in joined  # 옛날식 사이트도 따라감
    assert "2024학년도" not in joined and "동아리" not in joined
    assert h.neis_calls == 1


def test_school_scan_runs_once_a_day_and_reports_new_posts(h):
    setup_schools(h)
    h.run()

    assert alerts_only(h.run()) == []  # 같은 날 저녁에는 건너뜀
    assert "school_scan_date" in h.state()

    h.woosuk_posts.insert(0, (102, "미술 시간강사 모집 공고"))
    h.sites["https://school.jbedu.kr/woosuk/MAB0"] = school_board("woosuk", h.woosuk_posts)
    h.sites["https://school.jbedu.kr/wonkwangms"] = platform_home(
        "wonkwangms", [(9, "2027학년도 신규교사 채용 공고"), (10, "2027학년도 교원 신규채용 공개전형(영어)")]
    )
    sent = h.run("--force-schools")

    assert len(sent) == 2
    assert sent[0].startswith("🏫🎨") and "미술 시간강사 모집 공고" in sent[0]
    assert sent[1].startswith("🏫🟡") and "원광중학교" in sent[1]
    assert h.neis_calls == 1  # 학교 목록은 일주일 동안 저장본 사용


def test_school_majority_failure_still_alerts_and_retries(h):
    setup_schools(h)
    for prefix in ("http://woosuk.hs.kr", "https://school.jbedu.kr/wonkwangms", "http://old.hs.kr"):
        h.sites[prefix] = RuntimeError("blocked")
    h.neis_rows.append(neis_row("정상고등학교", "고등학교", "9", "http://ok.hs.kr"))
    h.sites["http://ok.hs.kr"] = platform_home("okhs", [(1, "2027학년도 미술 기간제교사 채용")])

    first = h.run()
    assert any("정상고등학교" in m for m in first)          # 찾은 글은 그대로 보냄
    assert "school_scan_date" not in h.state()            # 저녁에 다시 시도
    assert h.state()["fails"]["school"] == 1

    second = h.run()
    assert any("사립 중·고 홈페이지 2회 연속 실패" in m for m in second)


def test_school_scan_stops_when_time_budget_is_over(h, monkeypatch):
    setup_schools(h)
    monkeypatch.setattr(monitor, "SCHOOL_SCAN_BUDGET_SEC", -1)  # 시작하자마자 시간 초과

    sent = h.run()

    summary = next(m for m in sent if "사립 중·고 홈페이지 첫 확인" in m)
    assert "시간 부족으로 건너뜀 5곳" in summary
    assert "school_scan_date" not in h.state()  # 저녁에 다시 시도
    assert h.state()["fails"]["school"] == 1
    assert not any(m.startswith("🏫🎨") for m in sent)


def test_school_list_falls_back_to_cache_when_neis_fails(h, monkeypatch):
    setup_schools(h)
    h.run()
    state = h.state()
    state["schools"]["updated"] = "2026-01-01"  # 오래된 목록 → 새로 받기 시도
    h.state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(monitor, "neis_get", lambda p: {"RESULT": {"CODE": "ERROR-290", "MESSAGE": "인증키가 유효하지 않습니다."}})

    h.run("--force-schools")

    assert h.state()["fails"]["school"] == 0
    assert h.state()["schools"]["updated"] == "2026-01-01"


def test_without_neis_key_school_scan_is_skipped(h):
    sent = h.run()
    assert "NEIS_API_KEY 없음" in sent[0]
    assert "schools" not in h.state()
