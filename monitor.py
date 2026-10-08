#!/usr/bin/env python3
"""전북·대전·충남 미술 교사 티오 알리미

전북특별자치도교육청 게시판 4곳과 세 지역의 교육청·교육지원청·사립 중·고 누리집을 읽어서
미술 관련 새 글을 텔레그램으로 보냅니다.

  1) 기간제교사 인력풀 > 채용공고         과목/분야에 '미술'이 있으면 알림
  2) 기간제교사 인력풀 > 채용계획 사전공개  제목·첨부파일명에 '미술'이 있으면 알림
                                          과목이 안 적힌 중등 글은 '확인 필요'로 알림
  3) 도교육청 > 중등임용시험 게시판         새 글은 모두 알림 (공립 + 사립 위탁 채용)
  4) 도교육청 > 고시/공고                  '미술' 또는 중등·교사 임용 관련 글만 알림
                                          (임용시험 시행계획 공고가 여기에도 실림)
  5) 교육청·교육지원청 누리집 (매번)        전북 교육지원청 14곳, 대전교육청·교육지원청 2곳(학교지원센터 포함),
                                          충남교육청·교육지원청 14곳. 첫 화면과 채용·구인·임용·고시 메뉴에서
                                          미술 채용 글, 과목 없는 신규교사 채용 글, 중등 임용시험 글을 찾음
  6) 전북·대전·충남 사립 중·고 홈페이지 (하루 1번)
                                          첫 화면과 '채용' 메뉴에서 미술 채용 글을 찾음
                                          학교 목록은 나이스 교육정보 개방포털에서 자동으로 받음

게시판마다 주소를 여러 개 두고(인력풀 사이트 → 교육청 본사이트), 앞 주소가 안 열리면 다음 주소로 넘어갑니다.
제목에 과목이 없는 교사 채용 글은 글을 열어 본문과 첨부파일(hwp·hwpx·pdf·docx·xlsx)에서 과목을 찾습니다.
'미술'이 있으면 🎨, 다른 과목이 분명하면 알리지 않고, 읽지 못하면 🟡(직접 확인)로 보냅니다.

환경변수
  TELEGRAM_BOT_TOKEN  텔레그램 봇 토큰
  TELEGRAM_CHAT_ID    받을 채팅 ID (여러 개면 쉼표로 구분)
  NEIS_API_KEY        나이스 교육정보 개방포털 인증키 (없으면 4번은 건너뜀)

실행
  python monitor.py                  실제 실행 (알림 발송 + seen.json 저장)
  python monitor.py --dry-run        알림 내용만 화면에 출력하고 저장하지 않음
  python monitor.py --force-schools  오늘 이미 확인했어도 사립학교 홈페이지를 다시 확인
  python monitor.py --no-offices     교육청·교육지원청 누리집 확인은 건너뜀
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

# ─────────────────────────── 설정 ───────────────────────────
KEYWORDS = ["미술"]              # 이 단어가 과목·제목·첨부파일명에 있으면 즉시 알림
FIRST_RUN_LOOKBACK_DAYS = 14     # 첫 실행 때는 최근 이 기간의 관련 글만 알려 줌
FAILS_BEFORE_ALERT = 2           # 연속 몇 번 실패하면 경고를 보낼지 (하루 2회 실행 기준 약 반나절)
ERROR_ALERT_INTERVAL_HOURS = 12  # 경고 반복 간격
MAX_SEEN_PER_BOARD = 1500
TELEGRAM_RETRIES = 4             # 텔레그램 전송 제한·서버 오류 때 다시 시도하는 횟수

JBE = "https://www.jbe.go.kr"


def board_pages(path: str, pages: int, rows: int = 50, **params: str) -> list[str]:
    """교육청 게시판 목록 주소를 페이지 수만큼 만든다 (startPage=1..pages)."""
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return [
        f"{JBE}{path}?{query}&listRow={rows}&listCel=1&paging=ok&searchOperation=AND&startPage={p}"
        for p in range(1, pages + 1)
    ]


# 게시판마다 주소 후보를 순서대로 시도한다. 첫 주소가 안 열리거나 다른 게시판이 열리면 다음 후보로 넘어간다.
# 주소는 검색엔진에 남은 실제 링크로 확인한 것 (2026-10 기준). boardId 는 게시판 고유 번호라 메뉴가 바뀌어도 유지된다.
BOARDS = {
    "recruit": {
        "name": "기간제 채용공고",
        "sources": [
            # 인력풀 사이트 > 학교/기관별 채용공고 > 채용공고 (최근 150건: 12시간 사이 올라온 글을 놓치지 않도록)
            board_pages("/pool/board/list.jbe", 3, boardId="BBS_0000130", menuCd="DOM_000001601002000000"),
            # 교육청 본사이트 > 알림마당 > 시험/채용/구직 > 학교/기관별 채용공고 (같은 게시판)
            board_pages("/board/list.jbe", 3, boardId="BBS_0000130", menuCd="DOM_000000103004006000"),
            board_pages("/index.jbe", 3, menuCd="DOM_000000103004006000"),
        ],
        "expect_title": "채용공고",
        "reject_title": "사전공개",
    },
    "preplan": {
        "name": "채용계획 사전공개",
        "sources": [
            # 인력풀 사이트 > 학교/기관별 채용공고 > 채용계획 사전공개 (최근 100건)
            board_pages("/pool/board/list.jbe", 2, boardId="BBS_0000053", menuCd="DOM_000001601001000000"),
            board_pages("/pool/board/list.jbe", 2, boardId="BBS_0000053", menuCd="DOM_000001802001000000"),
            # 교육청 본사이트 > 알림마당 > 시험/채용/구직 > 학교/기관별 채용공고 > 채용계획 사전공개
            board_pages("/board/list.jbe", 2, boardId="BBS_0000053", menuCd="DOM_000000103004005000"),
            board_pages("/index.jbe", 2, menuCd="DOM_000000103004005000"),
        ],
        "expect_title": "사전공개",
    },
    "exam": {
        "name": "중등임용시험 게시판",
        "sources": [
            # 교육청 본사이트 > 알림마당 > 시험/채용/구직 > 중등임용시험
            board_pages("/board/list.jbe", 1, 30, boardId="BBS_0000043",
                        menuCd="DOM_000000103004002000", categoryCode1="BB"),
            [f"{JBE}/index.jbe?menuCd=DOM_000000103004002000"],
        ],
        "expect_title": "중등임용",
    },
    "gosi": {
        "name": "고시/공고",
        "sources": [
            # 교육청 본사이트 > 알림마당 > 고시/공고 (임용시험 시행계획 공고가 여기에 실림. 글이 많아 관련 글만 골라냄)
            board_pages("/index.jbe", 1, 30, menuCd="DOM_000000103002000000"),
        ],
        "expect_title": "고시/공고",
    },
}
# 고시/공고에서 '미술'이 없어도 알릴 글: 중등·교사 임용 관련 (초등·유치원만 해당하는 글은 제외)
GOSI_EXAM_RE = re.compile(r"임용")
GOSI_TEACHER_RE = re.compile(r"중등|교사|교원")
GOSI_EXCLUDE_RE = re.compile(r"초등|유치원|특수학교")

# 사립 중·고 홈페이지 + 교육청·교육지원청 누리집
NEIS_URL = "https://open.neis.go.kr/hub/schoolInfo"
NEIS_OFFICES = {"P10": "전북", "G10": "대전", "N10": "충남"}   # 나이스 시도교육청 코드 → 지역 이름 (감시 지역)
NEIS_OFFICE_CODE = "P10"          # 예전 이름 (호환용)
SCHOOL_KINDS = {"중학교", "고등학교"}
SCHOOL_LIST_REFRESH_DAYS = 7      # 학교 목록(폐교·통합 반영)을 며칠마다 새로 받을지
SITE_WORKERS = 8                  # 동시에 여는 누리집 수
SITE_SCAN_BUDGET_SEC = 720        # 한 묶음(학교 전체 / 교육청 전체)을 훑는 데 쓸 최대 시간. 넘기면 남은 곳은 건너뜀
SITE_HTTP_TIMEOUT = 12            # 누리집 한 번 요청에 기다리는 시간(초)
MAX_SEEN_SCHOOL = 5000


def _offices(region: str, kind_name: str, entries: list[tuple[str, str]]) -> list[dict]:
    return [
        {"code": f"office:{urlparse(url).netloc}{urlparse(url).path.rstrip('/')}", "name": f"{name}{kind_name}",
         "region": region, "url": url, "kind": "office"}
        for name, url in entries
    ]


# 교육청·교육지원청 누리집. 학교 홈페이지와 같은 방식으로 첫 화면과 채용·구인·임용·고시 메뉴를 훑는다.
# 주소는 2026-10 웹 검색으로 확인한 것. 매 실행(아침·저녁)마다 확인한다.
OFFICE_SITES = (
    _offices("전북", "교육지원청", [
        ("전주", "https://office.jbedu.kr/jeonjuedu/"), ("군산", "https://office.jbedu.kr/jbgse/"),
        ("익산", "https://office.jbedu.kr/jbise/"), ("정읍", "https://office.jbedu.kr/jbjue/"),
        ("남원", "https://office.jbedu.kr/jbnwe/"), ("김제", "https://office.jbedu.kr/jbgje/"),
        ("완주", "https://office.jbedu.kr/jbwje/"), ("진안", "https://office.jbedu.kr/jbjae/"),
        ("무주", "https://office.jbedu.kr/jbmje/"), ("장수", "https://office.jbedu.kr/jbjse/"),
        ("임실", "https://office.jbedu.kr/jbime/"), ("순창", "https://office.jbedu.kr/jbsce/"),
        ("고창", "https://office.jbedu.kr/gce/"), ("부안", "https://office.jbedu.kr/jbbae/"),
    ])
    + _offices("대전", "", [
        ("대전광역시교육청", "https://www.dje.go.kr/main.do"),
        ("대전동부교육지원청", "https://www.djdbe.go.kr/home/main.do"),
        ("대전동부교육지원청 학교지원센터", "https://www.djdbe.go.kr/ssc/home/main.do"),
        ("대전서부교육지원청", "https://www.djsbe.go.kr/home/main.do"),
        ("대전서부교육지원청 학교지원센터", "https://www.djsbe.go.kr/ssc/home/main.do"),
    ])
    + _offices("충남", "", [("충청남도교육청", "https://www.cne.go.kr/")])
    + _offices("충남", "교육지원청", [
        ("천안", "https://www.cncae.go.kr/"), ("공주", "https://www.cngje.go.kr/"),
        ("보령", "https://www.cnbre.go.kr/"), ("아산", "https://www.cnased.go.kr/"),
        ("서산", "https://www.cnssed.go.kr/"), ("논산계룡", "https://www.cnnse.go.kr/"),
        ("당진", "https://www.cndje.go.kr/"), ("금산", "https://www.cngse.go.kr/"),
        ("부여", "https://www.cnbye.go.kr/"), ("서천", "https://www.cnsce.go.kr/"),
        ("청양", "https://www.cncyed.go.kr/"), ("홍성", "https://www.cnhsed.go.kr/"),
        ("예산", "https://www.cnyse.go.kr/"), ("태안", "https://www.cntae.go.kr/"),
    ])
)

SECONDARY_RE = re.compile(r"중학교|고등학교|중등|여중|여고|고교|중·고|중고등")
SUBJECT_WORDS = (
    "국어 영어 수학 사회 역사 지리 도덕 윤리 과학 물리 화학 생물 생명 지구 "
    "체육 음악 기술 가정 정보 컴퓨터 한문 일본어 중국어 독일어 프랑스어 스페인어 "
    "보건 사서 상담 영양 특수 진로 기계 금속 전기 전자 건설 토목 농업 식품 조리 "
    "미용 상업 회계 공업 담임"
).split()

KST = timezone(timedelta(hours=9))
STATE_FILE = Path(__file__).with_name("seen.json")
VIEW_LINK_RE = re.compile(r"/board/view\.jbe")
DATE_FULL_RE = re.compile(r"(?<!\d)(20\d{2})[-.](\d{1,2})[-.](\d{1,2})(?!\d)")
DATE_SHORT_RE = re.compile(r"(?<!\d)(\d{2})\.(\d{2})\.(\d{2})(?!\d)")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
})


# ─────────────────────────── 수집 ───────────────────────────
def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def short_error(exc: BaseException) -> str:
    """requests 예외를 사용자가 읽을 수 있는 짧은 말로 바꾼다."""
    if isinstance(exc, requests.exceptions.Timeout):
        return "시간 초과"
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "접속 안 됨"
    return str(exc)[:90]


def fetch(url: str) -> str:
    last_error = None
    for attempt in range(2):
        try:
            try:
                resp = SESSION.get(url, timeout=30)
            except requests.exceptions.SSLError:
                # 공공기관 사이트의 인증서 체인 문제 대비 (읽기 전용 요청이라 위험 낮음)
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                resp = SESSION.get(url, timeout=30, verify=False)
            resp.raise_for_status()
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(3)
    raise RuntimeError(f"접속 실패({short_error(last_error)})")


def parse_page(page_html: str, base_url: str) -> tuple[str, list[dict]]:
    """목록 페이지에서 게시글 행을 뽑는다. 게시글 링크(dataSid)를 기준으로 찾는다."""
    soup = BeautifulSoup(page_html, "html.parser")
    # 어느 게시판이 열렸는지 확인할 때 <title>과 제목 태그(h1~h4)를 함께 본다
    headings = " | ".join(norm(h.get_text(" ")) for h in soup.find_all(["h1", "h2", "h3", "h4"])[:8])
    page_title = norm(f"{soup.title.get_text() if soup.title else ''} | {headings}").strip(" |")
    rows: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not VIEW_LINK_RE.search(href) or "dataSid=" not in href:
            continue
        sid = parse_qs(urlparse(href).query).get("dataSid", [""])[0]
        if not sid or sid in rows:
            continue
        tr = a.find_parent("tr")
        container = tr if tr is not None else a.parent
        cell_tags = container.find_all(["td", "th"]) if tr is not None else []
        cells = [norm(c.get_text(" ")) for c in cell_tags]
        link_cell = a.find_parent(["td", "th"])
        link_idx = next((i for i, c in enumerate(cell_tags) if c is link_cell), -1)
        link_titles = " ".join(x.get("title", "") for x in container.find_all("a"))
        rows[sid] = {
            "id": sid,
            "title": norm(a.get_text(" ")) or norm(a.get("title", "")),
            "url": urljoin(base_url, href),
            "cells": cells,
            "link_idx": link_idx,
            "text": norm(f"{container.get_text(' ')} {link_titles}"),
        }
    return page_title, list(rows.values())


def check_board_title(board: dict, page_title: str) -> None:
    expect, reject = board.get("expect_title"), board.get("reject_title")
    if (expect and expect not in page_title) or (reject and reject in page_title):
        raise RuntimeError(f"다른 게시판이 열림(페이지 제목: {page_title[:60]})")


def read_board(board: dict) -> tuple[list[dict], str]:
    """주소 후보를 차례로 시도해 (게시글 목록, 비고)를 돌려준다.

    후보마다 첫 페이지는 반드시 읽혀야 하고, 뒤 페이지는 실패해도 읽은 데까지 쓴다.
    """
    failures: list[str] = []
    for n, urls in enumerate(board["sources"], start=1):
        rows: list[dict] = []
        for i, url in enumerate(urls):
            try:
                page_title, page_rows = parse_page(fetch(url), url)
                check_board_title(board, page_title)
                if i == 0 and not page_rows:
                    raise RuntimeError("게시글을 하나도 못 읽음 — 사이트 구조가 바뀌었을 수 있음")
            except Exception as exc:  # noqa: BLE001
                if i == 0:
                    failures.append(str(exc)[:90])
                    break
                print(f"[{board['name']}] {i + 1}페이지 읽기 실패(무시): {exc}", file=sys.stderr)
                break
            known = {r["id"] for r in rows}
            rows.extend(r for r in page_rows if r["id"] not in known)  # 페이지 간 중복(공지글) 제거
            time.sleep(1)
        if rows:
            note = "" if n == 1 else f" (예비 주소 {n}번 사용)"
            return rows, note
    if len(set(failures)) == 1:
        message = f"주소 {len(failures)}개 모두 {failures[0]}" if len(failures) > 1 else failures[0]
    else:
        message = " / ".join(f"{n}번 주소: {f}" for n, f in enumerate(failures, start=1))
    if any("다른 게시판" in f or "하나도 못 읽음" in f for f in failures):
        message += " — 주소 확인 필요"
    raise RuntimeError(message)


# ─────────────────────────── 판정 ───────────────────────────
def dates_in(text: str) -> list[date]:
    found = []
    for y, m, d in DATE_FULL_RE.findall(text):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    for y, m, d in DATE_SHORT_RE.findall(text):
        try:
            found.append(date(2000 + int(y), int(m), int(d)))
        except ValueError:
            pass
    return found


def cell(row: dict, offset: int) -> str:
    i = row["link_idx"] + offset
    return row["cells"][i] if row["link_idx"] >= 0 and 0 <= i < len(row["cells"]) else ""


def classify(board_key: str, row: dict) -> str | None:
    text = row["text"]
    if any(k in text for k in KEYWORDS):
        return "match"
    if board_key == "exam":
        return "exam"
    if board_key == "gosi":
        title = row["title"]
        if GOSI_EXAM_RE.search(title) and GOSI_TEACHER_RE.search(title):
            if GOSI_EXCLUDE_RE.search(title) and not SECONDARY_RE.search(title):
                return None  # 초등·유치원만 해당하는 임용 글
            return "exam"
        return None
    if board_key == "preplan" and SECONDARY_RE.search(text):
        author = cell(row, 2)
        subject_text = text.replace(author, " ") if author else text
        if not any(w in subject_text for w in SUBJECT_WORDS):
            return "unspecified"
    return None


def is_recent(board_key: str, row: dict, kind: str, today: date) -> bool:
    found = dates_in(row["text"])
    if not found:
        return False
    if board_key == "recruit" and kind == "match":
        return max(found) >= today  # 아직 접수 중인 공고
    return max(found) >= today - timedelta(days=FIRST_RUN_LOOKBACK_DAYS)


def format_message(board_key: str, row: dict, kind: str, note: str = "") -> str:
    e = html.escape
    if board_key == "recruit":
        period = next((c for c in row["cells"] if DATE_FULL_RE.search(c)), "")
        head = "🎨 <b>미술 채용공고</b> (기간제·강사)"
        body = (
            f"{e(cell(row, 0) or row['title'])} · {e(cell(row, -1))}\n"
            f"과목: {e(cell(row, 1))}\n"
            f"접수: {e(period)}"
        )
    elif board_key == "preplan":
        if kind == "match":
            head = "🎨 <b>미술 채용계획 사전공개</b> (보통 7일 뒤 본공고)"
        else:
            head = "🟡 <b>과목 미기재 중등 사전공개</b> — 첨부에 미술 있는지 확인"
        body = f"{e(row['title'])}\n작성: {e(cell(row, 2))} {e(cell(row, 3))}" + (f"\n({e(note)})" if note else "")
    else:
        where = "중등임용시험 게시판 새 글" if board_key == "exam" else "고시/공고 임용 관련 글"
        head = f"📢 <b>{where}</b>"
        if kind == "match":
            head += " (미술 언급)"
        found = dates_in(row["text"])
        body = e(row["title"]) + (f"\n게시: {max(found):%Y-%m-%d}" if found else "")
    return f'{head}\n{body}\n<a href="{e(row["url"], quote=True)}">공고 열기</a>'


# ─────────────────────────── 누리집 훑기 (사립 중·고, 교육지원청, 대전·충남 교육청) ───────────────────────────
HIRE_STRONG_RE = re.compile(r"채용|공개전형|초빙|임용")
HIRE_WEAK_RE = re.compile(r"모집|공고")
STAFF_RE = re.compile(r"교사|교원|강사|기간제|계약제")
REGULAR_RE = re.compile(r"신규|정규|공개전형")
TEACHER_RE = re.compile(r"교사|교원")
JS_REDIRECT_RE = re.compile(
    r"location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]|location\.replace\(\s*['\"]([^'\"]+)['\"]"
)
# 어떤 메뉴를 따라 들어갈지. 학교는 '채용'만, 교육(지원)청은 채용·구인·기간제·임용·고시 메뉴까지
MENU_RE = {
    "school": re.compile(r"채용"),
    "office": re.compile(r"채용|구인|기간제|임용|고시"),
}
MENU_PRIORITY = (re.compile(r"중등"), re.compile(r"교사|교원|기간제|채용"))  # 앞에 있는 말이 든 메뉴를 먼저 연다
MAX_MENUS = {"school": 3, "office": 6}


def get_html(url: str, timeout: int = SITE_HTTP_TIMEOUT) -> tuple[str, str]:
    headers = dict(SESSION.headers)
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(url, headers=headers, timeout=timeout, verify=False)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.url, resp.text


def neis_get(params: dict) -> dict:
    resp = requests.get(NEIS_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_school_list(api_key: str) -> list[dict]:
    """나이스 교육정보 개방포털에서 감시 지역의 사립 중·고 목록과 홈페이지 주소를 받는다."""
    schools = []
    for office_code, region in NEIS_OFFICES.items():
        page = 1
        while True:
            data = neis_get({
                "KEY": api_key, "Type": "json", "pIndex": page, "pSize": 1000,
                "ATPT_OFCDC_SC_CODE": office_code, "FOND_SC_NM": "사립",
            })
            if "schoolInfo" not in data:
                result = data.get("RESULT", {})
                if result.get("CODE") == "INFO-200":
                    break  # 더 없음 (첫 페이지부터 없으면 그 지역엔 해당 학교가 없는 것)
                raise RuntimeError(f"나이스 응답 오류({region}) {result.get('CODE')}: {result.get('MESSAGE')}")
            rows = data["schoolInfo"][1]["row"]
            for r in rows:
                if r.get("FOND_SC_NM") == "사립" and r.get("SCHUL_KND_SC_NM") in SCHOOL_KINDS:
                    schools.append({
                        "code": r.get("SD_SCHUL_CODE", ""),
                        "name": r.get("SCHUL_NM", ""),
                        "kind": r.get("SCHUL_KND_SC_NM", ""),
                        "region": region,
                        "url": (r.get("HMPG_ADRES") or "").strip(),
                    })
            if len(rows) < 1000:
                break
            page += 1
    if not schools:
        raise RuntimeError("나이스에서 사립 중·고를 한 곳도 받지 못함")
    order = list(NEIS_OFFICES.values())
    return sorted(schools, key=lambda x: (order.index(x["region"]), x["kind"], x["name"]))


def fix_url(url: str) -> str:
    url = url.strip()
    if not url or url in ("http://", "https://"):
        return ""
    return url if url.startswith(("http://", "https://")) else "http://" + url


def load_home(start_url: str) -> list[tuple[str, BeautifulSoup]]:
    """첫 화면을 불러온다. 메타·자바스크립트 이동과 프레임은 몇 단계까지 따라간다."""
    pages, queue, visited = [], [start_url], set()
    while queue and len(visited) < 4:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        final_url, text = get_html(url)
        soup = BeautifulSoup(text, "html.parser")
        pages.append((final_url, soup))
        if len(soup.find_all("a", href=True)) >= 10:
            continue  # 정상적인 첫 화면
        nxt = []
        meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
        if meta:
            m = re.search(r"url\s*=\s*['\"]?([^'\";]+)", meta.get("content", ""), re.I)
            if m:
                nxt.append(m.group(1))
        for m in JS_REDIRECT_RE.finditer(text):
            nxt.append(m.group(1) or m.group(2))
        nxt += [f["src"] for f in soup.find_all(["frame", "iframe"], src=True)[:2]]
        queue += [urljoin(final_url, u.strip()) for u in nxt if u and u.strip()]
    return pages


def site_items(page_url: str, soup: BeautifulSoup) -> list[dict]:
    items = []
    for a in soup.find_all("a", href=True):
        title = norm(a.get_text(" ")) or norm(a.get("title", ""))
        if not 6 <= len(title) <= 200:
            continue
        href = a["href"].strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:")) or not href:
            link, key = page_url, f"{urlparse(page_url).netloc}|{title}"
        else:
            link = urljoin(page_url, href)
            key = link
        items.append({"id": hashlib.sha1(key.encode()).hexdigest()[:16], "title": title, "url": link,
                      "detail": link != page_url})
    return items


def same_site(host_a: str, host_b: str) -> bool:
    """www.dje.go.kr 와 dje.go.kr, office.jbedu.kr 와 school.jbedu.kr 처럼 같은 기관의 주소인지."""
    def base(host: str) -> str:
        parts = host.lower().split(".")
        n = 3 if len(parts) >= 3 and parts[-2] in ("go", "or", "ac", "co", "ne", "hs", "ms", "es", "sc", "pe") else 2
        return ".".join(parts[-n:])
    return base(host_a) == base(host_b)


def hiring_menus(page_url: str, soup: BeautifulSoup, kind: str = "school") -> list[str]:
    host = urlparse(page_url).netloc
    menu_re, limit = MENU_RE[kind], MAX_MENUS[kind]
    found: list[tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        text, href = norm(a.get_text(" ")), a["href"].strip()
        if not menu_re.search(text) or len(text) > 20 or href.startswith(("#", "javascript:")):
            continue
        url = urljoin(page_url, href)
        if not same_site(urlparse(url).netloc, host) or "/view/" in url or url in (u for _, u in found):
            continue
        rank = next((i for i, rx in enumerate(MENU_PRIORITY) if rx.search(text)), len(MENU_PRIORITY))
        found.append((rank, url))
    found.sort(key=lambda x: x[0])  # 안정 정렬이라 같은 순위 안에서는 페이지 순서 유지
    return [u for _, u in found][:limit]


def scan_site(site: dict, deadline: float | None = None) -> dict:
    """누리집 하나를 읽는다. site: {"code","name","region","url","kind"} (kind: school | office)"""
    url = fix_url(site["url"])
    kind = site.get("kind", "school")
    if not url:
        return {"site": site, "status": "no_url", "items": [], "boards": 0}
    if deadline is not None and time.monotonic() > deadline:
        return {"site": site, "status": "skipped", "items": [], "boards": 0}
    try:
        pages = load_home(url)
        items = []
        menus: list[str] = []
        for page_url, soup in pages:
            items += site_items(page_url, soup)
            menus += [m for m in hiring_menus(page_url, soup, kind) if m not in menus]
        boards = 0
        for menu_url in menus[:MAX_MENUS[kind]]:
            try:
                board_url, text = get_html(menu_url)
                items += site_items(board_url, BeautifulSoup(text, "html.parser"))
                boards += 1
            except Exception:  # noqa: BLE001  메뉴 하나 실패는 무시
                pass
        return {"site": site, "status": "ok", "items": items, "boards": boards}
    except Exception as exc:  # noqa: BLE001
        return {"site": site, "status": "fail", "items": [], "boards": 0, "error": short_error(exc)}


def is_hiring(title: str) -> bool:
    return bool(HIRE_STRONG_RE.search(title) or (HIRE_WEAK_RE.search(title) and STAFF_RE.search(title)))


def classify_site_title(title: str, kind: str = "school") -> str | None:
    """누리집 글 제목 판정. match: 미술 채용 / unspecified: 과목 없는 신규교사 채용 / exam: 중등 임용시험 글(교육청만)"""
    if not is_hiring(title):
        return None
    if any(k in title for k in KEYWORDS):
        return "match"
    if REGULAR_RE.search(title) and TEACHER_RE.search(title) and not any(w in title for w in SUBJECT_WORDS):
        return "unspecified"
    if kind == "office" and GOSI_EXAM_RE.search(title) and GOSI_TEACHER_RE.search(title):
        if GOSI_EXCLUDE_RE.search(title) and not SECONDARY_RE.search(title):
            return None
        if re.search(r"임용후보자|임용시험|임용 시험|선정경쟁|시행계획|사전 ?예고|시행 ?공고", title):
            return "exam"
    return None


classify_school_title = classify_site_title  # 예전 이름


def site_label(site: dict) -> str:
    return f"[{site['region']}] {site['name']}"


def format_site_message(kind: str, title: str, url: str, names: list[str], site_kind: str = "school",
                        note: str = "") -> str:
    e = html.escape
    where = "사립학교 홈페이지" if site_kind == "school" else "교육(지원)청 누리집"
    icon = "🏫" if site_kind == "school" else "🏢"
    if kind == "match":
        head = f"{icon}🎨 <b>{where} 미술 채용 글</b>"
    elif kind == "exam":
        head = f"{icon}📢 <b>{where} 중등 임용시험 글</b>"
    else:
        head = f"{icon}🟡 <b>{where} 교사 채용 글</b> — 과목 미기재, 미술 있는지 확인"
    body = f'{e(" · ".join(names))}\n{e(title)}' + (f"\n({e(note)})" if note else "")
    return f'{head}\n{body}\n<a href="{e(url, quote=True)}">글 열기</a>'


format_school_message = format_site_message  # 예전 이름


def load_school_list(api_key: str, state: dict, today: date) -> list[dict]:
    """사립 중·고 목록. 일주일에 한 번 나이스에서 새로 받고, 실패하면 저장된 목록을 쓴다."""
    cache = state.get("schools", {})
    regions = list(NEIS_OFFICES.values())
    fresh = (
        cache.get("updated")
        and cache.get("regions") == regions  # 감시 지역이 바뀌면 바로 새로 받음
        and (today - date.fromisoformat(cache["updated"])).days < SCHOOL_LIST_REFRESH_DAYS
    )
    schools = cache.get("list", [])
    if not fresh:
        try:
            schools = fetch_school_list(api_key)
            state["schools"] = {"updated": today.isoformat(), "regions": regions, "list": schools}
        except Exception as exc:  # noqa: BLE001
            if not schools:
                raise
            print(f"[사립학교 목록] 새로 받기 실패, 저장된 목록 사용: {exc}", file=sys.stderr)
    for s in schools:
        s.setdefault("region", "전북")
        s.setdefault("kind", "")
    return schools


def run_site_scan(sites: list[dict], site_kind: str, state: dict, today: date) -> dict:
    """누리집 목록을 훑고 결과를 돌려준다: alerts, ok/failed/no_url/skipped 목록, with_board 수, healthy."""
    deadline = time.monotonic() + SITE_SCAN_BUDGET_SEC
    with ThreadPoolExecutor(max_workers=SITE_WORKERS) as pool:
        results = list(pool.map(lambda s: scan_site({**s, "kind": site_kind}, deadline), sites))

    seen = set(state["seen"].get("school", []))
    scanned_before = set(state.get("schools_scanned", []))
    year_marks = (str(today.year), str(today.year + 1))
    found: dict[str, dict] = {}
    newly_seen: list[str] = []
    for res in results:
        if res["status"] != "ok":
            continue
        site = res["site"]
        first_time = site["code"] not in scanned_before
        for item in res["items"]:
            if item["id"] in seen:
                continue
            kind = classify_site_title(item["title"], site_kind)
            if (kind in (None, "unspecified")) and item.get("detail") and needs_detail(item["title"]):
                kind = "detail"  # 제목만으로 과목을 모름 → 글을 열어 본다 (아래)
            if not kind:
                continue
            newly_seen.append(item["id"])
            if first_time and (kind in ("unspecified", "detail") or not any(y in item["title"] for y in year_marks)):
                continue  # 처음 보는 누리집은 올해·내년 글만 알림 (옛 글 폭탄 방지)
            entry = found.setdefault(item["id"], {**item, "kind": kind, "names": [], "note": ""})
            if site_label(site) not in entry["names"]:
                entry["names"].append(site_label(site))
        scanned_before.add(site["code"])

    pending = [v for v in found.values() if v["kind"] == "detail"]
    if pending:
        resolved = resolve_many([v["url"] for v in pending])
        for v in pending:
            v["kind"], v["note"] = resolved[v["url"]]
    found = {k: v for k, v in found.items() if v["kind"]}

    state["schools_scanned"] = sorted(scanned_before)
    state["seen"]["school"] = list(dict.fromkeys(newly_seen + state["seen"].get("school", [])))[:MAX_SEEN_SCHOOL]

    ok = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "fail"]
    no_url = [r for r in results if r["status"] == "no_url"]
    skipped = [r for r in results if r["status"] == "skipped"]
    label = "사립학교" if site_kind == "school" else "교육청"
    for r in failed:
        print(f"[{label}] {site_label(r['site'])} 접속 실패: {r.get('error')}", file=sys.stderr)
    for r in no_url:
        print(f"[{label}] {site_label(r['site'])} 홈페이지 주소 없음", file=sys.stderr)
    if skipped:
        print(f"[{label}] 시간 부족으로 {len(skipped)}곳 건너뜀", file=sys.stderr)
    return {
        "alerts": [
            format_site_message(v["kind"], v["title"], v["url"], v["names"], site_kind, v.get("note", ""))
            for v in found.values()
        ],
        "ok": ok, "failed": failed, "no_url": no_url, "skipped": skipped,
        "with_board": sum(1 for r in ok if r["boards"]),
        "healthy": len(ok) >= max(1, len(sites) // 2) and not skipped,
    }


def region_counts(sites: list[dict]) -> str:
    counts: dict[str, int] = {}
    for s in sites:
        counts[s["region"]] = counts.get(s["region"], 0) + 1
    return ", ".join(f"{r} {n}" for r, n in counts.items())


def run_school_scan(api_key: str, state: dict, today: date) -> tuple[list[str], str, str | None, bool]:
    """사립학교 홈페이지를 확인하고 (알림 목록, 상태 한 줄, 첫 확인 요약, 정상 여부)를 돌려준다."""
    schools = load_school_list(api_key, state, today)
    r = run_site_scan(schools, "school", state, today)
    ok, failed, no_url, skipped = r["ok"], r["failed"], r["no_url"], r["skipped"]

    status = f"사립 중·고 홈페이지: {len(schools)}곳 중 {len(ok)}곳 확인 (채용 메뉴 {r['with_board']}곳)"
    if skipped:
        status += f" — 시간 부족으로 {len(skipped)}곳 건너뜀"
    elif not r["healthy"]:
        status += " — 절반 넘게 접속 실패"

    summary = None
    if state.get("school_summary_regions") != list(NEIS_OFFICES.values()):  # 처음이거나 감시 지역이 바뀌었을 때
        state["school_summary_sent"] = today.isoformat()
        state["school_summary_regions"] = list(NEIS_OFFICES.values())
        middle = sum(1 for s in schools if s["kind"] == "중학교")
        names = ", ".join(site_label(x["site"]) for x in failed[:15]) + (" 외" if len(failed) > 15 else "")
        summary = (
            "🏫 <b>사립 중·고 홈페이지 첫 확인</b>\n"
            f"대상 {len(schools)}곳 (중 {middle}, 고 {len(schools) - middle}; {region_counts(schools)})\n"
            f"정상 {len(ok)}곳 · 채용 메뉴 찾음 {r['with_board']}곳\n"
            f"접속 실패 {len(failed)}곳" + (f": {html.escape(names)}" if failed else "") + "\n"
            f"홈페이지 주소 없음 {len(no_url)}곳\n"
            + (f"시간 부족으로 건너뜀 {len(skipped)}곳\n" if skipped else "")
            + "이후로는 매일 아침 한 번 확인합니다."
        )
    if r["healthy"]:
        state["school_scan_date"] = today.isoformat()  # 실패가 많으면 저녁에 다시 시도
    return r["alerts"], status, summary, r["healthy"]


def run_office_scan(state: dict, today: date) -> tuple[list[str], str, str | None, bool]:
    """교육청·교육지원청 누리집을 확인하고 (알림 목록, 상태 한 줄, 첫 확인 요약, 정상 여부)를 돌려준다."""
    r = run_site_scan(OFFICE_SITES, "office", state, today)
    ok, failed, skipped = r["ok"], r["failed"], r["skipped"]
    status = f"교육청·교육지원청 누리집: {len(OFFICE_SITES)}곳 중 {len(ok)}곳 확인 (채용 메뉴 {r['with_board']}곳)"
    if skipped:
        status += f" — 시간 부족으로 {len(skipped)}곳 건너뜀"
    elif not r["healthy"]:
        status += " — 절반 넘게 접속 실패"
    summary = None
    if not state.get("office_summary_sent"):
        state["office_summary_sent"] = today.isoformat()
        names = ", ".join(site_label(x["site"]) for x in failed[:15]) + (" 외" if len(failed) > 15 else "")
        summary = (
            "🏢 <b>교육청·교육지원청 누리집 첫 확인</b>\n"
            f"대상 {len(OFFICE_SITES)}곳 ({region_counts(OFFICE_SITES)})\n"
            f"정상 {len(ok)}곳 · 채용 메뉴 찾음 {r['with_board']}곳\n"
            f"접속 실패 {len(failed)}곳" + (f": {html.escape(names)}" if failed else "") + "\n"
            "이후로는 매번(아침·저녁) 확인합니다."
        )
    return r["alerts"], status, summary, r["healthy"]


# ─────────────────────────── 글 본문·첨부파일 확인 ───────────────────────────
# 제목에 과목이 없는 교사 채용 글은 글을 열어 본문과 첨부파일(hwp·hwpx·pdf·docx·xlsx)에서 과목을 찾는다.
#   '미술'이 나오면 🎨, 다른 과목이 분명하면 알리지 않고, 못 읽거나 알 수 없으면 🟡로 보낸다.
MAX_DETAILS_PER_RUN = 40          # 한 번 실행에 열어 볼 글 수 (넘으면 🟡로 보냄)
MAX_ATTACHMENTS = 3               # 글마다 읽을 첨부파일 수
MAX_ATTACHMENT_BYTES = 8_000_000  # 이보다 큰 파일은 읽지 않음
DOC_EXT_RE = re.compile(r"\.(hwpx?|pdf|docx?|xlsx?|pptx?|zip|jpe?g|png|gif|tiff?|bmp)(?=$|[?#\s])", re.I)
ATTACH_HREF_RE = re.compile(r"download|filedown|file_down|/down/|attach|atch|/files?/|upload|getfile|fileid|filesid", re.I)
NOT_TEACHER_RE = re.compile(r"공무직|조리|행정|시설|돌봄|방과후|초등|유치원|특수학교|자원봉사|지킴이")
_SUBJECTS = "|".join(sorted((w for w in SUBJECT_WORDS if w != "담임"), key=len, reverse=True))
# 본문·첨부에서 '다른 과목이 분명하다'고 볼 표현. 안내문의 흔한 말('개인정보', '교육정보과')에 걸리지 않게 앞뒤를 제한한다.
SUBJECT_STRICT_RE = re.compile(
    rf"(?<![가-힣])(?:{_SUBJECTS})\s*(?:과(?![가-힣])|교사|교원|기간제|강사|전담|\d+\s*명)"
    rf"|[(\[/·,]\s*(?:{_SUBJECTS})\s*[)\]/·,]"
    rf"|(?:과목|교과|분야|전공)\s*[:：]?\s*(?:{_SUBJECTS})(?![가-힣])"
)


def needs_detail(title: str) -> bool:
    """제목만으로는 과목을 알 수 없는 교사 채용 글인지."""
    return bool(
        is_hiring(title) and STAFF_RE.search(title)
        and not any(k in title for k in KEYWORDS)
        and not any(w in title for w in SUBJECT_WORDS)
        and not NOT_TEACHER_RE.search(title)
    )


def main_text(soup: BeautifulSoup) -> str:
    """글 상세 페이지에서 메뉴·머리글을 빼고 본문으로 보이는 덩어리를 고른다 (링크가 적고 글이 긴 블록)."""
    for t in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
        t.decompose()
    best, best_len = None, 0
    for block in soup.find_all(["article", "section", "div", "td"]):
        if len(block.find_all("a")) > 5:
            continue
        text = norm(block.get_text(" "))
        if len(text) > best_len:
            best, best_len = text, len(text)
    return best if best is not None else norm(soup.get_text(" "))


def attachment_links(page_url: str, soup: BeautifulSoup) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        label = norm(a.get_text(" ")) or norm(a.get("title", ""))
        if not (DOC_EXT_RE.search(label) or DOC_EXT_RE.search(href) or ATTACH_HREF_RE.search(href)):
            continue
        url = urljoin(page_url, href)
        if any(url == u for _, u in found):
            continue
        name = re.sub(r"\s*(다운로드|내려받기|새창으로 열림|문서보기)\s*", " ", label).strip() or url.rsplit("/", 1)[-1]
        found.append((name, url))
    return found


def read_detail(url: str) -> dict:
    final_url, text = get_html(url)
    soup = BeautifulSoup(text, "html.parser")
    attachments = attachment_links(final_url, soup)
    return {"text": main_text(soup), "attachments": attachments}


def get_bytes(url: str, timeout: int = SITE_HTTP_TIMEOUT) -> tuple[str, bytes]:
    """첨부파일을 내려받아 (파일 이름, 내용)을 돌려준다. 너무 크면 빈 내용."""
    headers = dict(SESSION.headers)
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(url, headers=headers, timeout=timeout, stream=True, verify=False)
    resp.raise_for_status()
    name = ""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", resp.headers.get("Content-Disposition", ""), re.I)
    if m:
        from urllib.parse import unquote
        name = unquote(m.group(1)).strip()
    chunks, total = [], 0
    for chunk in resp.iter_content(65536):
        total += len(chunk)
        if total > MAX_ATTACHMENT_BYTES:
            return name, b""
        chunks.append(chunk)
    return name, b"".join(chunks)


def xml_text(xml: bytes | str) -> str:
    if isinstance(xml, bytes):
        xml = xml.decode("utf-8", "ignore")
    return norm(html.unescape(re.sub(r"<[^>]+>", " ", xml)))


def zip_text(data: bytes) -> str | None:
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if any(n.startswith("Contents/section") for n in names):          # hwpx
                parts = sorted(n for n in names if n.startswith("Contents/section") and n.endswith(".xml"))
            elif "word/document.xml" in names:                                 # docx
                parts = ["word/document.xml"] + [n for n in names if re.match(r"word/(header|footer)\d*\.xml", n)]
            elif any(n.startswith("xl/") for n in names):                      # xlsx
                parts = [n for n in names if n == "xl/sharedStrings.xml" or n.startswith("xl/worksheets/sheet")]
            elif any(n.startswith("ppt/slides/slide") for n in names):         # pptx
                parts = sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml", n))
            else:
                return None
            return "\n".join(xml_text(z.read(n)) for n in parts)
    except (zipfile.BadZipFile, KeyError):
        return None


def hwp_para_text(b: bytes) -> str:
    """HWP 문단 텍스트(UTF-16LE + 제어문자)에서 글자만 꺼낸다."""
    out, i, n = [], 0, len(b) // 2
    while i < n:
        c = int.from_bytes(b[2 * i:2 * i + 2], "little")
        if c in (10, 13):
            out.append("\n")
        elif 1 <= c <= 23:
            i += 7  # 표·그림 같은 확장 제어문자는 8글자를 차지한다
        elif c < 32:
            out.append(" ")
        else:
            out.append(chr(c))
        i += 1
    return "".join(out)


def hwp_section_text(raw: bytes) -> str:
    """HWP BodyText 섹션(압축 푼 상태)의 레코드를 훑어 문단 텍스트를 모은다."""
    out, pos = [], 0
    while pos + 4 <= len(raw):
        header = int.from_bytes(raw[pos:pos + 4], "little")
        pos += 4
        tag, size = header & 0x3FF, (header >> 20) & 0xFFF
        if size == 0xFFF:
            size = int.from_bytes(raw[pos:pos + 4], "little")
            pos += 4
        if tag == 67:  # HWPTAG_PARA_TEXT
            out.append(hwp_para_text(raw[pos:pos + size]))
        pos += size
    return "\n".join(out)


def hwp_text(data: bytes) -> str | None:
    """한글(HWP 5.0) 파일 본문. 암호·배포용 문서는 못 읽는다(None)."""
    import zlib

    import olefile
    if not olefile.isOleFile(data):
        return None
    ole = olefile.OleFileIO(data)
    if not ole.exists("FileHeader"):
        return None  # doc·xls 같은 다른 OLE 파일
    flags = int.from_bytes(ole.openstream("FileHeader").read()[36:40], "little")
    if flags & 2 or flags & 4:
        return None  # 암호화 / 배포용
    sections = sorted(
        (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
        key=lambda e: int(re.sub(r"\D", "", e[1]) or 0),
    )
    texts = []
    for entry in sections:
        raw = ole.openstream(entry).read()
        if flags & 1:
            raw = zlib.decompress(raw, -15)
        texts.append(hwp_section_text(raw))
    return "\n".join(texts)


def pdf_text(data: bytes) -> str | None:
    import io
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        return None
    return "\n".join((page.extract_text() or "") for page in reader.pages[:10])


def extract_text(data: bytes) -> str | None:
    """첨부파일 내용에서 글자를 꺼낸다. 파일 종류는 내용으로 알아낸다. 못 읽으면 None."""
    if not data:
        return None
    try:
        if data[:4] == b"\xd0\xcf\x11\xe0":
            return hwp_text(data)
        if data[:2] == b"PK":
            return zip_text(data)
        if data[:5] == b"%PDF-":
            return pdf_text(data)
    except Exception as exc:  # noqa: BLE001  깨진 파일 등
        print(f"[첨부파일] 읽기 실패: {short_error(exc)}", file=sys.stderr)
    return None


def resolve_by_detail(url: str) -> tuple[str | None, str]:
    """글을 열어 (판정, 설명)을 돌려준다. 판정: match / None(다른 과목) / unspecified(알 수 없음)."""
    try:
        page = read_detail(url)
    except Exception as exc:  # noqa: BLE001
        return "unspecified", f"글을 열지 못함({short_error(exc)}) — 직접 확인"
    names = " ".join(n for n, _ in page["attachments"])
    if any(k in page["text"] for k in KEYWORDS):
        return "match", "본문에 미술"
    if any(k in names for k in KEYWORDS):
        return "match", "첨부파일 이름에 미술"
    texts, unread = [page["text"]], []
    for name, aurl in page["attachments"][:MAX_ATTACHMENTS]:
        try:
            real_name, data = get_bytes(aurl)
            text = extract_text(data)
        except Exception:  # noqa: BLE001
            text = None
        if text is None:
            unread.append(name)
            continue
        if any(k in text for k in KEYWORDS):
            return "match", f"첨부 「{name}」에 미술"
        texts.append(text)
    found = SUBJECT_STRICT_RE.search(" ".join(texts))
    if found and not unread:
        return None, f"다른 과목({norm(found.group(0))})"
    if unread:
        return "unspecified", f"첨부 「{unread[0]}」를 읽지 못함 — 직접 확인"
    if not page["attachments"]:
        return "unspecified", "과목이 적혀 있지 않음 — 직접 확인"
    return "unspecified", "첨부에서 과목을 찾지 못함 — 직접 확인"


def resolve_many(urls: list[str]) -> dict[str, tuple[str | None, str]]:
    """여러 글을 한꺼번에 연다. 한도(MAX_DETAILS_PER_RUN)를 넘는 글은 🟡로 둔다."""
    urls = list(dict.fromkeys(urls))
    todo, rest = urls[:MAX_DETAILS_PER_RUN], urls[MAX_DETAILS_PER_RUN:]
    with ThreadPoolExecutor(max_workers=SITE_WORKERS) as pool:
        results = dict(zip(todo, pool.map(resolve_by_detail, todo)))
    for u in rest:
        results[u] = ("unspecified", "확인할 글이 많아 열어 보지 못함 — 직접 확인")
    return results


# ─────────────────────────── 알림·상태 ───────────────────────────
def send_telegram(token: str, chat_ids: list[str], text: str) -> None:
    """메시지 하나를 모든 채팅에 보낸다. 전송 제한(429)·서버 오류(5xx)는 잠시 기다렸다가 다시 시도한다."""
    for chat_id in chat_ids:
        for attempt in range(TELEGRAM_RETRIES):
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                },
                timeout=20,
            )
            if resp.ok:
                break
            if resp.status_code == 429 or resp.status_code >= 500:
                try:
                    wait = int(resp.json().get("parameters", {}).get("retry_after", 0))
                except ValueError:
                    wait = 0
                time.sleep(max(wait, 3))
                continue
            raise RuntimeError(f"텔레그램 전송 실패({chat_id}): {resp.status_code} {resp.text[:200]}")
        else:
            raise RuntimeError(f"텔레그램 전송 실패({chat_id}): {resp.status_code} {resp.text[:200]}")
        time.sleep(1)  # 텔레그램 전송 제한(채팅당 초당 1건, 그룹은 분당 20건) 대비


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ─────────────────────────── 실행 ───────────────────────────
def main() -> int:
    dry_run = "--dry-run" in sys.argv
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not dry_run and (not token or not chat_ids):
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없습니다. 테스트는 --dry-run 으로 실행하세요.")
        return 1

    now = datetime.now(KST)
    today = now.date()
    state = load_state()
    state.setdefault("seen", {})
    state.setdefault("fails", {})

    alerts: list[str] = []
    status_lines: list[str] = []
    errors: list[str] = []
    is_initial = "started" not in state

    for key, board in BOARDS.items():
        first_run = key not in state["seen"]
        try:
            rows, note = read_board(board)
        except Exception as exc:  # noqa: BLE001
            state["fails"][key] = state["fails"].get(key, 0) + 1
            status_lines.append(f"❌ {board['name']}: {exc}")
            if state["fails"][key] >= FAILS_BEFORE_ALERT:
                errors.append(f"{board['name']} {state['fails'][key]}회 연속 실패: {exc}")
            print(f"[{board['name']}] 실패: {exc}", file=sys.stderr)
            continue

        state["fails"][key] = 0
        status_lines.append(f"✅ {board['name']}: 글 {len(rows)}건 읽음{note}")
        seen = set(state["seen"].get(key, []))
        candidates = []
        for row in reversed(rows):  # 오래된 글부터 보내기
            if row["id"] in seen:
                continue
            kind = classify(key, row)
            if kind and (not first_run or is_recent(key, row, kind, today)):
                candidates.append([row, kind, ""])
        # 과목이 안 적힌 사전공개 글은 글을 열어 본문·첨부파일에서 과목을 찾는다
        to_open = [c for c in candidates if key == "preplan" and c[1] == "unspecified"]
        if to_open:
            resolved = resolve_many([c[0]["url"] for c in to_open])
            for c in to_open:
                c[1], c[2] = resolved[c[0]["url"]]
        alerts.extend(format_message(key, row, kind, note) for row, kind, note in candidates if kind)
        current_ids = [r["id"] for r in rows]
        current_set = set(current_ids)
        older_ids = [i for i in dict.fromkeys(state["seen"].get(key, [])) if i not in current_set]
        state["seen"][key] = (current_ids + older_ids)[:MAX_SEEN_PER_BOARD]

    # 교육청·교육지원청 누리집 (매번) + 사립 중·고 홈페이지 (하루 한 번)
    summaries: list[str] = []

    def run_scan(label: str, key: str, runner) -> None:
        try:
            scan_alerts, scan_status, scan_summary, healthy = runner()
            if scan_summary:
                summaries.append(scan_summary)
            alerts.extend(scan_alerts)
            if not healthy:
                raise RuntimeError(scan_status.split(": ", 1)[-1])
            state["fails"][key] = 0
            status_lines.append(f"✅ {scan_status}")
        except Exception as exc:  # noqa: BLE001
            state["fails"][key] = state["fails"].get(key, 0) + 1
            status_lines.append(f"❌ {label}: {exc}")
            if state["fails"][key] >= FAILS_BEFORE_ALERT:
                errors.append(f"{label} {state['fails'][key]}회 연속 실패: {exc}")
            print(f"[{label}] 실패: {exc}", file=sys.stderr)

    if "--no-offices" not in sys.argv:
        run_scan("교육청·교육지원청 누리집", "office", lambda: run_office_scan(state, today))

    neis_key = os.environ.get("NEIS_API_KEY", "").strip()
    if not neis_key:
        status_lines.append("⏸ 사립 중·고 홈페이지: NEIS_API_KEY 없음(건너뜀)")
    elif state.get("school_scan_date") == today.isoformat() and "--force-schools" not in sys.argv:
        status_lines.append("⏭ 사립 중·고 홈페이지: 오늘 이미 확인함")
    else:
        run_scan("사립 중·고 홈페이지", "school", lambda: run_school_scan(neis_key, state, today))

    outgoing: list[str] = []
    if is_initial:
        state["started"] = now.isoformat()
        outgoing.append(
            "✅ <b>미술 티오 알리미 시작</b>\n"
            + "\n".join(html.escape(s) for s in status_lines)
            + f"\n키워드: {html.escape(', '.join(KEYWORDS))}"
            + f"\n최근 {FIRST_RUN_LOOKBACK_DAYS}일 안의 관련 글 {len(alerts)}건을 이어서 보냅니다."
        )
    outgoing.extend(summaries)
    outgoing.extend(alerts)

    if errors:
        last = state.get("last_error_alert")
        due = not last or now - datetime.fromisoformat(last) >= timedelta(hours=ERROR_ALERT_INTERVAL_HOURS)
        if due:
            outgoing.append(
                "⚠️ <b>알리미 점검 필요</b>\n"
                + "\n".join(html.escape(x) for x in errors)
                + f"\n(이 경고는 {ERROR_ALERT_INTERVAL_HOURS}시간에 한 번만 보냅니다)"
            )
            state["last_error_alert"] = now.isoformat()

    print(f"{now:%Y-%m-%d %H:%M} KST | " + " | ".join(status_lines) + f" | 알림 {len(alerts)}건")

    if dry_run:
        for msg in outgoing:
            print("\n----- 보낼 메시지 -----\n" + msg)
        print("\n(--dry-run: 발송·저장 안 함)")
        return 0

    try:
        for msg in outgoing:
            send_telegram(token, chat_ids, msg)
    except Exception as exc:  # noqa: BLE001
        # 발송에 실패하면 상태를 저장하지 않아 다음 실행 때 다시 보낸다.
        print(exc, file=sys.stderr)
        return 1

    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
