---
title: "실무 중심 비동기 Apex 완전 정복: @future 한계부터 Queueable 체이닝, Batch Apex 주의점까지"
description: "왜 실무에서 @future 대신 Queueable을 써야 할까? 체이닝 불가 에러 해결부터 Queueable 연쇄 실행, Batch Apex 청크 사이즈 및 Stateful 힙 메모리 함정까지 현업 코드로 정리합니다."
date: 2026-11-25 16:05:00 +0900
categories: ["Salesforce", "Apex"]
tags: ["asynchronous-apex", "queueable", "batch-apex", "future", "governor-limits", "salesforce"]
mermaid: true
toc: true
---

## 서론: 동기(Trigger)만으로는 해결 안 되는 3가지 실무 순간

[지난 1편 포스트](/posts/salesforce-apex-trigger-framework-best-practices/)에서 다룬 것처럼 `Trigger`와 `Handler`를 아무리 깔끔하게 Bulkification 해두더라도, 프로젝트를 진행하다 보면 **동기(Synchronous) 트랜잭션 안에서는 절대 처리할 수 없는 벽**을 마주치게 됩니다.

실무에서 비동기(Asynchronous) Apex를 꺼내 들어야 하는 대표적인 상황은 딱 3가지입니다.

1. **트리거에서 외부 시스템 API(Callout)를 호출해야 할 때**
   - 고객이나 주문 레코드가 저장된 직후 ERP나 알림톡/Slack API를 호출하려고 트리거 안에서 `Http.send()`를 실행하면 곧바로 아래 에러가 터집니다.
   ```text
   System.CalloutException: Callout from triggers are currently not supported.
   ```
   - 설령 일반 클래스에서 호출하더라도 같은 트랜잭션 안에서 DML(`insert`/`update`)을 먼저 실행한 직후 Callout을 날리면 유명한 `You have uncommitted work pending` 에러가 발생합니다.
2. **처리할 데이터가 10,000건(DML 한도) / 50,000건(SOQL 조회 한도)을 넘어갈 때**
   - 야간 정산이나 마이그레이션처럼 수십만~수백만 건의 레코드를 한 번에 돌려야 할 때는 트랜잭션을 여러 개로 쪼개서 돌리는 배치가 필수입니다.
3. **사용자 화면 응답 속도(UX) 확보**
   - 저장 버튼을 눌렀는데 복잡한 집계 연산 때문에 화면 로딩 스피너가 5~10초씩 돌면 현업 사용자 불만이 바로 접수됩니다. 당장 화면에 보여줄 필요 없는 후속 작업은 비동기 백그라운드로 넘겨야 합니다.

이번 글에서는 비동기 Apex 4종 세트(`@future`, `Queueable`, `Batch`, `Schedulable`) 중 **왜 요즘 실무에서 `@future` 대신 `Queueable`이 표준이 되었는지(체이닝 문제 포함)**와, **`Batch Apex` 운영 시 가장 자주 터지는 실전 함정**들을 정리합니다.

---

## 1. 한눈에 보는 비동기 Apex 4종 선택 기준

먼저 어떤 상황에 무엇을 써야 하는지 실무 기준으로 딱 정해두고 시작하겠습니다.

```mermaid
flowchart TD
    A["비동기 처리 필요"] --> B{"처리할 데이터 건수가 수만~수백만 건인가?"}
    B -- "Yes (대용량 배치)" --> C["Batch Apex (Database.Batchable)"]
    B -- "No (단건 ~ 수천 건)" --> D{"매일/매시간 정해진 시각에 실행해야 하는가?"}
    D -- "Yes (스케줄링)" --> E["Scheduled Apex + 내부에서 Batch/Queueable 호출"]
    D -- "No (즉시 백그라운드 실행)" --> F{"복잡한 객체 전달이나 후속 작업 연결(체이닝)이 필요한가?"}
    F -- "Yes (실무 기본 추천)" --> G["Queueable Apex (System.enqueueJob)"]
    F -- "No (단순 ID 전달 단발성)" --> H["@future (레거시 유지보수 외엔 Queueable 권장)"]
```

| 구분 | `@future` | `Queueable Apex` (실무 주력) | `Batch Apex` | `Scheduled Apex` |
| :--- | :--- | :--- | :--- | :--- |
| **파라미터 전달** | 원시 타입만 가능 (`Set<Id>`, `String` 등) | **`List<SObject>`, 커스텀 DTO 클래스 모두 가능** | 생성자로 모두 전달 가능 | 생성자/멤버 변수 활용 |
| **연쇄 실행 (Chaining)** | **불가 ❌** (`@future` 안에서 `@future` 호출 에러) | **가능 ⭕** (`execute` 안에서 다음 Job 연결) | **가능 ⭕** (`finish`에서 다음 Batch/Queueable 연결) | 스케줄 등록용 |
| **작업 추적 (Job ID)** | 불가 (`void` 반환) | **`Id` 반환** (`AsyncApexJob` 조회 가능) | **`Id` 반환** | **`Id` 반환** |
| **주요 용도** | 아주 단순한 비동기 처리 (과거 코드) | **트리거 후속 API 연동, 순차 비동기 파이프라인** | **1만 건 이상 대용량 데이터 일괄 처리** | 야간/주기적 자동 실행 |

---

## 2. 왜 실무에서 `@future`를 쓰면 발목이 잡힐까? (체이닝 불가와 배치 충돌)

예전 Salesforce 프로젝트 코드를 보면 어노테이션 한 줄(`@future(callout=true)`)만 붙이면 끝나는 간편함 때문에 `@future`를 정말 많이 썼습니다. 하지만 실무 요건이 조금만 복잡해지면 **치명적인 2가지 벽**에 부딪힙니다.

### 함정 1) `@future` 안에서는 다른 `@future`를 부를 수 없다 (체이닝 불가!)

예를 들어 외부 시스템 연동 시 **"1차로 토큰 발급/고객 등록 API를 쏘고 → 성공하면 이어서 2차로 주문 상세 API를 쏘는 작업"**을 연결(Chaining)하고 싶을 때, `@future` 메서드 안에서 또 다른 `@future` 메서드를 호출하면 즉시 아래 예외가 발생합니다.

```text
System.AsyncException: Future method cannot be called from a future or batch method
```

### 함정 2) 야간 `Batch`가 돌 때 트리거 안의 `@future`가 터진다!

현업에서 가장 흔하게 겪는 장애 시나리오입니다.
1. 개발자 A가 `OrderTriggerHandler`에서 주문 수정 시 ERP로 전송하려고 `@future` 메서드를 호출하게 만들어 두었습니다. (화면에서 저장할 땐 아주 잘 돌아갑니다!)
2. 몇 달 뒤 개발자 B가 야간에 미정산 주문을 일괄 업데이트하는 **`Batch Apex`**를 만들어 돌렸습니다.
3. 배치가 주문을 `update` 하는 순간 `OrderTrigger`가 실행되고, 이미 배치(비동기) 컨텍스트인데 그 안에서 `@future`를 호출하면서 **`Future method cannot be called from a future or batch method` 에러와 함께 야간 배치가 통째로 실패**합니다.

```apex
// ⚠️ 과거 @future 사용 시 어쩔 수 없이 덕지덕지 붙이던 방어 코드
if (!System.isFuture() && !System.isBatch()) {
    LegacyErpService.sendOrderFuture(orderIds); // 배치에서 돌 땐 아예 스킵되어 데이터 누락 위험!
}
```

게다가 `@future`는 파라미터로 `List<Order>` 같은 SObject 리스트나 직접 만든 Wrapper 클래스를 넘길 수 없어서, 굳이 `Set<Id>`만 넘겨서 다시 SOQL로 조회하거나 `JSON.serialize()`로 문자열로 변환해 넘기는 번거로운 꼼수를 써야 했습니다.

---

## 3. 실무 표준 해결사: `Queueable Apex`와 안전한 체이닝 패턴

위에서 겪은 `@future`의 모든 단점을 해결하기 위해 나온 상위 호환이 바로 **`Queueable` 인터페이스**입니다. 현업에서 새로 비동기 로직을 짠다면 특별한 이유가 없는 한 `@future` 대신 무조건 `Queueable`로 작성하는 것이 좋습니다.

### ✅ 실전 예제: 1차 연동 후 2차 후속 작업을 체이닝(Chaining)하는 `Queueable`

```apex
/**
 * @description 주문 생성/수정 후 외부 ERP 연동 및 후속 알림 작업을 처리하는 Queueable 클래스
 */
public class OrderErpSyncQueueable implements Queueable, Database.AllowsCallouts {

    private List<Order> targetOrders;

    // 1. @future와 달리 생성자를 통해 SObject 리스트나 커스텀 DTO를 그대로 받을 수 있음!
    public OrderErpSyncQueueable(List<Order> targetOrders) {
        this.targetOrders = targetOrders;
    }

    public void execute(QueueableContext context) {
        // 실패 복구 및 에러 로깅을 위한 Finalizer 부착 (선택적이지만 실무 강추!)
        System.attachFinalizer(new ErpSyncFinalizer(this.targetOrders));

        // 2. 외부 ERP API Callout 실행 (별도 비동기 트랜잭션이므로 DML 이후여도 안전)
        Http http = new Http();
        HttpRequest req = new HttpRequest();
        req.setEndpoint('callout:ERP_Named_Credential/api/v1/orders');
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setBody(JSON.serialize(this.targetOrders));

        HttpResponse res = http.send(req);
        if (res.getStatusCode() != 200) {
            throw new CalloutException('ERP 전송 실패: Status ' + res.getStatusCode());
        }

        // 3. 연동 완료 상태 DB 반영
        List<Order> ordersToUpdate = new List<Order>();
        for (Order ord : this.targetOrders) {
            ordersToUpdate.add(new Order(Id = ord.Id, Description = 'ERP Synced'));
        }
        update as user ordersToUpdate;

        // 4. ⭐ 핵심: 후속 2차 비동기 작업(예: 알림톡 발송 Queueable) 체이닝 연결!
        if (!Test.isRunningTest()) {
            System.enqueueJob(new KakaoAlimtalkQueueable(this.targetOrders));
        }
    }
}
```

트리거 핸들러에서 호출할 때는 단 한 줄이면 되고, 반환받은 `jobId`로 진행 상태까지 조회할 수 있습니다.

```apex
// TriggerHandler 내부에서 호출 시
Id jobId = System.enqueueJob(new OrderErpSyncQueueable(changedOrders));
```

### 💡 실무자가 꼭 알아야 할 `Queueable` 디테일 2가지!

> **1. 테스트 클래스 에러 방지: 체이닝 앞에는 반드시 `if (!Test.isRunningTest())` 붙이기!**
> Apex 단위 테스트에서 `Test.stopTest()`가 실행될 때 비동기 작업이 동기로 즉시 실행되는데, 테스트 컨텍스트에서는 Queueable이 또 다른 Queueable을 부르는 연쇄 체이닝이 허용되지 않아 **`System.AsyncException: Maximum stack depth has been reached`** 에러가 납니다. 따라서 체이닝 호출부에는 `!Test.isRunningTest()`(또는 테스트용 스위치 변수)로 감싸두고, 2차 Queueable은 별도 테스트 메서드에서 단독 검증하는 것이 현업 국룰입니다.
{: .prompt-warning }

> **2. 조용히 묻히는 비동기 에러 잡기: `System.Finalizer` 활용**
> 비동기 작업은 백그라운드에서 돌기 때문에 예외가 터져도 사용자 화면에 에러 창이 뜨지 않습니다. 아래처럼 `Finalizer`를 붙여두면 **Callout 타임아웃이나 심지어 미처리 Limit 에러로 죽더라도 무조건 `execute`가 호출**되어 실패 로그 오브젝트(`Error_Log__c`)에 안전하게 기록을 남기거나 재시도(Retry) 큐를 태울 수 있습니다!
{: .prompt-tip }

```apex
public class ErpSyncFinalizer implements Finalizer {
    private List<Order> orders;

    public ErpSyncFinalizer(List<Order> orders) {
        this.orders = orders;
    }

    public void execute(FinalizerContext ctx) {
        if (ctx.getResult() == ParentJobResult.UNHANDLED_EXCEPTION) {
            Exception ex = ctx.getException();
            // 비동기 본체 트랜잭션이 롤백되더라도 이 안의 에러 로그 저장 DML은 별도로 정상 커밋됨!
            insert new Error_Log__c(
                Source__c = 'OrderErpSyncQueueable',
                Job_Id__c = String.valueOf(ctx.getAsyncApexJobId()),
                Message__c = ex.getMessage(),
                StackTrace__c = ex.getStackTraceString()
            );
        }
    }
}
```

---

## 4. 대용량 처리의 정석: `Batch Apex` 구조와 실전 함정 2가지

데이터가 수만 건~수천만 건 단위로 넘어가면 한 번의 `Queueable` 트랜잭션(SOQL 조회 5만 건, DML 1만 건 한도)으로도 감당할 수 없습니다. 이때 사용하는 것이 **`Database.Batchable`**입니다.

- **`start()`**: `Database.QueryLocator`를 통해 최대 **5,000만 건**까지 대상을 추출합니다.
- **`execute()`**: 지정한 배치 사이즈(기본값 **200건**) 단위로 데이터를 쪼개어 각각 **독립된 새 트랜잭션**으로 실행합니다. (즉, 200건 돌 때마다 SOQL 200회·DML 150회 카운트가 **0으로 새로 리셋**됩니다!)
- **`finish()`**: 모든 청크 실행이 끝난 뒤 딱 1번 호출됩니다. 완료 결과 메일을 보내거나 **2차 후속 배치를 체이닝(`Database.executeBatch(new Step2Batch(), 200)`)**할 때 씁니다.

### ✅ 실전 예제: 실패 건수 집계 및 후속 배치를 연결하는 `Batch Apex`

```apex
public class InactiveAccountCleanupBatch implements Database.Batchable<SObject>, Database.Stateful {

    // Database.Stateful 선언 시 청크가 바뀌어도 멤버 변수 값이 초기화되지 않고 끝까지 유지됨
    private Integer successCount = 0;
    private Integer failCount = 0;

    public Database.QueryLocator start(Database.BatchableContext bc) {
        Date cutoffDate = Date.today().addYears(-1);
        return Database.getQueryLocator([
            SELECT Id, Name, Status__c
            FROM Account
            WHERE LastActivityDate < :cutoffDate
              AND Status__c != 'Dormant'
        ]);
    }

    public void execute(Database.BatchableContext bc, List<Account> scope) {
        for (Account acc : scope) {
            acc.Status__c = 'Dormant';
        }

        // allOrNone = false 옵션: 200건 중 1건이 Validation 에러가 나더라도 나머지 199건은 정상 저장!
        Database.SaveResult[] results = Database.update(scope, false);
        for (Database.SaveResult sr : results) {
            if (sr.isSuccess()) {
                successCount++;
            } else {
                failCount++;
            }
        }
    }

    public void finish(Database.BatchableContext bc) {
        System.debug('휴면 전환 완료 - 성공: ' + successCount + '건 / 실패: ' + failCount + '건');

        // ⭐ 배치 체이닝: 1차 휴면 전환이 모두 끝난 직후 2차 하위 Contact 정리 배치 연속 실행!
        if (!Test.isRunningTest()) {
            Database.executeBatch(new DormantContactSyncBatch(), 200);
        }
    }
}
```

### ⚠️ 현업에서 진짜 자주 터지는 `Batch Apex` 사고 2가지

#### 1) 배치 안에서 외부 API(Callout) 쏠 때 기본 사이즈(200)로 돌리면 터진다!
`Database.AllowsCallouts`를 붙여서 배치 안에서 레코드마다 외부 API를 호출하는 경우를 생각해 봅시다.
- 한 트랜잭션(`execute` 1회)당 허용되는 **Callout 최대 횟수는 100회**입니다.
- 그런데 `Database.executeBatch(new MyCalloutBatch());`처럼 두 번째 파라미터(청크 사이즈)를 생략하면 **기본값인 `200`건**이 한 번에 들어옵니다!
- 레코드 1건당 API를 1번씩 호출하면 101번째 레코드에서 `System.LimitException: Too many callouts: 101` 에러가 터집니다.
- **해결책**: 단건 API 호출이 있는 배치는 반드시 **`Database.executeBatch(new MyCalloutBatch(), 50);`** 처럼 청크 사이즈를 100 이하(API가 2번 불린다면 50 이하)로 줄이거나, API가 벌크 배열 전송을 지원하도록 설계해야 합니다.

#### 2) `Database.Stateful` 켜놓고 `List<SObject>`를 계속 누적하면 메모리(Heap 12MB)가 터진다!
`Database.Stateful`은 `execute()`가 수백 번 반복되는 동안 인스턴스 변수를 직렬화/역직렬화하며 계속 들고 갑니다.
- 만약 `private List<Account> processedRecords = new List<Account>();` 같은 리스트 변수를 만들어 매 청크마다 데이터를 `addAll`로 계속 쌓아두면, 대상이 수만 건일 때 비동기 **Heap Size 한도(12MB)**를 초과해 배치가 중간에 죽어버리고 실행 속도도 급격히 느려집니다.
- **해결책**: `Stateful` 변수에는 위 예제처럼 **정수형 카운트(`Integer`)나 꼭 필요한 실패 레코드의 `Set<Id>` 정도만 가볍게 보관**해야 합니다!

---

## 5. 실무 응용 패턴: 외부 API 수신 ➔ `Iterable` 배치 체이닝 ➔ `Queueable` 완료(ACK) 회신

단순히 내부 데이터만 정리하는 배치를 넘어, 현업 인터페이스 개발에서 정말 유용하게 쓰이는 **다단계 하이브리드 체이닝 레퍼런스 패턴**을 하나 소개합니다. 나중에 외부 시스템(ERP, 물류, 커머스 등)과 양방향 동기화를 구현할 때 그대로 뼈대로 활용하기 좋은 구조입니다.

### 📌 실무 요건 시나리오
1. 외부 시스템 API를 호출(GET/POST)하여 변경된 **상위/연관 데이터(`Invoice__c`)**와 **품목 데이터(`OrderItem`)** 수백~수천 건을 JSON으로 받아옵니다.
2. 받아온 데이터를 Salesforce에 순차적으로 업데이트하되, **인터페이스 업데이트 도중 불필요한 내부 트리거가 돌지 않도록 제어**해야 합니다.
3. 만약 500건 중 498건은 성공하고 2건은 필수값 오류로 실패했다면, **실제 저장에 성공한 498건의 ID만 골라내어 외부 시스템에 "수신 반영 완료(ACK)" API를 다시 호출**해야 합니다. (실패한 2건은 다음 주기에 재수신되도록 유지)

왜 이 요건을 하나의 메서드에서 처리할 수 없을까요?
- `1차 조회 Callout` 이후 DB `update`(DML)를 실행하면, 같은 트랜잭션 안에서는 `2차 완료 회신 Callout`을 날릴 수 없습니다(`Uncommitted work pending` 에러).
- 또한 배치의 `finish()` 단계에서는 `@future` 메서드를 호출할 수 없으므로, 마지막 완료 회신 단계는 **`Queueable` (`Database.AllowsCallouts`)**로 연결해야 매끄럽게 완성됩니다.

```mermaid
flowchart LR
    A["1. @future 수신 Callout (JSON 파싱)"] --> B["2. 1차 Iterable Batch (연관 객체 + 스위치)"]
    B -- "finish() 체이닝" --> C["3. 2차 Stateful Batch (부분 저장 & 성공 ID 수집)"]
    C -- "finish() 체이닝" --> D["4. ACK Queueable (성공 ID 외부 회신)"]
```

### 1단계: `@future(callout=true)`로 외부 데이터 수신 및 Wrapper 파싱 후 배치 체인 시작

먼저 외부 API 게이트웨이를 호출해 변경 데이터를 받아오고, 내부 `Wrapper` 클래스로 역직렬화(Deserialize)하여 업데이트용 리스트를 구성한 뒤 첫 번째 배치를 출발시키는 진입점 클래스입니다. (사번 등 외부 키로 `User`를 매핑할 때도 루프 밖에서 단 1회 SOQL로 처리합니다.)

```apex
/**
 * @description 외부 시스템으로부터 변경 데이터를 수신하여 배치 체인을 시작하는 클래스
 * 호출 예시: ExternalDataFetchService.fetchUpdatedRecords();
 */
public class ExternalDataFetchService {

    @future(callout = true)
    public static void fetchUpdatedRecords() {
        Http http = new Http();
        HttpRequest request = new HttpRequest();

        request.setEndpoint('https://<외부_API_엔드포인트>/v1/sync/pending-orders');
        request.setMethod('POST');
        request.setHeader('Content-Type', 'application/json; charset=utf-8');
        request.setHeader('x-api-key', '<발급받은_API_KEY>'); // 실무 운영 시 Named Credential 또는 Custom Metadata 분리 권장
        request.setTimeout(120000); // 최대 타임아웃 120초
        request.setBody(JSON.serialize(new Map<String, Object>()));

        HttpResponse response = http.send(request);
        if (response.getStatusCode() >= 200 && response.getStatusCode() < 300) {
            // API 게이트웨이가 JSON 문자열을 한 번 더 감싸서 반환하는 경우 언래핑 처리
            String rawBody = response.getBody();
            String jsonPayload = rawBody.startsWith('"')
                ? (String) JSON.deserialize(rawBody, String.class)
                : rawBody;

            parseAndStartBatchChain(jsonPayload);
        } else {
            System.debug(LoggingLevel.ERROR, '외부 수신 실패: ' + response.getStatusCode() + ' / ' + response.getBody());
        }
    }

    private static void parseAndStartBatchChain(String jsonPayload) {
        try {
            List<SyncRecordWrapper> wrappers = (List<SyncRecordWrapper>) JSON.deserialize(
                jsonPayload,
                List<SyncRecordWrapper>.class
            );
            if (wrappers == null || wrappers.isEmpty()) {
                return;
            }

            // 1. 담당자 사번(EmployeeNumber) 등 참조 키를 먼저 모아 단 1회 SOQL로 매핑 준비
            Set<String> empNumbers = new Set<String>();
            for (SyncRecordWrapper w : wrappers) {
                if (String.isNotBlank(w.MANAGER_EMP_NO)) {
                    empNumbers.add(w.MANAGER_EMP_NO);
                }
            }

            Map<String, Id> empNoToUserIdMap = new Map<String, Id>();
            if (!empNumbers.isEmpty()) {
                for (User u : [SELECT Id, EmployeeNumber FROM User WHERE EmployeeNumber IN :empNumbers]) {
                    empNoToUserIdMap.put(u.EmployeeNumber, u.Id);
                }
            }

            // 2. 배치에 넘길 업데이트 대상 SObject 리스트 및 외부 키 매핑 구성
            List<Invoice__c> invoicesToUpdate = new List<Invoice__c>();
            List<OrderItem> itemsToUpdate = new List<OrderItem>();
            Map<Id, String> sfIdToExternalKeyMap = new Map<Id, String>();

            for (SyncRecordWrapper w : wrappers) {
                if (String.isNotBlank(w.SF_INVOICE_ID)) {
                    invoicesToUpdate.add(new Invoice__c(
                        Id = (Id) w.SF_INVOICE_ID,
                        External_Spec__c = w.SPEC_CODE,
                        Synced_At__c = System.now()
                    ));
                }

                if (String.isNotBlank(w.SF_ORDER_ITEM_ID)) {
                    OrderItem item = new OrderItem(
                        Id = (Id) w.SF_ORDER_ITEM_ID,
                        Description = w.ITEM_NAME
                    );
                    // 매핑된 내부 User Id가 있으면 할당
                    if (empNoToUserIdMap.containsKey(w.MANAGER_EMP_NO)) {
                        // 커스텀 담당자 필드에 세팅 예시
                        item.put('Engineer_User__c', empNoToUserIdMap.get(w.MANAGER_EMP_NO));
                    }
                    itemsToUpdate.add(item);
                    sfIdToExternalKeyMap.put(item.Id, w.EXTERNAL_SYNC_KEY);
                }
            }

            // 3. 파싱된 메모리 리스트를 1차 배치로 넘겨 체이닝 파이프라인 시작!
            if (!invoicesToUpdate.isEmpty() || !itemsToUpdate.isEmpty()) {
                Database.executeBatch(
                    new SyncRelatedInvoiceBatch(invoicesToUpdate, itemsToUpdate, sfIdToExternalKeyMap),
                    200
                );
            }
        } catch (Exception e) {
            System.debug(LoggingLevel.ERROR, '파싱 및 배치 시작 오류: ' + e.getLineNumber() + ' / ' + e.getMessage());
            // 필요시 OrgWideEmailAddress를 활용한 관리자 장애 알림 메일 발송 처리
        }
    }

    // 외부 JSON 응답 매핑용 DTO Wrapper 클래스
    public class SyncRecordWrapper {
        public String EXTERNAL_SYNC_KEY; // 외부 시스템 고유 키 (ACK 회신용)
        public String SF_INVOICE_ID;     // Salesforce 상위/연관 레코드 ID
        public String SF_ORDER_ITEM_ID;  // Salesforce 품목 레코드 ID
        public String ITEM_NAME;
        public String SPEC_CODE;
        public String MANAGER_EMP_NO;    // 담당자 사번
    }
}
```

### 2단계: 메모리 리스트를 바로 태우는 `Iterable<SObject>` 1차 배치

보통 배치는 `Database.QueryLocator`로 DB를 조회할 때만 쓴다고 생각하기 쉽지만, 이미 외부 API 응답으로 메모리에 만들어 둔 `List<SObject>`가 있다면 **`Iterable<SObject>`**를 반환하여 불필요한 SOQL 없이 200건 단위로 안전하게 쪼개어 DML을 칠 수 있습니다.

```apex
public class SyncRelatedInvoiceBatch implements Database.Batchable<SObject> {

    private final List<Invoice__c> invoicesToUpdate;
    private final List<OrderItem> itemsToUpdate;
    private final Map<Id, String> sfIdToExternalKeyMap;

    public SyncRelatedInvoiceBatch(
        List<Invoice__c> invoices,
        List<OrderItem> items,
        Map<Id, String> externalKeyMap
    ) {
        this.invoicesToUpdate = invoices;
        this.itemsToUpdate = items;
        this.sfIdToExternalKeyMap = externalKeyMap;
    }

    // DB 재조회 없이 API에서 파싱한 리스트를 그대로 배치 청크로 투입
    public Iterable<SObject> start(Database.BatchableContext bc) {
        return this.invoicesToUpdate;
    }

    public void execute(Database.BatchableContext bc, List<SObject> scope) {
        // 1편에서 다룬 TriggerSwitch 패턴: 인터페이스 반영 중 불필요한 트리거 연쇄 차단
        TriggerSwitch.isExternalSync = true;
        try {
            Database.update(scope, false);
        } finally {
            TriggerSwitch.isExternalSync = false;
        }
    }

    public void finish(Database.BatchableContext bc) {
        // 1차 반영 완료 후 2차 품목 업데이트 배치로 체이닝!
        if (this.itemsToUpdate != null && !this.itemsToUpdate.isEmpty() && !Test.isRunningTest()) {
            Database.executeBatch(
                new SyncOrderItemBatch(this.itemsToUpdate, this.sfIdToExternalKeyMap),
                200
            );
        }
    }
}
```

### 3단계: 부분 성공(`allOrNone=false`) ID만 선별해 `Queueable`을 부르는 2차 배치

`Database.Stateful`을 활용해 무거운 SObject 전체가 아닌 **성공한 문자열 키(`List<String>`)만 가볍게 누적**한 뒤, `finish()`에서 완료 회신용 `Queueable`을 호출합니다.

```apex
public class SyncOrderItemBatch implements Database.Batchable<SObject>, Database.Stateful {

    private final List<OrderItem> itemsToUpdate;
    private final Map<Id, String> sfIdToExternalKeyMap;
    // 가벼운 문자열 리스트만 Stateful로 유지 (Heap 메모리 안전)
    private List<String> succeededExternalKeys = new List<String>();

    public SyncOrderItemBatch(List<OrderItem> items, Map<Id, String> externalKeyMap) {
        this.itemsToUpdate = items;
        this.sfIdToExternalKeyMap = externalKeyMap;
    }

    public Iterable<SObject> start(Database.BatchableContext bc) {
        return this.itemsToUpdate;
    }

    public void execute(Database.BatchableContext bc, List<SObject> scope) {
        // 일부 레코드가 실패하더라도 성공한 건은 살리고(false), 성공한 외부 키만 정확히 수집
        List<Database.SaveResult> saveResults = Database.update(scope, false);

        for (Database.SaveResult sr : saveResults) {
            if (sr.isSuccess()) {
                String extKey = this.sfIdToExternalKeyMap.get(sr.getId());
                if (String.isNotBlank(extKey)) {
                    this.succeededExternalKeys.add(extKey);
                }
            }
        }
    }

    public void finish(Database.BatchableContext bc) {
        // 성공한 건이 있을 때만 외부 시스템으로 ACK 회신 Queueable 실행
        if (!this.succeededExternalKeys.isEmpty() && !Test.isRunningTest()) {
            if (Limits.getQueueableJobs() < Limits.getLimitQueueableJobs()) {
                System.enqueueJob(new SendSyncAckQueueable(this.succeededExternalKeys));
            }
        }
    }
}
```

### 4단계: 성공 목록만 외부 API로 회신하는 마무리 `Queueable`

배치의 `finish()` 안에서는 `@future` 호출이 불가능하지만, 아래처럼 `Queueable`에 `Database.AllowsCallouts`를 구현하면 깔끔하게 외부 시스템에 완료 신호를 보낼 수 있습니다.

```apex
public class SendSyncAckQueueable implements Queueable, Database.AllowsCallouts {

    private final List<String> succeededExternalKeys;

    public SendSyncAckQueueable(List<String> succeededExternalKeys) {
        this.succeededExternalKeys = succeededExternalKeys;
    }

    public void execute(QueueableContext context) {
        HttpRequest req = new HttpRequest();
        // <외부_ACK_API_엔드포인트> 호출 (실무에서는 Named Credential 사용 시 키 관리가 더욱 안전함)
        req.setEndpoint('https://<외부_ACK_API_엔드포인트>/v1/sync/ack');
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json; charset=utf-8');
        req.setHeader('x-api-key', '<발급받은_API_KEY>');
        req.setTimeout(120000);

        Map<String, Object> payload = new Map<String, Object>{
            'syncedIds' => this.succeededExternalKeys
        };
        req.setBody(JSON.serialize(payload));

        HttpResponse res = new Http().send(req);
        if (res.getStatusCode() < 200 || res.getStatusCode() >= 300) {
            throw new CalloutException('ACK 회신 실패: ' + res.getStatusCode() + ' ' + res.getBody());
        }
    }
}
```

> **이 아키텍처의 실무적 장점**:
> 1. **트랜잭션 분리 완벽 해결**: 수신 Callout ➔ 다중 객체 대량 DML ➔ 송신 Callout을 에러 없이 한 줄기 파이프라인으로 연결할 수 있습니다.
> 2. **무결성 보장**: 무조건 전체 완료 신호를 보내는 것이 아니라 `SaveResult.isSuccess()`로 검증된 ID만 회신하므로 데이터 누락이 발생하지 않습니다.
{: .prompt-tip }

---

## 6. 스케줄러(`Schedulable`)와 결합할 때의 실무 팁

매일 새벽 2시에 배치를 돌릴 때는 `Schedulable` 클래스를 껍데기로 얇게 만들고 실제 로직은 `Batch`나 `Queueable`에 위임합니다.

```apex
public class DailyAccountCleanupScheduler implements Schedulable {
    public void execute(SchedulableContext sc) {
        // 스케줄러 클래스에는 비즈니스 로직을 넣지 않고 배치 실행만 위임!
        // (나중에 배치 코드를 수정하더라도 걸려 있는 스케줄 Job을 삭제하고 다시 걸 필요가 없음)
        Database.executeBatch(new InactiveAccountCleanupBatch(), 200);
    }
}
```

> **왜 스케줄러 클래스와 배치 클래스를 분리할까요?**
> Salesforce에서는 이미 스케줄에 등록된(`Scheduled Jobs`) 클래스나 그 클래스가 직접 참조하는 코드를 배포/수정하려 할 때 락(Lock)이 걸려 배포 에러가 나는 경우가 있습니다. 스케줄러는 최대한 얇게 유지(필요시 `Type.forName` 동적 생성 활용)하고 실제 로직은 배치 클래스에 분리하는 것이 운영 배포 시 훨씬 편합니다.
{: .prompt-info }

---

## 마무리 요약 체크리스트

> **비동기 Apex 설계 전 5초 점검표**
> - [ ] 신규 개발인데 습관적으로 `@future`를 쓰려 하지 않았는가? → **`Queueable`로 작성하면 체이닝과 객체 전달이 모두 해결된다!**
> - [ ] `Queueable` 체이닝 시 단위 테스트 에러 방지를 위해 `!Test.isRunningTest()` 분기를 처리했는가?
> - [ ] 대량 배치(`Batch Apex`)의 `execute`에서 1건의 데이터 오류로 200건 전체가 롤백되지 않도록 `Database.update(scope, false)` 부분 성공 처리를 고려했는가?
> - [ ] Callout이 포함된 배치의 실행 청크 사이즈(Scope Size)가 Callout 제한(100회)을 넘지 않도록 조정했는가?
> - [ ] `Database.Stateful` 사용 시 거대한 `SObject` 리스트 대신 `Integer` 카운트나 최소한의 `Id`만 저장했는가?
{: .prompt-tip }

**다음 편 예고:**
> 데이터가 수백만 건 이상 쌓인 Org(Large Data Volume)에서는 똑같은 SOQL 쿼리도 인덱스를 타지 못하면 타임아웃(`Non-selective query`) 에러를 뿜어냅니다. 다음 3편에서는 **`대용량 데이터(LDV) 환경에서의 SOQL 쿼리 성능 최적화와 Query Plan 분석 실무`**를 다룹니다.
