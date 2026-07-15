# Meta 마케팅 API 정식 발급 매뉴얼

> 목적: **본인 소유의 페이스북 광고 계정** 실적을 정당한 방법으로 프로그램에서 조회.
> 소요 시간: 처음이면 20~30분. 재발급은 5분.
> 위험도: **0** — 공식 API. 계정 잠금·차단·의심 로그인 알림 발생하지 않음.

---

## 준비물

시작 전에 아래 3개가 있어야 합니다.

| 항목 | 확인 방법 |
|---|---|
| ① 페이스북 개인 계정 (관리자 권한 소유자) | 이미 광고 집행하는 계정 그대로 |
| ② 페이스북 비즈니스 관리자 (Business Manager) | https://business.facebook.com 접속해서 조직이 잡혀있으면 OK |
| ③ 광고 계정 (Ad Account) 최소 1개 + 관리자 권한 | Business Manager → 광고 계정 목록에 뜨는지 확인 |

**② Business Manager가 없다면 먼저 만들기 (5분):**
1. https://business.facebook.com 접속 → "계정 만들기"
2. 회사명(브라이트비드), 본인 이름, 업무 이메일 입력 → 인증 메일 확인
3. 왼쪽 메뉴 "비즈니스 설정" → "광고 계정" → "추가" → 기존 광고 계정 연결

---

## Step 1. Meta for Developers 앱 생성

1. https://developers.facebook.com 접속 → 우상단 **로그인** (준비물 ①의 개인 계정)
2. 최초 로그인이면 **"개발자 등록"** 클릭 → 휴대폰 SMS 인증 → 완료
3. 우상단 **내 앱** → **앱 만들기** 클릭
4. **앱 유형 선택** 화면에서 반드시 **"비즈니스 (Business)"** 선택 → **다음**
   - ⚠️ 다른 유형(소비자/게이밍 등)은 Marketing API 못 붙임
5. 앱 정보 입력:
   - **앱 이름**: `Brightbeed Marketing API` (아무거나. 나중에 변경 가능)
   - **앱 이메일**: 본인 이메일
   - **비즈니스 계정**: 위에서 만든 브라이트비드 Business Manager 선택
6. **앱 만들기** → 비밀번호 재입력 → 대시보드 진입

---

## Step 2. Marketing API 제품 추가

1. 방금 만든 앱 대시보드 왼쪽 메뉴 → **제품 추가** 섹션
2. **Marketing API** 카드에서 **설정** 클릭
3. 새로 생긴 왼쪽 메뉴 **Marketing API → 시작하기** 클릭
4. 사용 사례 3개 체크박스 모두 체크:
   - ☑ 광고 관리
   - ☑ 광고 인사이트 읽기
   - ☑ 광고 계정 정보 읽기
5. **저장**

이 시점의 앱은 **개발 모드 (Development)** 상태입니다.
→ **본인 소유의 광고 계정**에 대해서는 개발 모드에서도 **모든 데이터 조회 가능**합니다.
→ 다른 사람의 광고 계정에 접근하려면 앱 심사(App Review)가 필요하지만, **우리는 브라이트비드 자체 광고만 볼 거니까 심사 안 받아도 됩니다.**

---

## Step 3. 광고 계정 ID 확보

API 호출에 계정 ID가 필요합니다.

1. https://business.facebook.com/settings/ad-accounts 접속
2. 조회하고 싶은 광고 계정 클릭
3. 우측 패널에 **"광고 계정 ID"** 15자리 숫자 표시됨 (예: `123456789012345`)
4. **API 호출 시엔 앞에 `act_` 붙여서 사용**: `act_123456789012345`

**여러 계정을 다룰 거면** 각각 ID를 메모해 두세요.

---

## Step 4. 액세스 토큰 발급 — 3단계 (60초 → 60일 → 무기한)

Marketing API는 액세스 토큰이 필수. 만료 기간에 따라 3종류.

### 4-A. 단기 토큰 발급 (60초짜리 — 테스트용, 1분 안에 4-B로 넘어가야 함)

1. https://developers.facebook.com/tools/explorer 접속 (Graph API Explorer)
2. 우측 상단 **Meta App** 드롭다운 → 방금 만든 앱 선택
3. 그 아래 **User or Page** → **Get User Access Token** 클릭
4. **권한(Permissions)** 창에서 아래 3개 체크:
   - ☑ `ads_read`
   - ☑ `ads_management`
   - ☑ `business_management`
5. **Generate Access Token** → 페이스북 로그인 팝업 뜨면 확인 → 앱 권한 승인
6. 상단 **Access Token** 필드에 `EAAxxxxx…` 긴 문자열 생김 → **복사**

### 4-B. 장기 토큰 변환 (60일짜리)

터미널에서 다음 3개 값을 준비:
- `SHORT_TOKEN` = 4-A에서 복사한 토큰
- `APP_ID` = 앱 대시보드 상단 좌측의 **앱 ID** (16자리 숫자)
- `APP_SECRET` = 앱 대시보드 → **설정 → 기본 설정 → 앱 시크릿 코드 → 표시** (비밀번호 재입력 필요)

```bash
curl -s "https://graph.facebook.com/v20.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id=APP_ID&\
client_secret=APP_SECRET&\
fb_exchange_token=SHORT_TOKEN"
```

응답 JSON의 `access_token` 값이 60일짜리 장기 토큰. **잘 저장해 두기.**

### 4-C. 시스템 사용자 토큰 발급 (무기한 — 서버 자동화용, 최종 목표)

60일마다 갱신하기 귀찮으니 **무기한 토큰** 만들기:

1. https://business.facebook.com/settings/system-users 접속
2. **추가** 클릭 → 이름 `brightbeed-marketing-bot` → 역할 `관리자` (또는 최소권한 `직원`)
3. 생성된 시스템 사용자 클릭 → **자산 할당** → **광고 계정** → Step 3에서 확인한 계정 선택 → 권한 **광고 관리** (또는 **광고 성과 보기**만 필요하면 그것만)
4. **자산 할당** 다시 → **앱** → Step 1에서 만든 앱 선택 → **개발** 권한 부여
5. 상단 **새 토큰 생성** 클릭:
   - **앱** = Step 1 앱 선택
   - **토큰 만료** = **만료 없음** ✅
   - **권한**: `ads_read`, `ads_management`, `business_management` 3개 체크
6. **토큰 생성** → 팝업에 뜨는 `EAA…` 문자열이 **무기한 액세스 토큰**
   - ⚠️ **팝업 닫으면 다시 못 봄** — 즉시 복사해서 안전한 곳(1Password, config.env 등)에 저장

**이게 최종 토큰입니다.** 서버 코드에는 이 토큰만 넣으면 됨.

---

## Step 5. API 호출 테스트

터미널에서 성과 좋은 광고 TOP 10 뽑아보기:

```bash
TOKEN="EAA...위에서 발급받은 무기한 토큰..."
AD_ACCOUNT="act_123456789012345"

# 최근 30일 광고별 성과 (지출 순 정렬)
curl -s "https://graph.facebook.com/v20.0/${AD_ACCOUNT}/insights?\
level=ad&\
date_preset=last_30d&\
fields=ad_id,ad_name,campaign_name,adset_name,spend,impressions,clicks,ctr,cpc,cpm,reach,frequency,actions,action_values,cost_per_action_type&\
sort=spend_descending&\
limit=10&\
access_token=${TOKEN}" | python3 -m json.tool
```

응답 예시 (일부):
```json
{
  "data": [
    {
      "ad_id": "23851234567890123",
      "ad_name": "CH.alban Ring - 여름 캠페인",
      "campaign_name": "SILVER925 리마케팅",
      "spend": "342500.00",
      "impressions": "128456",
      "clicks": "3421",
      "ctr": "2.66",
      "cpc": "100.12",
      "actions": [
        {"action_type": "purchase", "value": "47"},
        {"action_type": "add_to_cart", "value": "312"}
      ]
    }
  ]
}
```

성과 기준을 바꾸려면:
- **ROAS 순**: `fields`에 `purchase_roas` 추가 → 응답에서 클라이언트 정렬
- **구매수 순**: 응답의 `actions` 배열에서 `action_type=purchase`인 `value` 기준 정렬
- **CTR 순**: `sort=ctr_descending`
- **기간 변경**: `date_preset=last_7d` / `last_90d` / `today` / `yesterday` — 또는 `time_range={"since":"2026-06-01","until":"2026-06-30"}`

크리에이티브(이미지/영상 URL)까지 뽑으려면:
```bash
curl -s "https://graph.facebook.com/v20.0/{ad_id}?\
fields=creative{image_url,video_id,thumbnail_url,object_story_spec}&\
access_token=${TOKEN}"
```

---

## Step 6. 서버에 토큰 심기 (브라이트비드 프록시 통합 시)

**절대 클라이언트(대시보드)에 토큰 노출 금지.** 반드시 서버 프록시 통해서만 호출.

`~/server/brightbeed-proxy/config.env`에 추가:
```
META_MARKETING_TOKEN=EAA...무기한토큰...
META_AD_ACCOUNT_6A=act_123456789012345
META_AD_ACCOUNT_CT=act_234567890123456
META_AD_ACCOUNT_YAR=act_345678901234567
```

이후 프록시에 `/meta/*` 라우트 추가하면 대시보드에서 마케팅팀 뷰에 "광고 성과 TOP 10" 패널 붙일 수 있습니다.

---

## 자주 걸리는 문제

| 증상 | 원인 · 해결 |
|---|---|
| `(#100) Tried accessing nonexisting field` | `fields=` 파라미터 오타. Meta는 콤마 뒤 공백 있으면 에러 |
| `(#294) Requires ads_management permission` | 토큰 권한 부족. Step 4-C 다시, 권한 3개 다 체크 |
| `(#17) User request limit reached` | 요청 과다. 잠깐 쉬거나 batch 요청 활용. 자기 계정 조회는 여유로움 |
| `(#200) Requires app review` | 다른 사람 광고 계정 조회 시. 자기 계정만 볼 거면 절대 안 뜸 |
| 토큰 조회 → `Session has expired` | 60일 지난 4-B 토큰. Step 4-C로 무기한 토큰 만들기 |
| 시스템 사용자에서 광고 계정 안 보임 | Step 4-C-3에서 자산 할당 놓침. 다시 |

---

## 참고 링크

- [Meta Business Manager](https://business.facebook.com/)
- [Meta for Developers](https://developers.facebook.com/)
- [Graph API Explorer](https://developers.facebook.com/tools/explorer)
- [Marketing API 공식 문서](https://developers.facebook.com/docs/marketing-apis/)
- [Insights API 필드 목록](https://developers.facebook.com/docs/marketing-api/insights/parameters/v20.0)
- [Rate Limits](https://developers.facebook.com/docs/graph-api/overview/rate-limiting)

---

**작성**: 2026-07-15
**용도**: 브라이트비드 페이스북 광고 성과를 대시보드 마케팅팀 뷰에 연동하기 위한 사전 세팅
