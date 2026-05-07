# 브라이트비드 오피스 (Brightbeed Office)

브라이트비드 내부 운영용 웹 대시보드.
중국 발주, ERP 연동, 사내 자료 관리를 하나의 화면에서 다룬다.

> **라이브 URL** · https://j65209.github.io/Brightbeed/
> **저장소** · https://github.com/j65209/Brightbeed

---

## 1. 프로젝트 개요

- **이름** · 브라이트비드 오피스 (Brightbeed Office)
- **목적** · 중국 발주 + 사내 운영 데이터를 한 화면에서 보고/관리
- **호스팅** · GitHub Pages (main 브랜치 / root)
- **보안** · 6자리 PIN + IP 화이트리스트 (브라우저 localStorage 기억)

## 2. 접속

| 항목 | 값 |
|---|---|
| URL | https://j65209.github.io/Brightbeed/ |
| PIN | `670200` |
| 자동 통과 IP | `110.11.178.25` |
| 저장 키 | `brightbeed_unlocked` (localStorage) |

PIN을 한 번 입력하면 해당 브라우저는 다음부터 자동 통과한다.
다른 컴퓨터에서 작업할 때는 PIN `670200`을 한 번만 넣으면 된다.

## 3. 폴더 구조

```
Brightbeed/
├── index.html       메인 대시보드 (잠금화면 + 본문 단일 파일)
├── README.md        본 문서
└── .gitignore       Python 기본 ignore
```

현재는 단일 `index.html` 구조다. 모듈이 늘어나면
`/orders`, `/inventory`, `/erp` 같이 하위 페이지로 분리한다.

## 4. 다른 컴퓨터에서 작업 재개하기

### 방법 A · GitHub 웹 에디터에서 바로 수정 (가장 간단)

1. https://github.com/j65209/Brightbeed 접속 후 로그인
2. `index.html` 클릭 → 우상단 연필 아이콘
3. 수정 후 `Commit changes`
4. 1~2분 뒤 라이브 사이트에 자동 반영 (GitHub Pages 빌드)

### 방법 B · Claude에게 맡기기 (권장)

새 대화창에서 아래 한 줄을 보내면 이 프로젝트를 바로 이어서 작업한다.

> **"브라이트비드 오피스 수정하자: github.com/j65209/Brightbeed"**

Claude가 저장소 상태를 읽고 이 README를 기준으로 작업을 이어간다.

### 방법 C · 로컬에서 클론

```bash
git clone https://github.com/j65209/Brightbeed.git
cd Brightbeed
# index.html 수정 후
git add . && git commit -m "수정 내용" && git push
```

## 5. 현재 기능 (v0.4)

- 잠금화면 (PIN + IP 화이트리스트)
- 다크 + 골드 액센트 기업용 디자인
- 한글 UI 전체 적용
- 핵심지표 4종 (진행중 발주 / 운송중 / 이번 달 발주액 / 동기화 대기)
- 액션 버튼 (ERP 최신화 · 발주서 가져오기 · 구글 시트 열기 · 드롭박스 열기 · 내보내기)
- 최근 발주 내역 테이블 (확정 · 입고 완료 · 운송중 · 작성중 상태 배지)
- 행별 "상세" 토글 (공급사 / 품목 / 도착예정 / 비고)

## 6. 향후 작업 (TODO)

- [ ] 드롭박스 발주서(`MM.DD 발주서.xlsx`) 자동 파싱 → 구글 시트 연동
- [ ] ERP 최신화 버튼 실연동 (사용 ERP 미정)
- [ ] 발주서 업로드 기능 (드래그&드롭)
- [ ] 사내 멤버 추가 (PIN별 권한 분리 검토)
- [ ] 모바일 화면 추가 최적화
- [ ] 사내 다른 모듈 추가 (재고 / 매출 / 일정 등)

## 7. 작업 이력

| 버전 | 날짜 | 내용 |
|---|---|---|
| v0.1 | 2025-05-07 | 초기 HTML 대시보드 |
| v0.2 | 2025-05-07 | PIN + IP 화이트리스트 추가 |
| v0.3 | 2025-05-07 | 다크 모드 + 기업용 고급 디자인 리뉴얼 |
| v0.4 | 2025-05-07 | 한글 UI 전체 전환, 명칭을 "브라이트비드 오피스"로 확정 |

## 8. 보안 메모

- 저장소는 **Public** 이지만 PIN 잠금으로 일반인 접근을 차단
- API 키, 토큰, 비밀번호 등 민감 정보는 **절대 commit 금지**
- 외부 연동 시(드롭박스/구글/ERP) 토큰은 GitHub Secrets 또는 별도 백엔드로 분리
- PIN 노출 우려가 생기면 `index.html` 상단 `PIN` 상수만 바꿔서 commit

---

© 2025 브라이트비드 · 내부 사용 전용
