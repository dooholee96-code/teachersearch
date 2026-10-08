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
            f"<td class='subject'><a href='{VIEW.format(b='BBS_0000123', sid=sid)}' title='{title_}'>{title_}</a></td>"
            f"<td><a href='{DOWNLOAD.format(b='BBS_0000123', sid=sid)}' title='{fname} 다운로드'><img alt='첨부파일'></a>"
            f"<a href='{VIEWER.format(b='BBS_0000123', sid=sid)}' title='{fname} 문서보기 새창으로 열림'>문서보기</a></td>"
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


def detail_page(body, attachments):
    """글 상세 페이지. attachments: (파일 이름, 다운로드 URL)"""
    nav = "".join(f'<li><a href="/m{i}">메뉴{i}</a></li>' for i in range(8)) + '<li><a href="/art">미술부</a></li>'
    files = "".join(f'<li><a href="{u}" title="{n} 다운로드">{n}</a></li>' for n, u in attachments)
    return (
        f"<html><body><nav><ul>{nav}</ul></nav><div class='view'><h3>제목</h3><div class='cont'><p>{body}</p></div>"
        f"<ul class='file'>{files}</ul></div><footer>전북특별자치도교육청</footer></body></html>"
    )


def make_zip(parts: dict) -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in parts.items():
            z.writestr(name, content)
    return buf.getvalue()


def make_hwpx(text):
    return make_zip({"Contents/section0.xml": f"<hs:sec><hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></hs:sec>"})


def make_docx(text):
    return make_zip({"word/document.xml": f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"})


def neis_row(name, kind, code, url, fond="사립"):
    return {"FOND_SC_NM": fond, "SCHUL_KND_SC_NM": kind, "SCHUL_NM": name, "SD_SCHUL_CODE": code, "HMPG_ADRES": url}


# ─────────────────────────── 실행 환경 ───────────────────────────
class Harness:
    def __init__(self, monkeypatch, tmp_path):
        self.pages: dict[str, str] = {}   # 교육청 게시판: URL 일부 → HTML
        self.sites: dict = {}             # 학교 홈페이지: URL 앞부분 → HTML | (최종URL, HTML) | 예외
        self.files: dict = {}             # 첨부파일: URL → bytes | 예외
        self.neis_rows: list[dict] = []   # 전북(P10) 사립학교
        self.neis_other: dict[str, list[dict]] = {}  # 다른 지역: 교육청 코드 → 학교들
        self.neis_calls = 0
        self.offices = False              # True 면 교육청·교육지원청 누리집도 확인
        self.sent: list[str] = []
        self.boards: list[str] = []      # 실행마다 만들어진 현황판 글
        self.state_file = tmp_path / "seen.json"

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return FIXED_NOW

        monkeypatch.setattr(monitor, "datetime", FixedDatetime)
        monkeypatch.setattr(monitor, "STATE_FILE", self.state_file)
        self.web_file = tmp_path / "docs" / "data.json"
        monkeypatch.setattr(monitor, "WEB_DATA_FILE", self.web_file)
        for var in ("WEB_PAGE_URL", "GITHUB_REPOSITORY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(monitor.time, "sleep", lambda s: None)
        monkeypatch.setattr(monitor, "fetch", self._fetch)
        monkeypatch.setattr(monitor, "get_html", self._get_html)
        monkeypatch.setattr(monitor, "get_bytes", self._get_bytes)
        monkeypatch.setattr(monitor, "neis_get", self._neis)
        monkeypatch.setattr(monitor, "send_telegram", lambda token, chats, msg: self.sent.append(msg))
        monkeypatch.setattr(monitor, "update_board", lambda token, chats, text, state: self.boards.append(text))
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        monkeypatch.delenv("NEIS_API_KEY", raising=False)
        self.monkeypatch = monkeypatch

        # 기본 게시판 (관련 글 없음)
        self.pages["BBS_0000130"] = recruit_page([(1, "초등학교", "가나초등학교", "조리실무사", "2026-09-29 ~ 2026-10-06", "r1")])
        self.pages["BBS_0000123"] = preplan_page([(1, "다라중학교 영어과 사전공개", "a.hwp", "다라중학교", "26.09.28", "p1")])
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
        prefixes = sorted((p for p in self.sites if url.startswith(p)), key=len, reverse=True)  # 긴 주소 우선
        if not prefixes:
            raise RuntimeError(f"404 {url}")
        value = self.sites[prefixes[0]]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, tuple) else (url, value)

    def _get_bytes(self, url, timeout=15):
        if url not in self.files:
            raise RuntimeError(f"404 {url}")
        value = self.files[url]
        if isinstance(value, Exception):
            raise value
        return url.rsplit("/", 1)[-1], value

    def _neis(self, params):
        self.neis_calls += 1
        rows = self.neis_rows if params["ATPT_OFCDC_SC_CODE"] == "P10" else self.neis_other.get(params["ATPT_OFCDC_SC_CODE"], [])
        if not rows:
            return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}
        return {"schoolInfo": [{"head": [{"list_total_count": len(rows)}, {"RESULT": {"CODE": "INFO-000"}}]}, {"row": rows}]}

    def enable_schools(self):
        self.monkeypatch.setenv("NEIS_API_KEY", "test-key")

    def run(self, *args):
        self.sent.clear()
        if not self.offices:
            args = ("--no-offices", *args)
        self.monkeypatch.setattr(monitor.sys, "argv", ["monitor.py", *args])
        assert monitor.main() == 0
        return list(self.sent)

    def state(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def web(self):
        return json.loads(self.web_file.read_text(encoding="utf-8"))


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
    h.pages["BBS_0000123"] = preplan_page([
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
    h.pages["BBS_0000123"] = preplan_page([
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
    h.pages["BBS_0000123"] = preplan_page(
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
    assert "대상 6곳 (중 3, 고 3; 전북 6)" in summary
    assert "정상 4곳" in summary and "접속 실패 1곳: [전북] 접속실패고등학교" in summary and "주소 없음 1곳" in summary

    school = [m for m in sent if m.startswith("🏫🎨") or m.startswith("🏫🟡")]
    assert len(school) == 2
    joined = "\n".join(school)
    assert "[전북] 우석고등학교 · [전북] 우석중학교" in joined   # 같은 글은 한 번만, 학교 이름은 합쳐서
    assert "2027학년도 미술 교사 채용 공고" in joined
    assert "2027학년도 미술과 기간제 교원 채용 공고" in joined  # 옛날식 사이트도 따라감
    assert "2024학년도" not in joined and "동아리" not in joined
    assert h.neis_calls == 3  # 전북·대전·충남 한 번씩


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
    h.sites["https://school.jbedu.kr/wonkwangms/M010301/view/9.do"] = detail_page("자세한 내용은 학교로 문의 바랍니다.", [])
    sent = h.run("--force-schools")

    assert len(sent) == 2
    assert sent[0].startswith("🏫🎨") and "미술 시간강사 모집 공고" in sent[0]
    assert sent[1].startswith("🏫🟡") and "원광중학교" in sent[1] and "과목이 적혀 있지 않음" in sent[1]
    assert h.neis_calls == 3  # 학교 목록은 일주일 동안 저장본 사용


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

    h.sites["http://ok.hs.kr"] = RuntimeError("blocked")  # 읽히던 곳마저 안 열리면 2회 연속 실패
    second = h.run()
    assert any("사립 중·고 홈페이지 2회 연속 실패" in m for m in second)


def test_school_scan_stops_when_time_budget_is_over(h, monkeypatch):
    setup_schools(h)
    monkeypatch.setattr(monitor, "SITE_SCAN_BUDGET_SEC", -1)  # 시작하자마자 시간 초과

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


# ─────────────────────────── 교육청·교육지원청 누리집, 대전·충남 ───────────────────────────
def office_home(base, menus):
    """교육지원청 첫 화면. menus: (메뉴 이름, 경로)"""
    nav = "".join(
        f'<li><a href="{path if path.startswith("http") else base + path}">{name}</a></li>' for name, path in menus
    )
    nav += "".join(f'<li><a href="{base}/M{i}/index.do">메뉴{i}</a></li>' for i in range(12))
    return f"<html><body><ul>{nav}</ul><p>교육지원청에 오신 것을 환영합니다</p></body></html>"


def office_board(base, posts):
    rows = "".join(f'<tr><td><a href="{base}/view/{pid}">{t}</a></td><td>2026.10.01</td></tr>' for pid, t in posts)
    return f"<html><body><table>{rows}</table></body></html>"


TEST_OFFICES = [
    {"code": "office:office.jbedu.kr/jeonjuedu", "name": "전주교육지원청", "region": "전북",
     "url": "https://office.jbedu.kr/jeonjuedu/", "kind": "office"},
    {"code": "office:www.dje.go.kr", "name": "대전광역시교육청", "region": "대전",
     "url": "https://www.dje.go.kr/main.do", "kind": "office"},
    {"code": "office:www.cncae.go.kr", "name": "천안교육지원청", "region": "충남",
     "url": "https://www.cncae.go.kr/", "kind": "office"},
]


def setup_offices(h, monkeypatch):
    h.offices = True
    monkeypatch.setattr(monitor, "OFFICE_SITES", TEST_OFFICES)
    jj = "https://office.jbedu.kr/jeonjuedu"
    h.sites[jj + "/M01050902"] = office_board(jj + "/M01050902", [
        (11, "2026학년도 전주○○중학교 기간제교사 채용 공고(미술)"),
        (10, "2026학년도 전주△△고등학교 기간제교사 채용 공고(국어)"),
        (9, "2025학년도 전주□□중학교 기간제교사(미술) 채용 공고"),   # 작년 글 → 처음엔 제외
    ])
    h.sites[jj + "/M01050901"] = office_board(jj + "/M01050901", [(5, "2026학년도 전주◇◇초등학교 기간제교사 채용 공고(미술)")])
    h.sites[jj + "/M0105090303"] = office_board(jj + "/M0105090303", [])
    h.sites[jj] = office_home(jj, [
        ("학교채용공고(유/초등)", "/M01050901/index.do"), ("학교채용공고(중등)", "/M01050902/index.do"),
        ("기간제교사(중등)", "/M0105090303/index.do"), ("미술관 안내", "/M0199/index.do"),
    ])
    dj = "https://www.dje.go.kr"
    h.sites[dj + "/board/gosi"] = office_board(dj + "/board/gosi", [
        (3, "2027학년도 대전광역시 공·사립 중등학교교사 임용후보자 선정경쟁시험 시행계획 공고"),
        (2, "2027학년도 대전광역시 공립 유치원·초등학교 교사 임용후보자 선정경쟁시험 시행계획 공고"),
        (1, "학교용지 매각 입찰 공고"),
    ])
    h.sites[dj + "/board/gigan"] = office_board(dj + "/board/gigan", [(7, "우송고등학교 2026학년도 기간제교원(수학) 채용 공고")])
    h.sites[dj + "/main.do"] = office_home(dj, [("고시·공고", "/board/gosi"), ("기간제교사", "/board/gigan"), ("학교인력 채용공고", "/board/gigan")])
    h.sites["https://www.cncae.go.kr"] = RuntimeError("Connection timed out")


def test_office_scan_reports_art_and_exam_posts_with_region(h, monkeypatch):
    setup_offices(h, monkeypatch)
    sent = h.run()

    summary = next(m for m in sent if "교육청·교육지원청 누리집 첫 확인" in m)
    assert "대상 3곳 (전북 1, 대전 1, 충남 1)" in summary
    assert "정상 2곳" in summary and "접속 실패 1곳: [충남] 천안교육지원청" in summary

    office = [m for m in sent if m.startswith(("🏢🎨", "🏢📢", "🏢🟡"))]
    assert len(office) == 3
    art = [m for m in office if "🎨" in m]
    assert all("[전북] 전주교육지원청" in m for m in art)
    assert any("전주○○중학교" in m for m in art) and any("전주◇◇초등학교" in m for m in art)  # 초등 미술 글도 일단 알림
    exam = next(m for m in office if "📢" in m)
    assert "[대전] 대전광역시교육청" in exam and "공·사립 중등학교교사 임용후보자" in exam
    joined = "\n".join(sent)
    assert "2025학년도" not in joined and "유치원·초등학교" not in joined and "국어" not in joined and "수학" not in joined

    # 이후 실행에서는 새 글만. 교육청 누리집은 저녁에도 확인한다 (학교는 하루 1번)
    assert h.run() == []
    jj = "https://office.jbedu.kr/jeonjuedu"
    h.sites[jj + "/M01050902"] = office_board(jj + "/M01050902", [(12, "2026학년도 2학기 전주☆☆고 미술 시간강사 채용 공고")])
    again = h.run()
    assert len(again) == 1 and "미술 시간강사" in again[0] and again[0].startswith("🏢🎨")


def test_office_menus_prefer_secondary_and_hiring_menus_and_stay_on_same_site(h):
    from bs4 import BeautifulSoup
    base = "https://office.jbedu.kr/jeonjuedu"
    page = office_home(base, [
        ("고시공고", "/a"), ("학교채용공고(유/초등)", "/b"), ("학교채용공고(중등)", "/c"),
        ("구인구직", "/d"), ("채용 외부 사이트", "https://edurecruit.go.kr/x"), ("학교찾기", "https://school.jbedu.kr/find"),
    ])
    menus = monitor.hiring_menus(base + "/", BeautifulSoup(page, "html.parser"), "office")
    assert menus[0] == base + "/c" and base + "/b" in menus and base + "/a" in menus
    assert "edurecruit" not in " ".join(menus)
    assert monitor.same_site("www.dje.go.kr", "dje.go.kr")
    assert monitor.same_site("office.jbedu.kr", "school.jbedu.kr")
    assert not monitor.same_site("www.dje.go.kr", "www.cne.go.kr")


@pytest.mark.parametrize("title, kind, expected", [
    ("2027학년도 충청남도 공립 중등학교 교사 임용후보자 선정경쟁시험 시행계획 공고", "office", "exam"),
    ("2027학년도 공립 유치원·초등학교 교사 임용후보자 선정경쟁시험 시행계획 공고", "office", None),
    ("2027학년도 중등학교교사 임용시험 사전 예고", "office", "exam"),
    ("2026년 교육공무원 임용 관련 서류 안내", "office", None),            # 시험 공고가 아님
    ("2027학년도 중등학교교사 임용후보자 선정경쟁시험 시행계획 공고", "school", None),  # 학교 홈페이지에선 보지 않음
    ("음봉중학교 기간제 교원(미술) 채용 공고", "office", "match"),
])
def test_classify_site_title_office(title, kind, expected):
    assert monitor.classify_site_title(title, kind) == expected


def test_school_list_covers_daejeon_and_chungnam_and_refreshes_when_regions_change(h):
    setup_schools(h)
    h.neis_other["G10"] = [neis_row("우송고등학교", "고등학교", "d1", "http://woosong.hs.kr")]
    h.neis_other["N10"] = [neis_row("천안○○고등학교", "고등학교", "c1", "http://cheonan.hs.kr")]
    h.sites["http://woosong.hs.kr"] = platform_home("woosong", [(1, "2027학년도 미술 교사 채용 공고")])
    h.sites["http://cheonan.hs.kr"] = platform_home("cheonan", [(1, "2027학년도 신규교사 채용 공고")])

    sent = h.run()
    summary = next(m for m in sent if "사립 중·고 홈페이지 첫 확인" in m)
    assert "대상 8곳 (중 3, 고 5; 전북 6, 대전 1, 충남 1)" in summary
    assert any("[대전] 우송고등학교" in m and "🏫🎨" in m for m in sent)
    assert not any("천안○○고등학교" in m for m in sent)  # 과목 미기재 글은 처음 볼 땐 보내지 않음
    assert h.state()["schools"]["regions"] == ["전북", "대전", "충남"]

    # 예전 버전(전북만)에서 저장한 목록은 감시 지역이 달라졌으니 일주일을 기다리지 않고 바로 새로 받는다
    state = h.state()
    state["schools"] = {"updated": "2026-09-29", "list": [s for s in state["schools"]["list"] if s["region"] == "전북"]}
    h.state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    calls_before = h.neis_calls
    h.run("--force-schools")
    assert h.neis_calls == calls_before + 3
    assert len(h.state()["schools"]["list"]) == 8


# ─────────────────────────── 글 본문·첨부파일 확인 ───────────────────────────
@pytest.mark.parametrize("title, expected", [
    ("2026학년도 2학기 ○○고등학교 교원 채용 공고", True),
    ("2026학년도 기간제교사 채용 공고", True),
    ("○○중학교 기간제교사 채용 공고(국어)", False),        # 과목 있음
    ("○○중학교 미술 기간제교사 채용 공고", False),          # 미술 → 바로 알림
    ("2026년 교육공무직원(조리실무사) 채용 공고", False),    # 교사 아님
    ("○○초등학교 기간제교사 채용 공고", False),             # 초등
    ("학교운영위원회 위원 모집 공고", False),
])
def test_needs_detail(title, expected):
    assert monitor.needs_detail(title) == expected


@pytest.mark.parametrize("text, expected", [
    ("담당 과목: 국어 / 채용 인원 1명", True),
    ("2026학년도 기간제교사(영어) 채용", True),
    ("수학과 기간제교사 1명", True),
    ("사회 1명, 과학 2명 모집", True),
    ("개인정보 수집·이용 동의서, 담당: 교육정보과, 진로상담부 제출", False),  # 흔한 안내문
    ("사회과학 도서 구입", False),
    ("기간제교사 채용 공고. 자세한 내용은 붙임 참조", False),
])
def test_subject_strict_regex(text, expected):
    assert bool(monitor.SUBJECT_STRICT_RE.search(text)) == expected


def test_hwp_section_parsing_handles_control_chars_and_compression():
    import zlib

    def para(text):
        payload = text.encode("utf-16-le")
        header = (67 | (len(payload) << 20)).to_bytes(4, "little")  # tag 67 = HWPTAG_PARA_TEXT
        return header + payload

    other = (66 | (6 << 20)).to_bytes(4, "little") + b"\x00" * 6
    inline = (1).to_bytes(2, "little") + b"\x00" * 14          # 확장 제어문자(8글자) → 무시
    text = "담당 과목: 미술" + chr(13) + "채용 인원 1명"
    section = other + para("표 머리") + (67 | (16 << 20)).to_bytes(4, "little") + inline + para(text)
    got = monitor.hwp_section_text(section)
    assert "담당 과목: 미술\n채용 인원 1명" in got and "표 머리" in got

    class FakeOle:
        def __init__(self, flags, sections):
            self.flags, self.sections = flags, sections

        def exists(self, name):
            return name == "FileHeader"

        def listdir(self):
            return [["BodyText", f"Section{i}"] for i in range(len(self.sections))] + [["DocInfo"]]

        def openstream(self, entry):
            import io
            if entry == "FileHeader":
                return io.BytesIO(b"HWP Document File".ljust(36, b"\x00") + self.flags.to_bytes(4, "little"))
            return io.BytesIO(self.sections[int(entry[1][7:])])

    compressed = zlib.compress(section)[2:-4]  # raw deflate
    monkey = pytest.MonkeyPatch()
    monkey.setattr(monitor, "hwp_text", monitor.hwp_text)
    import olefile
    monkey.setattr(olefile, "isOleFile", lambda data: True)
    monkey.setattr(olefile, "OleFileIO", lambda data: FakeOle(1, [compressed]))
    assert "미술" in monitor.hwp_text(b"\xd0\xcf\x11\xe0fake")
    monkey.setattr(olefile, "OleFileIO", lambda data: FakeOle(1 | 2, [compressed]))
    assert monitor.hwp_text(b"\xd0\xcf\x11\xe0fake") is None  # 암호 문서
    monkey.undo()


def test_extract_text_detects_file_type_by_content():
    assert "미술" in monitor.extract_text(make_hwpx("담당 과목: 미술"))
    assert "국어과" in monitor.extract_text(make_docx("국어과 기간제교사"))
    xlsx = make_zip({"xl/sharedStrings.xml": "<sst><si><t>과목</t></si><si><t>음악</t></si></sst>", "xl/worksheets/sheet1.xml": "<x/>"})
    assert "음악" in monitor.extract_text(xlsx)
    import io
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    w = PdfWriter()
    page = w.add_blank_page(200, 200)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (ART TEACHER 2027) Tj ET")
    page[NameObject("/Contents")] = w._add_object(stream)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    buf = io.BytesIO()
    w.write(buf)
    pdf = buf.getvalue()
    assert "ART TEACHER" in monitor.extract_text(pdf)
    assert monitor.extract_text(b"\x89PNG\r\n\x1a\n....") is None   # 그림
    assert monitor.extract_text(b"PK\x03\x04 broken") is None         # 깨진 압축 파일
    assert monitor.extract_text(b"") is None


def test_main_text_skips_menus_and_attachment_links_are_found():
    from bs4 import BeautifulSoup
    page = detail_page("기간제교사 채용 안내문입니다. 붙임 참조.", [("공고문(미술).hwp", "/download?f=1"), ("지원서.hwpx", "/download?f=2")])
    soup = BeautifulSoup(page, "html.parser")
    text = monitor.main_text(soup)
    assert "채용 안내문" in text and "미술부" not in text
    links = monitor.attachment_links("https://school.jbedu.kr/x/view/1", soup)
    assert links == [("공고문(미술).hwp", "https://school.jbedu.kr/download?f=1"), ("지원서.hwpx", "https://school.jbedu.kr/download?f=2")]


def test_office_posts_without_subject_are_resolved_from_attachments(h, monkeypatch):
    setup_offices(h, monkeypatch)
    h.run()  # 첫 확인 (옛 글 정리)

    jj = "https://office.jbedu.kr/jeonjuedu"
    posts = [
        (21, "2026학년도 2학기 전주A고등학교 교원 채용 공고"),          # hwpx 첨부에 미술 → 🎨
        (22, "2026학년도 전주B중학교 기간제교사 채용 공고"),             # docx 첨부에 국어과 → 조용히 넘김
        (23, "2026학년도 전주C고등학교 기간제교사 채용 공고"),           # 첨부가 그림 → 🟡
        (24, "2026학년도 전주D중학교 기간제교원 채용 공고"),             # 본문에 미술 → 🎨 (첨부 안 읽음)
        (25, "2026학년도 전주E고등학교 기간제교사 채용 공고"),           # 글이 안 열림 → 🟡
        (26, "2026학년도 전주F중학교 기간제교사 채용 공고(영어)"),       # 제목에 과목 → 열지 않음
    ]
    h.sites[jj + "/M01050902"] = office_board(jj + "/M01050902", posts)
    v = jj + "/M01050902/view/"
    h.sites[v + "21"] = detail_page("붙임 공고문 참조", [("공고문.hwpx", jj + "/down/21")])
    h.files[jj + "/down/21"] = make_hwpx("모집 분야: 미술 1명 (2026.9.1.~2027.2.28.)")
    h.sites[v + "22"] = detail_page("붙임 참조", [("공고문.docx", jj + "/down/22")])
    h.files[jj + "/down/22"] = make_docx("담당 과목: 국어 / 채용 인원 1명")
    h.sites[v + "23"] = detail_page("붙임 참조", [("공고문.png", jj + "/down/23")])
    h.files[jj + "/down/23"] = b"\x89PNG\r\n\x1a\n...."
    h.sites[v + "24"] = detail_page("미술 교과 기간제교사 1명을 모집합니다.", [("공고문.hwp", jj + "/down/24")])
    h.sites[v + "25"] = RuntimeError("Connection timed out")

    sent = h.run()

    assert len(sent) == 4, sent
    a = next(m for m in sent if "전주A고등학교" in m)
    assert a.startswith("🏢🎨") and "첨부 「공고문.hwpx」에 미술" in a
    assert not any("전주B중학교" in m for m in sent)
    c = next(m for m in sent if "전주C고등학교" in m)
    assert c.startswith("🏢🟡") and "읽지 못함" in c
    d = next(m for m in sent if "전주D중학교" in m)
    assert d.startswith("🏢🎨") and "본문에 미술" in d
    e = next(m for m in sent if "전주E고등학교" in m)
    assert e.startswith("🏢🟡") and "글을 열지 못함" in e
    assert not any("전주F중학교" in m for m in sent)
    assert h.run() == []  # 두 번 보내지 않고, 넘긴 글도 다시 열지 않음


def test_preplan_unspecified_rows_are_resolved_from_detail_page(h):
    h.run()
    h.pages["BBS_0000123"] = preplan_page([
        (3, "남원A고등학교 기간제교원 채용계획 사전공개", "채용계획.hwpx", "남원A고등학교", "26.10.01", "p3"),
        (2, "남원B중학교 기간제교원 채용계획 사전공개", "채용계획.hwpx", "남원B중학교", "26.10.01", "p2"),
    ])
    for sid, text in (("p3", "과목: 미술, 기간: 2026.11.1.~"), ("p2", "과목: 체육, 기간: 2026.11.1.~")):
        view = f"https://www.jbe.go.kr/board/view.jbe?boardId=BBS_0000123&menuCd=X&paging=ok&startPage=1&searchOperation=AND&dataSid={sid}"
        h.sites[view] = detail_page("붙임 참조", [("채용계획.hwpx", f"https://www.jbe.go.kr/board/download.jbe?dataSid={sid}")])
        h.files[f"https://www.jbe.go.kr/board/download.jbe?dataSid={sid}"] = make_hwpx(text)

    sent = h.run()
    assert len(sent) == 1
    assert sent[0].startswith("🎨") and "남원A고등학교" in sent[0] and "첨부 「채용계획.hwpx」에 미술" in sent[0]


# ─────────────────────────── 현황판 (고정 메시지) ───────────────────────────
def test_board_lists_open_posts_and_drops_them_after_deadline(h, monkeypatch):
    h.run()
    h.pages["BBS_0000130"] = recruit_page([
        (5, "고등학교", "우석고등학교", "미술 기간제교사 1명", "2026-10-02 ~ 2026-10-07", "r5"),
        (1, "초등학교", "가나초등학교", "조리실무사", "2026-09-29 ~ 2026-10-06", "r1"),
    ])
    h.pages["BBS_0000123"] = preplan_page([
        (3, "우석고등학교 기간제교사 채용 사전공고", "사전공개.hwpx", "우석고등학교", "26.10.01", "p3"),
        (1, "다라중학교 영어과 사전공개", "a.hwp", "다라중학교", "26.09.28", "p1"),
    ])
    h.sites["https://www.jbe.go.kr/board/view.jbe?boardId=BBS_0000123"] = detail_page("붙임 참조", [])
    h.pages["DOM_000000103004002000"] = exam_page([
        (2, "2027학년도 중등학교교사 등 임용후보자 선정경쟁시험 시행계획 공고", "2026-09-30", "e2"),
        (1, "2027학년도 사전 예고", "2026-08-05", "e1"),
    ])
    h.run()

    board = h.boards[-1]
    assert board.startswith("📌 <b>미술 티오 현황판</b> (09/29 09:00 기준)")
    assert "<b>🎨 미술 공고</b> 1건" in board and "우석고등학교 · 미술 기간제교사 1명</a> ~10/07" in board
    assert "<b>🟡 확인 필요 (과목 미기재)</b> 1건" in board and "우석고등학교 기간제교사 채용 사전공고" in board
    assert "<b>📢 임용시험 관련</b> 1건" in board and "시행계획 공고</a> 09/29" in board
    found = h.state()["found"]
    assert {e["id"] for e in found} == {"recruit:r5", "preplan:p3", "exam:e2"}

    # 열흘 뒤: 접수가 끝난 채용공고는 빠지고, 🟡은 14일, 📢은 30일 동안 남는다
    monkeypatch.setattr(monitor, "datetime", type("D", (monitor.datetime,), {"now": classmethod(lambda cls, tz=None: FIXED_NOW.replace(day=29) + __import__("datetime").timedelta(days=10))}))
    h.run()
    board = h.boards[-1]
    assert "<b>🎨 미술 공고</b> 0건" in board and "<b>🟡 확인 필요 (과목 미기재)</b> 1건" in board and "<b>📢 임용시험 관련</b> 1건" in board
    assert len(h.state()["found"]) == 3  # 기록은 90일 보관

    monkeypatch.setattr(monitor, "datetime", type("D", (monitor.datetime,), {"now": classmethod(lambda cls, tz=None: FIXED_NOW + __import__("datetime").timedelta(days=40))}))
    h.run()
    assert "<b>📢 임용시험 관련</b> 0건" in h.boards[-1]


def test_board_includes_site_posts_with_region(h, monkeypatch):
    setup_offices(h, monkeypatch)
    h.run()
    assert "[대전] " in h.boards[-1] and "공·사립 중등학교교사 임용후보자" in h.boards[-1]
    assert "[전북] " in h.boards[-1] and "전주○○중학교" in h.boards[-1]


def test_update_board_edits_or_sends_and_pins(monkeypatch):
    calls = []

    class Resp:
        def __init__(self, ok, text="", mid=None):
            self.ok, self.text, self.status_code, self.mid = ok, text, 200 if ok else 400, mid

        def json(self):
            return {"result": {"message_id": self.mid}}

    def fake_call(token, method, data):
        calls.append((method, data.get("chat_id"), data.get("message_id")))
        if method == "editMessageText":
            return Resp(data["chat_id"] == "1") if data.get("message_id") != 99 else Resp(False, "Bad Request: message is not modified")
        if method == "sendMessage":
            return Resp(True, mid=500 + len(calls))
        return Resp(True)

    monkeypatch.setattr(monitor, "telegram_call", fake_call)
    monkeypatch.setattr(monitor.time, "sleep", lambda s: None)

    state = {"board_messages": {"1": 10, "2": 20, "3": 99}}
    monitor.update_board("t", ["1", "2", "3", "4"], "text", state)
    methods = [c[0] for c in calls]
    assert methods.count("editMessageText") == 3                      # 1·2·3은 고쳐 쓰기 시도
    assert methods.count("sendMessage") == 2 and methods.count("pinChatMessage") == 2  # 2(실패)·4(없음)는 새로 보내고 고정
    assert state["board_messages"]["1"] == 10 and state["board_messages"]["3"] == 99
    assert state["board_messages"]["2"] != 20 and "4" in state["board_messages"]

    calls.clear()
    monitor.update_board("t", ["1", "2", "3", "4"], "text", state)
    assert calls == []  # 내용이 같으면 아무것도 안 함


# ─────────────────────────── 웹페이지 ───────────────────────────
def test_runs_without_any_channel_and_prints_alerts_to_log(h, monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    monkeypatch.setenv("GITHUB_REPOSITORY", "dooho/art-tio")
    h.pages["BBS_0000130"] = recruit_page([(3, "중학교", "원광중학교", "미술(1개월)", "2026-09-29 ~ 2026-10-01", "r3")])

    assert h.run() == []  # 텔레그램 없음 → 보내는 건 없지만
    out = capsys.readouterr().out
    assert "알리미 시작" in out and "원광중학교" in out and "https://dooho.github.io/art-tio/" in out
    assert h.boards == []  # 텔레그램 현황판은 없음
    assert h.web()["entries"][0]["title"] == "원광중학교 · 미술(1개월)"  # 웹페이지 데이터는 갱신됨
    assert h.state()["found"]


def test_web_data_file_lists_entries_with_alive_flag(h):
    h.pages["BBS_0000130"] = recruit_page([
        (3, "중학교", "원광중학교", "미술(1개월)", "2026-09-29 ~ 2026-10-01", "r3"),
        (2, "고등학교", "전주예술고등학교", "시간강사(미술)", "2026-09-10 ~ 2026-09-15", "r2"),  # 마감 → 첫 실행 땐 안 보냄
    ])
    h.run()
    web = h.web()
    assert web["updated"].startswith("2026-09-29T09:00") and web["regions"] == ["전북", "대전", "충남"]
    assert [e["title"] for e in web["entries"]] == ["원광중학교 · 미술(1개월)"]
    assert web["entries"][0]["alive"] is True and web["entries"][0]["deadline"] == "2026-10-01"
    assert any("기간제 채용공고" in s for s in web["status"])


def test_web_page_url_outside_actions_is_empty_unless_given(monkeypatch):
    assert monitor.web_page_url() == ""
    monkeypatch.setenv("WEB_PAGE_URL", "https://example.com/tio/")
    assert monitor.web_page_url() == "https://example.com/tio/"


# ─────────────────────────── 실제 실행(2026-10-08)에서 드러난 문제들 ───────────────────────────
def test_same_exam_notice_on_two_boards_is_sent_once(h):
    h.run()
    title = "2027학년도 전북특별자치도 중등학교교사 임용후보자 선정경쟁시험 시행계획 공고"
    h.pages["DOM_000000103004002000"] = exam_page([(2, title, "2026-09-30", "e2"), (1, "2027학년도 사전 예고", "2026-08-05", "e1")])
    h.pages["DOM_000000103002000000"] = gosi_page([(5, title, "2026-09-30", "g5"), (1, "부정당업자 입찰참가자격 제한 공고", "2026-09-27", "g1")])
    sent = h.run()
    assert len(sent) == 1 and "중등임용시험 게시판" in sent[0]
    assert len(h.state()["found"]) == 1
    assert h.run() == []


def test_viewer_links_are_not_treated_as_attachments():
    from bs4 import BeautifulSoup
    page = (
        '<html><body><div class="view"><p>붙임 참조</p><ul>'
        '<li><a href="/board/download.jbe?dataSid=1&fileSid=1" title="채용계획.hwp 다운로드">채용계획.hwp</a>'
        '<a href="/board/SynapViewer.jbe?dataSid=1&fileSid=1" title="채용계획.hwp 문서보기 새창으로 열림">바로보기</a></li>'
        '</ul></div></body></html>'
    )
    links = monitor.attachment_links("https://www.jbe.go.kr/board/view.jbe?dataSid=1", BeautifulSoup(page, "html.parser"))
    assert links == [("채용계획.hwp", "https://www.jbe.go.kr/board/download.jbe?dataSid=1&fileSid=1")]


@pytest.mark.parametrize("text", ["과목(분야): 국어", "모집 분야 - 영어 1명", "담당교과 : 수학"])
def test_subject_strict_regex_accepts_common_table_forms(text):
    assert monitor.SUBJECT_STRICT_RE.search(text)


def test_site_health_uses_previously_reachable_sites_as_baseline(h, monkeypatch):
    # 대전·충남처럼 처음부터 막힌 곳은 두 번째 실행부터 '정상' 기준에서 빠진다
    setup_offices(h, monkeypatch)
    blocked = [{"code": f"office:blocked{i}", "name": f"막힌청{i}", "region": "충남", "url": f"https://blocked{i}.go.kr/", "kind": "office"} for i in range(5)]
    monkeypatch.setattr(monitor, "OFFICE_SITES", TEST_OFFICES + blocked)
    for b in blocked:
        h.sites[b["url"]] = RuntimeError("Connection timed out")

    h.run()
    assert h.state()["fails"]["office"] == 1          # 첫 실행: 8곳 중 2곳만 읽힘 → 비정상
    assert h.state()["office_ok"] == ["office:office.jbedu.kr/jeonjuedu", "office:www.dje.go.kr"]
    h.run()
    assert h.state()["fails"]["office"] == 0          # 두 번째: 지난번에 읽힌 2곳이 다 읽힘 → 정상
    h.sites["https://www.dje.go.kr/main.do"] = RuntimeError("down")
    h.sites["https://office.jbedu.kr/jeonjuedu"] = RuntimeError("down")
    h.run()
    assert h.state()["fails"]["office"] == 1          # 읽히던 곳이 다 죽으면 비정상


def test_site_scan_retries_with_http_when_https_times_out(h, monkeypatch):
    import requests
    setup_offices(h, monkeypatch)
    h.sites["https://www.cncae.go.kr"] = requests.exceptions.Timeout("443 막힘")
    h.sites["http://www.cncae.go.kr"] = office_home("http://www.cncae.go.kr", [("채용정보", "/recruit")])
    h.sites["http://www.cncae.go.kr/recruit"] = office_board("http://www.cncae.go.kr/recruit", [(1, "2026학년도 천안A중학교 기간제교사(미술) 채용 공고")])
    sent = h.run()
    assert any("천안A중학교" in m and "[충남] 천안교육지원청" in m for m in sent)
    assert "접속 실패 0곳" in next(m for m in sent if "누리집 첫 확인" in m)
