"""기본 용어집 시드 데이터 (§3.3, T-22).

빈 상태로 두면 아무도 채우지 않아 기능이 죽는다는 이유로, 프로그래밍 수업에서 흔히 오인식되는
기술 용어 100개를 전역(`course=None`) 용어집으로 시드한다. `aliases`는 Whisper 한국어 STT가
실제로 잘못 인식하는 흔한 패턴을 반영한 것이며, 완벽한 목록이 아니라 출발점이다 — 사용자가
API로 계속 보강해 나가는 것을 전제로 한다.

이 모듈은 애플리케이션 코드(`app/api/v1/glossary.py`)와 Alembic 마이그레이션 양쪽에서
공유하는 순수 데이터다. ORM 모델을 import하지 않는다 — 마이그레이션이 특정 시점의 데이터
스키마에 결합되지 않게 하기 위해서다 (마이그레이션에서는 이 데이터를 얕은 테이블 정의에
`bulk_insert`한다).
"""

from __future__ import annotations

from typing import TypedDict


class GlossarySeedTerm(TypedDict):
    term: str
    aliases: list[str]
    course: str | None


DEFAULT_GLOSSARY_TERMS: list[GlossarySeedTerm] = [
    {"term": "PostgreSQL", "aliases": ["포스트그레스큐엘", "포스트그레"], "course": None},
    {"term": "MySQL", "aliases": ["마이 에스큐엘", "마이신큐엘"], "course": None},
    {"term": "MongoDB", "aliases": ["몽고디비", "몽고 디비"], "course": None},
    {"term": "Redis", "aliases": ["레디스", "래디스"], "course": None},
    {"term": "SQLite", "aliases": ["에스큐엘라이트", "시퀄라이트"], "course": None},
    {"term": "GitHub", "aliases": ["긴 허브", "깃 허브"], "course": None},
    {"term": "GitLab", "aliases": ["깃 랩", "기트랩"], "course": None},
    {"term": "Git", "aliases": ["기트", "깃트"], "course": None},
    {"term": "Docker", "aliases": ["도커", "도우커"], "course": None},
    {"term": "Kubernetes", "aliases": ["쿠버네티스", "쿠버네티즈"], "course": None},
    {"term": "JavaScript", "aliases": ["자바스크립트", "자바 스크립트"], "course": None},
    {"term": "TypeScript", "aliases": ["타입스크립트", "타입 스크립트"], "course": None},
    {"term": "Python", "aliases": ["파이썬", "파이슨"], "course": None},
    {"term": "Java", "aliases": ["자바"], "course": None},
    {"term": "Kotlin", "aliases": ["코틀린", "코트린"], "course": None},
    {"term": "Node.js", "aliases": ["노드제이에스", "노드 js", "노드제이"], "course": None},
    {"term": "React", "aliases": ["리액트", "리엑트"], "course": None},
    {"term": "Vue.js", "aliases": ["뷰제이에스", "뷰 js"], "course": None},
    {"term": "Angular", "aliases": ["앵귤러", "앵귤라"], "course": None},
    {"term": "Express", "aliases": ["익스프레스", "익스프래스"], "course": None},
    {"term": "FastAPI", "aliases": ["패스트에이피아이", "패스트 API"], "course": None},
    {"term": "Django", "aliases": ["장고", "쟝고"], "course": None},
    {"term": "Spring Boot", "aliases": ["스프링부트", "스프링 붓"], "course": None},
    {"term": "HTML", "aliases": ["에이치티엠엘"], "course": None},
    {"term": "CSS", "aliases": ["씨에스에스"], "course": None},
    {"term": "DOM", "aliases": ["돔"], "course": None},
    {"term": "API", "aliases": ["에이피아이", "에이피"], "course": None},
    {"term": "REST", "aliases": ["레스트", "레스티"], "course": None},
    {"term": "JSON", "aliases": ["제이슨", "제이슨포맷"], "course": None},
    {"term": "XML", "aliases": ["엑스엠엘"], "course": None},
    {"term": "SQL", "aliases": ["에스큐엘", "시퀄"], "course": None},
    {"term": "NoSQL", "aliases": ["노에스큐엘", "노시퀄"], "course": None},
    {"term": "ORM", "aliases": ["오알엠"], "course": None},
    {"term": "CRUD", "aliases": ["크러드", "씨알유디"], "course": None},
    {"term": "HTTP", "aliases": ["에이치티티피"], "course": None},
    {"term": "HTTPS", "aliases": ["에이치티티피에스"], "course": None},
    {"term": "TCP", "aliases": ["티씨피"], "course": None},
    {"term": "UDP", "aliases": ["유디피"], "course": None},
    {"term": "DNS", "aliases": ["디엔에스"], "course": None},
    {"term": "URL", "aliases": ["유알엘"], "course": None},
    {"term": "URI", "aliases": ["유알아이"], "course": None},
    {"term": "IP", "aliases": ["아이피"], "course": None},
    {"term": "쿼리", "aliases": ["코리", "퀴리"], "course": None},
    {"term": "조인", "aliases": ["존", "조잉"], "course": None},
    {"term": "트랜잭션", "aliases": ["트랜젝션", "트렌젝션"], "course": None},
    {"term": "인덱스", "aliases": ["인덱쓰", "인덱시"], "course": None},
    {"term": "정규화", "aliases": ["정규화하다"], "course": None},
    {"term": "알고리즘", "aliases": ["알고리듬"], "course": None},
    {"term": "자료구조", "aliases": ["자료 구조"], "course": None},
    {"term": "배열", "aliases": ["어레이"], "course": None},
    {"term": "링크드리스트", "aliases": ["링크드 리스트", "링크트리스트"], "course": None},
    {"term": "스택", "aliases": ["스텍"], "course": None},
    {"term": "큐", "aliases": ["큐우"], "course": None},
    {"term": "트리", "aliases": ["트리이"], "course": None},
    {"term": "그래프", "aliases": ["그레프"], "course": None},
    {"term": "해시맵", "aliases": ["해쉬맵", "해쉬 맵"], "course": None},
    {"term": "해시", "aliases": ["해쉬"], "course": None},
    {"term": "이진 탐색 트리", "aliases": ["비에스티", "비 에스 티"], "course": None},
    {"term": "이진 탐색", "aliases": ["바이너리 서치"], "course": None},
    {"term": "정렬", "aliases": ["소트"], "course": None},
    {"term": "재귀", "aliases": ["리커전"], "course": None},
    {"term": "포인터", "aliases": ["포인타"], "course": None},
    {"term": "널 포인터", "aliases": ["눌 포인터", "눌포인터"], "course": None},
    {"term": "컴파일러", "aliases": ["콤파일러"], "course": None},
    {"term": "인터프리터", "aliases": ["인터프리타"], "course": None},
    {"term": "런타임", "aliases": ["런 타임"], "course": None},
    {"term": "프레임워크", "aliases": ["프레임 워크"], "course": None},
    {"term": "라이브러리", "aliases": ["라이브라리"], "course": None},
    {"term": "패키지", "aliases": ["팩키지"], "course": None},
    {"term": "모듈", "aliases": ["모쥴"], "course": None},
    {"term": "클래스", "aliases": ["클라스"], "course": None},
    {"term": "인터페이스", "aliases": ["인터페이쓰"], "course": None},
    {"term": "상속", "aliases": [], "course": None},
    {"term": "다형성", "aliases": ["폴리모피즘"], "course": None},
    {"term": "캡슐화", "aliases": [], "course": None},
    {"term": "추상화", "aliases": [], "course": None},
    {"term": "람다", "aliases": ["람다식"], "course": None},
    {"term": "클로저", "aliases": ["클로져"], "course": None},
    {"term": "비동기", "aliases": ["에이싱크"], "course": None},
    {"term": "콜백", "aliases": ["콜 백"], "course": None},
    {"term": "프로미스", "aliases": ["프라미스"], "course": None},
    {"term": "이벤트 루프", "aliases": ["이벤트루프"], "course": None},
    {"term": "스레드", "aliases": ["쓰레드"], "course": None},
    {"term": "프로세스", "aliases": ["프로세쓰"], "course": None},
    {"term": "데드락", "aliases": ["데드 락"], "course": None},
    {"term": "뮤텍스", "aliases": ["뮤텍쓰"], "course": None},
    {"term": "세마포어", "aliases": ["세마포"], "course": None},
    {"term": "캐시", "aliases": ["캐쉬"], "course": None},
    {"term": "버퍼", "aliases": ["버퍼링"], "course": None},
    {"term": "소켓", "aliases": ["쏘켓"], "course": None},
    {"term": "쿠키", "aliases": ["쿠기"], "course": None},
    {"term": "토큰", "aliases": ["토우큰"], "course": None},
    {"term": "JWT", "aliases": ["제이더블유티"], "course": None},
    {"term": "OAuth", "aliases": ["오오스", "오어스"], "course": None},
    {"term": "SSL", "aliases": ["에스에스엘"], "course": None},
    {"term": "TLS", "aliases": ["티엘에스"], "course": None},
    {"term": "정규표현식", "aliases": ["레지엑스", "정규식"], "course": None},
    {"term": "유니코드", "aliases": ["유니 코드"], "course": None},
    {"term": "UTF-8", "aliases": ["유티에프8", "유티에프에잇"], "course": None},
    {"term": "오버플로우", "aliases": ["오버 플로우"], "course": None},
]
