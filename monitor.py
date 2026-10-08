#!/usr/bin/env python3
"""전북 미술 교사 티오 알리미

전북특별자치도교육청 게시판 3곳을 읽어서 미술 관련 새 글을 텔레그램으로 보냅니다.

  1) 기간제교사 인력풀 > 채용공고         과목/분야에 '미술'이 있으면 알림
  2) 기간제교사 인력풀 > 채용계획 사전공개  제목·첨부파일명에 '미술'이 있으면 알림
                                          과목이 안 적힌 중등 글은 '확인 필요'로 알림
  3) 도교육청 > 중등임용시험 게시판         새 글은 모두 알림 (공립 + 사립 위탁 채용)
  4) 전북 사립 중·고 홈페이지 (하루 1번)    첫 화면과 '채용' 메뉴에서 미술 채용 글을 찾음
                                          학교 목록은 나이스 교육정보 개방포털에서 자동으로 받음

환경변수
  TELEGRAM_BOT_TOKEN  텔레그램 봇 토큰
  TELEGRAM_CHAT_ID    받을 채팅 ID (여러 개면 쉼표로 구분)
  NEIS_API_KEY        나이스 교육정보 개방포털 인증키 (없으면 4번은 건너뜀)

실행
  python monitor.py                  실제 실행 (알림 발송 + seen.json 저장)
  python monitor.py --dry-run        알림 내용만 화면에 출력하고 저장하지 않음
  python monitor.py --force-schools  오늘 이미 확인했어도 사립학교 홈페이지를 다시 확인
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

POOL_LIST = "https://www.jbe.go.kr/pool/board/list.jbe"
BOARDS = {
    "recruit": {
        "name": "기간제 채용공고",
        "urls": [
            f"{POOL_LIST}?boardId=BBS_0000130&menuCd=DOM_000001601002000000"
            f"&listRow=50&listCel=1&paging=ok&searchOperation=AND&startPage={page}"
            for page in (1, 2, 3)  # 12시간 사이 올라온 글을 놓치지 않도록 최근 150건
        ],
    },
    "preplan": {
        "name": "채용계획 사전공개",
        "urls": [
            f"{POOL_LIST}?boardId=BBS_0000123&menuCd=DOM_000001601001000000"
            f"&listRow=50&listCel=1&paging=ok&searchOperation=AND&startPage={page}"
            for page in (1, 2)  # 최근 100건
        ],
    },
    "exam": {
        "name": "중등임용시험 게시판",
        # 도교육청 누리집 > 알림마당 > 시험/채용/구직 > 중등임용시험
        "urls": ["https://www.jbe.go.kr/index.jbe?menuCd=DOM_000000103004002000"],
        "expect_title": "중등임용",
    },
}

# 사립 중·고 홈페이지
NEIS_URL = "https://open.neis.go.kr/hub/schoolInfo"
NEIS_OFFICE_CODE = "P10"          # 전북특별자치도교육청
SCHOOL_KINDS = {"중학교", "고등학교"}
SCHOOL_LIST_REFRESH_DAYS = 7      # 학교 목록(폐교·통합 반영)을 며칠마다 새로 받을지
SCHOOL_WORKERS = 5                # 동시에 여는 홈페이지 수
SCHOOL_MAX_BOARDS = 3             # 학교마다 따라 들어갈 '채용' 메뉴 수
MAX_SEEN_SCHOOL = 3000

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
    raise RuntimeError(f"접속 실패: {last_error}")


def parse_page(page_html: str, base_url: str) -> tuple[str, list[dict]]:
    """목록 페이지에서 게시글 행을 뽑는다. 게시글 링크(dataSid)를 기준으로 찾는다."""
    soup = BeautifulSoup(page_html, "html.parser")
    page_title = norm(soup.title.get_text()) if soup.title else ""
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


def format_message(board_key: str, row: dict, kind: str) -> str:
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
        body = f"{e(row['title'])}\n작성: {e(cell(row, 2))} {e(cell(row, 3))}"
    else:
        head = "📢 <b>중등임용시험 게시판 새 글</b>"
        if kind == "match":
            head += " (미술 언급)"
        body = e(row["title"])
    return f'{head}\n{body}\n<a href="{e(row["url"], quote=True)}">공고 열기</a>'


# ─────────────────────────── 사립 중·고 홈페이지 ───────────────────────────
HIRE_STRONG_RE = re.compile(r"채용|공개전형|초빙|임용")
HIRE_WEAK_RE = re.compile(r"모집|공고")
STAFF_RE = re.compile(r"교사|교원|강사|기간제|계약제")
REGULAR_RE = re.compile(r"신규|정규|공개전형")
TEACHER_RE = re.compile(r"교사|교원")
JS_REDIRECT_RE = re.compile(
    r"location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]|location\.replace\(\s*['\"]([^'\"]+)['\"]"
)


def get_html(url: str, timeout: int = 15) -> tuple[str, str]:
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
    """나이스 교육정보 개방포털에서 전북 사립 중·고 목록과 홈페이지 주소를 받는다."""
    schools, page = [], 1
    while True:
        data = neis_get({
            "KEY": api_key, "Type": "json", "pIndex": page, "pSize": 1000,
            "ATPT_OFCDC_SC_CODE": NEIS_OFFICE_CODE, "FOND_SC_NM": "사립",
        })
        if "schoolInfo" not in data:
            result = data.get("RESULT", {})
            if result.get("CODE") == "INFO-200" and page > 1:
                break
            raise RuntimeError(f"나이스 응답 오류 {result.get('CODE')}: {result.get('MESSAGE')}")
        rows = data["schoolInfo"][1]["row"]
        for r in rows:
            if r.get("FOND_SC_NM") == "사립" and r.get("SCHUL_KND_SC_NM") in SCHOOL_KINDS:
                schools.append({
                    "code": r.get("SD_SCHUL_CODE", ""),
                    "name": r.get("SCHUL_NM", ""),
                    "kind": r.get("SCHUL_KND_SC_NM", ""),
                    "url": (r.get("HMPG_ADRES") or "").strip(),
                })
        if len(rows) < 1000:
            break
        page += 1
    if not schools:
        raise RuntimeError("나이스에서 사립 중·고를 한 곳도 받지 못함")
    return sorted(schools, key=lambda x: (x["kind"], x["name"]))


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


def school_items(page_url: str, soup: BeautifulSoup) -> list[dict]:
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
        items.append({"id": hashlib.sha1(key.encode()).hexdigest()[:16], "title": title, "url": link})
    return items


def hiring_menus(page_url: str, soup: BeautifulSoup) -> list[str]:
    host = urlparse(page_url).netloc
    urls = []
    for a in soup.find_all("a", href=True):
        text, href = norm(a.get_text(" ")), a["href"].strip()
        if "채용" not in text or len(text) > 20 or href.startswith(("#", "javascript:")):
            continue
        url = urljoin(page_url, href)
        if urlparse(url).netloc == host and "/view/" not in url and url not in urls:
            urls.append(url)
    return urls[:SCHOOL_MAX_BOARDS]


def scan_school(school: dict) -> dict:
    url = fix_url(school["url"])
    if not url:
        return {"school": school, "status": "no_url", "items": [], "boards": 0}
    try:
        pages = load_home(url)
        items = []
        menus: list[str] = []
        for page_url, soup in pages:
            items += school_items(page_url, soup)
            menus += [m for m in hiring_menus(page_url, soup) if m not in menus]
        boards = 0
        for menu_url in menus[:SCHOOL_MAX_BOARDS]:
            try:
                board_url, text = get_html(menu_url)
                items += school_items(board_url, BeautifulSoup(text, "html.parser"))
                boards += 1
            except Exception:  # noqa: BLE001  메뉴 하나 실패는 무시
                pass
        return {"school": school, "status": "ok", "items": items, "boards": boards}
    except Exception as exc:  # noqa: BLE001
        return {"school": school, "status": "fail", "items": [], "boards": 0, "error": str(exc)[:120]}


def is_hiring(title: str) -> bool:
    return bool(HIRE_STRONG_RE.search(title) or (HIRE_WEAK_RE.search(title) and STAFF_RE.search(title)))


def classify_school_title(title: str) -> str | None:
    if not is_hiring(title):
        return None
    if any(k in title for k in KEYWORDS):
        return "match"
    if REGULAR_RE.search(title) and TEACHER_RE.search(title) and not any(w in title for w in SUBJECT_WORDS):
        return "unspecified"
    return None


def format_school_message(kind: str, title: str, url: str, names: list[str]) -> str:
    e = html.escape
    if kind == "match":
        head = "🏫🎨 <b>사립학교 홈페이지 미술 채용 글</b>"
    else:
        head = "🏫🟡 <b>사립학교 신규교사 채용 글</b> — 과목 미기재, 미술 있는지 확인"
    return f'{head}\n{e(" · ".join(names))}\n{e(title)}\n<a href="{e(url, quote=True)}">글 열기</a>'


def run_school_scan(api_key: str, state: dict, today: date) -> tuple[list[str], str, str | None, bool]:
    """사립학교 홈페이지를 확인하고 (알림 목록, 상태 한 줄, 첫 확인 요약, 정상 여부)를 돌려준다."""
    cache = state.get("schools", {})
    fresh = cache.get("updated") and (
        today - date.fromisoformat(cache["updated"])
    ).days < SCHOOL_LIST_REFRESH_DAYS
    schools = cache.get("list", [])
    if not fresh:
        try:
            schools = fetch_school_list(api_key)
            state["schools"] = {"updated": today.isoformat(), "list": schools}
        except Exception as exc:  # noqa: BLE001
            if not schools:
                raise
            print(f"[사립학교 목록] 새로 받기 실패, 저장된 목록 사용: {exc}", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=SCHOOL_WORKERS) as pool:
        results = list(pool.map(scan_school, schools))

    seen = set(state["seen"].get("school", []))
    scanned_before = set(state.get("schools_scanned", []))
    year_marks = (str(today.year), str(today.year + 1))
    found: dict[str, dict] = {}
    newly_seen: list[str] = []
    for res in results:
        if res["status"] != "ok":
            continue
        school = res["school"]
        first_time = school["code"] not in scanned_before
        for item in res["items"]:
            if item["id"] in seen:
                continue
            kind = classify_school_title(item["title"])
            if not kind:
                continue
            newly_seen.append(item["id"])
            if first_time and (kind != "match" or not any(y in item["title"] for y in year_marks)):
                continue  # 처음 보는 학교는 올해·내년 미술 채용 글만 알림 (옛 글 폭탄 방지)
            entry = found.setdefault(item["id"], {**item, "kind": kind, "names": []})
            if school["name"] not in entry["names"]:
                entry["names"].append(school["name"])
        scanned_before.add(school["code"])

    state["schools_scanned"] = sorted(scanned_before)
    state["seen"]["school"] = list(dict.fromkeys(newly_seen + state["seen"].get("school", [])))[:MAX_SEEN_SCHOOL]

    ok = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "fail"]
    no_url = [r for r in results if r["status"] == "no_url"]
    with_board = sum(1 for r in ok if r["boards"])
    for r in failed:
        print(f"[사립학교] {r['school']['name']} 접속 실패: {r.get('error')}", file=sys.stderr)
    for r in no_url:
        print(f"[사립학교] {r['school']['name']} 홈페이지 주소 없음", file=sys.stderr)

    healthy = len(ok) >= max(1, len(schools) // 2)
    status = f"사립 중·고 홈페이지: {len(schools)}곳 중 {len(ok)}곳 확인 (채용 메뉴 {with_board}곳)"
    if not healthy:
        status += " — 절반 넘게 접속 실패"

    summary = None
    if not state.get("school_summary_sent"):
        state["school_summary_sent"] = today.isoformat()
        middle = sum(1 for s in schools if s["kind"] == "중학교")
        names = ", ".join(r["school"]["name"] for r in failed[:15]) + (" 외" if len(failed) > 15 else "")
        summary = (
            "🏫 <b>사립 중·고 홈페이지 첫 확인</b>\n"
            f"대상 {len(schools)}곳 (중 {middle}, 고 {len(schools) - middle})\n"
            f"정상 {len(ok)}곳 · 채용 메뉴 찾음 {with_board}곳\n"
            f"접속 실패 {len(failed)}곳" + (f": {html.escape(names)}" if failed else "") + "\n"
            f"홈페이지 주소 없음 {len(no_url)}곳\n"
            "이후로는 매일 아침 한 번 확인합니다."
        )
    if healthy:
        state["school_scan_date"] = today.isoformat()  # 실패가 많으면 저녁에 다시 시도
    alerts = [format_school_message(v["kind"], v["title"], v["url"], v["names"]) for v in found.values()]
    return alerts, status, summary, healthy


# ─────────────────────────── 알림·상태 ───────────────────────────
def send_telegram(token: str, chat_ids: list[str], text: str) -> None:
    for chat_id in chat_ids:
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
        if not resp.ok:
            raise RuntimeError(f"텔레그램 전송 실패({chat_id}): {resp.status_code} {resp.text[:200]}")
        time.sleep(0.5)


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
            rows: list[dict] = []
            for url in board["urls"]:
                page_title, page_rows = parse_page(fetch(url), url)
                expect = board.get("expect_title")
                if expect and expect not in page_title:
                    raise RuntimeError(f"다른 게시판이 열림(페이지 제목: {page_title[:60]}) — 주소 확인 필요")
                known = {r["id"] for r in rows}
                rows.extend(r for r in page_rows if r["id"] not in known)  # 페이지 간 중복 제거
                time.sleep(1)
            if not rows:
                raise RuntimeError("게시글을 하나도 못 읽음 — 사이트 구조가 바뀌었을 수 있음")
        except Exception as exc:  # noqa: BLE001
            state["fails"][key] = state["fails"].get(key, 0) + 1
            status_lines.append(f"❌ {board['name']}: {exc}")
            if state["fails"][key] >= FAILS_BEFORE_ALERT:
                errors.append(f"{board['name']} {state['fails'][key]}회 연속 실패: {exc}")
            print(f"[{board['name']}] 실패: {exc}", file=sys.stderr)
            continue

        state["fails"][key] = 0
        status_lines.append(f"✅ {board['name']}: 글 {len(rows)}건 읽음")
        seen = set(state["seen"].get(key, []))
        for row in reversed(rows):  # 오래된 글부터 보내기
            if row["id"] in seen:
                continue
            kind = classify(key, row)
            if kind and (not first_run or is_recent(key, row, kind, today)):
                alerts.append(format_message(key, row, kind))
        current_ids = [r["id"] for r in rows]
        current_set = set(current_ids)
        older_ids = [i for i in dict.fromkeys(state["seen"].get(key, [])) if i not in current_set]
        state["seen"][key] = (current_ids + older_ids)[:MAX_SEEN_PER_BOARD]

    # 사립 중·고 홈페이지 (하루 한 번)
    school_alerts: list[str] = []
    school_summary = None
    neis_key = os.environ.get("NEIS_API_KEY", "").strip()
    if not neis_key:
        status_lines.append("⏸ 사립 중·고 홈페이지: NEIS_API_KEY 없음(건너뜀)")
    elif state.get("school_scan_date") == today.isoformat() and "--force-schools" not in sys.argv:
        status_lines.append("⏭ 사립 중·고 홈페이지: 오늘 이미 확인함")
    else:
        try:
            school_alerts, school_status, school_summary, healthy = run_school_scan(neis_key, state, today)
            if not healthy:
                raise RuntimeError(school_status.split(": ", 1)[-1])
            state["fails"]["school"] = 0
            status_lines.append(f"✅ {school_status}")
        except Exception as exc:  # noqa: BLE001
            state["fails"]["school"] = state["fails"].get("school", 0) + 1
            status_lines.append(f"❌ 사립 중·고 홈페이지: {exc}")
            if state["fails"]["school"] >= FAILS_BEFORE_ALERT:
                errors.append(f"사립 중·고 홈페이지 {state['fails']['school']}회 연속 실패: {exc}")
            print(f"[사립 중·고 홈페이지] 실패: {exc}", file=sys.stderr)
    alerts.extend(school_alerts)

    outgoing: list[str] = []
    if is_initial:
        state["started"] = now.isoformat()
        outgoing.append(
            "✅ <b>미술 티오 알리미 시작</b>\n"
            + "\n".join(html.escape(s) for s in status_lines)
            + f"\n키워드: {html.escape(', '.join(KEYWORDS))}"
            + f"\n최근 {FIRST_RUN_LOOKBACK_DAYS}일 안의 관련 글 {len(alerts)}건을 이어서 보냅니다."
        )
    if school_summary:
        outgoing.append(school_summary)
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
