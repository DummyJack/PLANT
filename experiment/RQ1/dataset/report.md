# ReqElicitBench 新增資料

## 方法

### 1. 保留原有 benchmark 結構

- 每個情境保留 `name`、`application_type`、`Category`、`initial_requirements`、`Implicit Requirements`、`URL`。
- 每條隱性需求只包含 `Aspect` 與 `隱性需求`。
- 每條隱性需求只標一個 primary Aspect。
- 相同 Aspect 在 JSON 中連續排列。

### 2. 新增 Aspect 的選擇準則

新增 Aspect 必須同時符合下列條件：

1. 在該情境中常見且核心。
2. 在規格書或原有情境中有明確依據。
3. 與 `Interaction`、`Content`、`Style` 層級一致，不是某個功能底下的子議題。
4. 能自然形成至少三條可訪談問出的隱性需求。
5. 不與其他新增 Aspect 過度重疊。

### 3. URL / Final User Story 的建立

每條 `Implicit Requirement` 都建立對應的 `URL` user story，使資料仍保有 Initial → Implicit → Final 的可追溯結構。

### 4. 訪談紀錄與追溯

- 英文 benchmark 情境使用英文訪談段落。
- 中文訂餐外送情境使用中文訪談段落。
- 新增需求在過程紀錄與訪談紀錄中保留新增新增段落 ID；原資料集既有需求不再標記重建訪談段落。
- 訪談紀錄是根據 benchmark 與規格書重建的模擬訪談，不宣稱是真實逐字稿。

## 新增原則

- 原有 benchmark 已有的 `Interaction`、`Content`、`Style` 與其 `隱性需求` 全部保留，不因數量超過三條而裁剪。
- 若本次新增需要補強原有 Aspect，則每個情境最多新增三條，且必須是該情境非常常見、可由訪談問出的隱性需求。
- 新增 Aspect 每個以三條代表性隱性需求為原則；若只能自然產生一到兩條，則不升格為該情境的正式新增 Aspect。
- 每條需求只標一個 primary Aspect，Aspect 名稱不使用 `/`。
- 相同 Aspect 在 JSON 中連續排列，方便檢查與後續評估。
- 新增需求以新增段落 ID 追溯到訪談紀錄；原資料集既有需求保留內容但不標記重建訪談段落。

## Aspect 定義

| Aspect | 定義 |
| --- | --- |
| Interaction | 使用者與系統互動的方式、流程、操作選擇、通知、輸入輸出行為。 |
| Content | 系統需要呈現、保存、組織或產生的資訊內容。 |
| Style | 介面視覺外觀，例如背景色、元件色彩與視覺呈現偏好。 |
| Data Quality | 資料的正確性、即時性、完整性、一致性與來源可信度；freshness 視為 Data Quality 的一部分。 |
| Integration | 系統與外部 API、第三方服務、資料提供者、付款閘道，或內部模組之間的連接與同步。 |
| Performance | 系統在報告生成、查詢或多人使用時的速度、回應性與負載承受能力。 |
| Security | 身分驗證、授權、存取控制、敏感資料保護，以及防止不安全或有害內容進入使用情境。 |
| Auditability | 可追溯性、操作紀錄、修改紀錄、匯出紀錄，以及能否支援事後稽核。 |
| Reliability | 狀態一致性、交易正確性、失敗處理、防重複訂位，以及系統在異常狀況下維持正確結果的能力。 |
| Adaptivity | 系統根據使用者進度、表現或偏好調整學習路徑、難度與節奏的能力。 |
| Assessment | 學習回饋、掌握度判斷、錯題解釋、弱項分析與學習成效追蹤。 |

## 全體摘要

| 情境 ID | 情境 | 原有需求數 | 原有 Aspect 分布 | 新增至原有 Aspect 的需求數 | 新增 Aspect | 新增需求數 | 總需求數 |
| --- | --- | ---: | --- | ---: | --- | ---: | ---: |
| S1 | Stock Report Generation System | 5 | Interaction: 2, Content: 1, Style: 2 | 3 | Data Quality: 3, Integration: 3, Performance: 3 | 9 | 17 |
| S2 | Hospital Management and Information System | 9 | Interaction: 3, Content: 4, Style: 2 | 3 | Security: 3, Auditability: 3, Integration: 3 | 9 | 21 |
| S3 | Bus and Railway Ticket Booking System | 11 | Interaction: 6, Content: 3, Style: 2 | 3 | Security: 3, Reliability: 3, Integration: 3 | 9 | 23 |
| S4 | Adult Vocabulary Learning and Quiz System | 11 | Interaction: 4, Content: 5, Style: 2 | 3 | Adaptivity: 3, Assessment: 3, Security: 3 | 9 | 23 |
| S5 | 訂餐外送系統 | 0（新情境） | Interaction: 3, Content: 3, Style: 2（新建） | 不適用 | Performance: 3, Reliability: 3, Security: 3, Integration: 3 | 12 | 20 |ㄋ

# S1. Stock Report Generation System

## 情境

- Application type：`Dashboards`
- Primary category：`Data Management`
- Subcategories：`CRUD Operations, API Integration, Data Visualization`
- Initial requirements：I need a website that helps me search for stocks and automatically generate stock analysis reports.

## 原資料集隱性需求

| 原有 Aspect | 原有隱性需求 |
| --- | --- |
| Interaction | I prefer to search for stocks by entering stock codes or stock names. |
| Interaction | I prefer to select the report format and content scope before report generation, instead of using a default report template. |
| Content | I expect the generated reports to include basic stock information, market trends, and financial data. |
| Style | I prefer the website to use a white background. |
| Style | I prefer the website components to use a navy color. |

## 新增至原有 Aspect 的需求

| 原有 Aspect | 隱性需求 | 保留理由 |
| --- | --- | --- |
| Interaction | I prefer to choose the analysis time range before generating the report. | 此需求描述常見使用流程、操作控制或使用者行為，仍屬於原有 Interaction。 |
| Interaction | I prefer to download or export the generated stock report after it is created. | 此需求描述常見使用流程、操作控制或使用者行為，仍屬於原有 Interaction。 |
| Content | I expect the generated report to include charts or tables that summarize key stock indicators. | 此需求描述系統需呈現或保存的常見資訊內容，仍屬於原有 Content。 |

## 新增 Aspect

| 新增 Aspect | 為什麼此情境需要這個 Aspect | 與原有 Aspect 的邊界 | 新增隱性需求 |
| --- | --- | --- | --- |
| Data Quality | 股票報告的價值取決於股價、趨勢與財務資料是否即時、完整、一致且可信。這些需求不是單純「報告包含哪些內容」，而是報告資料是否可靠。 | Content 關心報告包含哪些資訊；Data Quality 關心這些資訊是否可信、即時、完整、一致。 | 1. I expect stock prices, market trends, and financial data in the report to be based on current data.<br>2. I expect the report to show when the stock data was last updated.<br>3. I expect the system to warn me when stock data is missing, delayed, or inconsistent. |
| Integration | 股票資料通常需要由外部市場資料 API 或資料提供者取得；資料來源可設定與連線狀態可見，都是系統與外部資料源的整合需求。 | Interaction 關心使用者怎麼操作；Integration 關心系統是否能接外部資料源並同步資料。 | 1. I expect the system to retrieve stock information from external market data APIs.<br>2. I expect the system to use a configurable external market data provider for retrieving stock information.<br>3. I expect the system to show the connection status of the external market data provider before generating a report. |
| Performance | 自動產生股票分析報告會產生等待時間與並發使用壓力；報告生成速度、頁面回應與多人同時生成時的表現屬於效能需求。 | Performance 關心速度與回應性；Data Quality 關心資料是否正確可信。 | 1. I expect stock analysis reports to be generated within an acceptable amount of time after I submit my choices.<br>2. I expect the system to remain responsive while generating stock analysis reports.<br>3. I expect the system to support multiple users generating stock reports without noticeable slowdown. |

## 需求追溯表

| Aspect | 隱性需求 | 來源類型 | 新增段落 ID |
| --- | --- | --- | --- |
| Interaction | I prefer to search for stocks by entering stock codes or stock names. | 原有 benchmark 已有 | — |
| Interaction | I prefer to select the report format and content scope before report generation, instead of using a default report template. | 原有 benchmark 已有 | — |
| Interaction | I prefer to choose the analysis time range before generating the report. | 新增至原有 Aspect | A-S1-I01 |
| Interaction | I prefer to download or export the generated stock report after it is created. | 新增至原有 Aspect | A-S1-I01 |
| Content | I expect the generated reports to include basic stock information, market trends, and financial data. | 原有 benchmark 已有 | — |
| Content | I expect the generated report to include charts or tables that summarize key stock indicators. | 新增至原有 Aspect | A-S1-I01 |
| Style | I prefer the website to use a white background. | 原有 benchmark 已有 | — |
| Style | I prefer the website components to use a navy color. | 原有 benchmark 已有 | — |
| Data Quality | I expect stock prices, market trends, and financial data in the report to be based on current data. | 新增 Aspect | A-S1-I02 |
| Data Quality | I expect the report to show when the stock data was last updated. | 新增 Aspect | A-S1-I02 |
| Data Quality | I expect the system to warn me when stock data is missing, delayed, or inconsistent. | 新增 Aspect | A-S1-I02 |
| Integration | I expect the system to retrieve stock information from external market data APIs. | 新增 Aspect | A-S1-I03 |
| Integration | I expect the system to use a configurable external market data provider for retrieving stock information. | 新增 Aspect | A-S1-I03 |
| Integration | I expect the system to show the connection status of the external market data provider before generating a report. | 新增 Aspect | A-S1-I03 |
| Performance | I expect stock analysis reports to be generated within an acceptable amount of time after I submit my choices. | 新增 Aspect | A-S1-I04 |
| Performance | I expect the system to remain responsive while generating stock analysis reports. | 新增 Aspect | A-S1-I04 |
| Performance | I expect the system to support multiple users generating stock reports without noticeable slowdown. | 新增 Aspect | A-S1-I04 |

# S2. Hospital Management and Information System

## 情境

- Application type：`Enterprise Management`
- Primary category：`Data Management`
- Subcategories：`CRUD Operations, API Integration, Big Data`
- Initial requirements：I want a website that helps manage hospital operations, including clinical, administrative, and operational activities, and provides a clear overview of the hospital’s overall performance.

## 原資料集隱性需求

| 原有 Aspect | 原有隱性需求 |
| --- | --- |
| Interaction | I prefer the system to support structured report generation (inventory, patient, and financial reports) |
| Interaction | I prefer employees to submit daily activity reports directly through the system so that reporting to superiors is integrated into routine workflows. |
| Interaction | I prefer financial interactions, such as collecting patient fees and preparing claims, to be handled within the same system |
| Content | I expect hospital performance information to be reflected through detailed financial, inventory, patient, and operational reports |
| Content | I expect patient electronic files to contain structured medical and administrative details, including identification, visit history, diagnoses, and supplementary comments. |
| Content | I expect pharmacy management to focus on medicine inventory details to ensure accurate tracking of stock levels. |
| Content | I expect daily employee reports to include detailed descriptions of activities |
| Style | I prefer the website to use a peach puff background color. |
| Style | I prefer the website’s interface components to be displayed in indian red. |

## 新增至原有 Aspect 的需求

| 原有 Aspect | 新增隱性需求 | 保留理由 |
| --- | --- | --- |
| Interaction | I prefer users to filter hospital reports by department, date range, and report type. | 此需求描述常見使用流程、操作控制或使用者行為，仍屬於原有 Interaction。 |
| Content | I expect claim records to include patient information, service details, claim status, and supporting notes. | 此需求描述系統需呈現或保存的常見資訊內容，仍屬於原有 Content。 |
| Content | I expect laboratory management information to include test requests, test results, and related patient details. | 此需求描述系統需呈現或保存的常見資訊內容，仍屬於原有 Content。 |

## 新增 Aspect

| 新增 Aspect | 為什麼此情境需要這個 Aspect | 與原有 Aspect 的邊界 | 新增隱性需求 |
| --- | --- | --- | --- |
| Security | 醫院系統處理病患電子檔、財務資料、claim 與醫療資訊，這些都是敏感資料，需要授權角色、權限分離與未授權存取防護。 | Content 關心病患檔案或報表包含哪些欄位；Security 關心誰能查看、修改或保護這些資料。 | 1. I expect patient electronic files to be accessible only to authorized hospital staff.<br>2. I expect different hospital roles to have different permissions for patient, financial, inventory, and claim records.<br>3. I expect sensitive patient and financial information to be protected from unauthorized access. |
| Auditability | 病患紀錄、財務紀錄與 claim 修改都需要可追溯；操作紀錄、修改紀錄與匯出紀錄可支援事後稽核。 | Security 關心防止未授權存取；Auditability 關心事後能否追蹤誰做了什麼。 | 1. I expect changes to patient records, financial records, and claims to be logged for audit purposes.<br>2. I expect audit logs to include the user, time, and action performed.<br>3. I expect exports of sensitive patient or financial data to be recorded for audit review. |
| Integration | 醫院系統包含 patient、pharmacy、financial、claim、laboratory、theater 等多模組，常見需求是資料在模組間同步與連動。 | Content 關心各模組內容；Integration 關心不同模組之間的資料交換與同步。 | 1. I expect patient, pharmacy, financial, claim, laboratory, and theater information to be synchronized across modules.<br>2. I expect claim formulation to exchange relevant data with financial and patient record modules.<br>3. I expect laboratory and theater records to be linked to relevant patient electronic files. |

## 需求追溯表

| Aspect | 隱性需求 | 來源類型 | 新增段落 ID |
| --- | --- | --- | --- |
| Interaction | I prefer the system to support structured report generation (inventory, patient, and financial reports) | 原有 benchmark 已有 | — |
| Interaction | I prefer employees to submit daily activity reports directly through the system so that reporting to superiors is integrated into routine workflows. | 原有 benchmark 已有 | — |
| Interaction | I prefer financial interactions, such as collecting patient fees and preparing claims, to be handled within the same system | 原有 benchmark 已有 | — |
| Interaction | I prefer users to filter hospital reports by department, date range, and report type. | 新增至原有 Aspect | A-S2-I01 |
| Content | I expect hospital performance information to be reflected through detailed financial, inventory, patient, and operational reports | 原有 benchmark 已有 | — |
| Content | I expect patient electronic files to contain structured medical and administrative details, including identification, visit history, diagnoses, and supplementary comments. | 原有 benchmark 已有 | — |
| Content | I expect pharmacy management to focus on medicine inventory details to ensure accurate tracking of stock levels. | 原有 benchmark 已有 | — |
| Content | I expect daily employee reports to include detailed descriptions of activities | 原有 benchmark 已有 | — |
| Content | I expect claim records to include patient information, service details, claim status, and supporting notes. | 新增至原有 Aspect | A-S2-I01 |
| Content | I expect laboratory management information to include test requests, test results, and related patient details. | 新增至原有 Aspect | A-S2-I01 |
| Style | I prefer the website to use a peach puff background color. | 原有 benchmark 已有 | — |
| Style | I prefer the website’s interface components to be displayed in indian red. | 原有 benchmark 已有 | — |
| Security | I expect patient electronic files to be accessible only to authorized hospital staff. | 新增 Aspect | A-S2-I02 |
| Security | I expect different hospital roles to have different permissions for patient, financial, inventory, and claim records. | 新增 Aspect | A-S2-I02 |
| Security | I expect sensitive patient and financial information to be protected from unauthorized access. | 新增 Aspect | A-S2-I02 |
| Auditability | I expect changes to patient records, financial records, and claims to be logged for audit purposes. | 新增 Aspect | A-S2-I03 |
| Auditability | I expect audit logs to include the user, time, and action performed. | 新增 Aspect | A-S2-I03 |
| Auditability | I expect exports of sensitive patient or financial data to be recorded for audit review. | 新增 Aspect | A-S2-I03 |
| Integration | I expect patient, pharmacy, financial, claim, laboratory, and theater information to be synchronized across modules. | 新增 Aspect | A-S2-I04 |
| Integration | I expect claim formulation to exchange relevant data with financial and patient record modules. | 新增 Aspect | A-S2-I04 |
| Integration | I expect laboratory and theater records to be linked to relevant patient electronic files. | 新增 Aspect | A-S2-I04 |

# S3. Bus and Railway Ticket Booking System

## 情境

- Application type：`E-commerce Web`
- Primary category：`User Interaction`
- Subcategories：`E-commerce, Authentication, Real-time Features`
- Initial requirements：I want a platform that helps me look up and book bus and train tickets, complete payments, and manage my trips and past bookings in one place.

## 原資料集隱性需求

| 原有 Aspect | 原有隱性需求 |
| --- | --- |
| Interaction | I prefer to receive booking confirmations automatically via email. |
| Interaction | I prefer to receive booking confirmations automatically via SMS. |
| Interaction | I prefer to manage my trips through a personal account that requires registration and login. |
| Interaction | I prefer to have the option to print tickets in addition to using digital confirmations. |
| Interaction | I prefer the platform to support responsive interaction on mobile devices. |
| Interaction | I prefer the platform to support responsive interaction on desktop devices. |
| Content | I prefer to view real-time seat availability before confirming a booking decision. |
| Content | I prefer to view real-time pricing before confirming a booking decision. |
| Content | I prefer to access my booking history through my account |
| Style | I prefer the platform to use a snow-colored background consistently across all pages. |
| Style | I prefer the platform’s interface components to use a dim gray color consistently. |

## 新增至原有 Aspect 的需求

| 原有 Aspect | 新增隱性需求 | 保留理由 |
| --- | --- | --- |
| Interaction | I prefer to search trips by origin, destination, travel date, and transport type. | 此需求描述常見使用流程、操作控制或使用者行為，仍屬於原有 Interaction。 |
| Interaction | I prefer to cancel or modify a booking from my account when allowed. | 此需求描述常見使用流程、操作控制或使用者行為，仍屬於原有 Interaction。 |
| Content | I expect trip results to include departure time, arrival time, duration, operator, and route information. | 此需求描述系統需呈現或保存的常見資訊內容，仍屬於原有 Content。 |

## 新增 Aspect

| 新增 Aspect | 為什麼此情境需要這個 Aspect | 與原有 Aspect 的邊界 | 新增隱性需求 |
| --- | --- | --- | --- |
| Security | 訂票平台涉及付款資訊、登入帳號、個人行程與 booking history，因此需要付款資料保護與個人資料存取控制。 | Interaction 關心使用者如何登入、付款或查看紀錄；Security 關心資料與帳號是否受到保護。 | 1. I expect my payment information to be protected during ticket purchases.<br>2. I expect only logged-in users to access their own booking history.<br>3. I expect the system to protect personal trip and account information from unauthorized access. |
| Reliability | 訂票與付款流程最常見風險是同一座位被重複預訂、付款中斷導致狀態不一致、付款期間座位沒有被保留。這些屬於交易可靠性。 | Performance 關心速度；Reliability 關心交易狀態是否正確且一致。 | 1. I expect the selected seat to be temporarily reserved while payment is being processed.<br>2. I expect the system to prevent double booking of the same seat.<br>3. I expect booking status to remain consistent if payment fails or the network connection is interrupted. |
| Integration | 訂票平台通常需要串接付款閘道、email/SMS 通知服務，以及交通營運商的座位與票務資料。 | Interaction 關心使用者接收通知；Integration 關心系統與外部服務是否成功串接。 | 1. I expect the platform to integrate with payment gateways for ticket purchases.<br>2. I expect the platform to integrate with email and SMS services for booking confirmations.<br>3. I expect bus and railway ticket availability to be synchronized with the relevant transport operators. |

## 需求追溯表

| Aspect | 隱性需求 | 來源類型 | 新增段落 ID |
| --- | --- | --- | --- |
| Interaction | I prefer to receive booking confirmations automatically via email. | 原有 benchmark 已有 | — |
| Interaction | I prefer to receive booking confirmations automatically via SMS. | 原有 benchmark 已有 | — |
| Interaction | I prefer to manage my trips through a personal account that requires registration and login. | 原有 benchmark 已有 | — |
| Interaction | I prefer to have the option to print tickets in addition to using digital confirmations. | 原有 benchmark 已有 | — |
| Interaction | I prefer the platform to support responsive interaction on mobile devices. | 原有 benchmark 已有 | — |
| Interaction | I prefer the platform to support responsive interaction on desktop devices. | 原有 benchmark 已有 | — |
| Interaction | I prefer to search trips by origin, destination, travel date, and transport type. | 新增至原有 Aspect | A-S3-I01 |
| Interaction | I prefer to cancel or modify a booking from my account when allowed. | 新增至原有 Aspect | A-S3-I01 |
| Content | I prefer to view real-time seat availability before confirming a booking decision. | 原有 benchmark 已有 | — |
| Content | I prefer to view real-time pricing before confirming a booking decision. | 原有 benchmark 已有 | — |
| Content | I prefer to access my booking history through my account | 原有 benchmark 已有 | — |
| Content | I expect trip results to include departure time, arrival time, duration, operator, and route information. | 新增至原有 Aspect | A-S3-I01 |
| Style | I prefer the platform to use a snow-colored background consistently across all pages. | 原有 benchmark 已有 | — |
| Style | I prefer the platform’s interface components to use a dim gray color consistently. | 原有 benchmark 已有 | — |
| Security | I expect my payment information to be protected during ticket purchases. | 新增 Aspect | A-S3-I02 |
| Security | I expect only logged-in users to access their own booking history. | 新增 Aspect | A-S3-I02 |
| Security | I expect the system to protect personal trip and account information from unauthorized access. | 新增 Aspect | A-S3-I02 |
| Reliability | I expect the selected seat to be temporarily reserved while payment is being processed. | 新增 Aspect | A-S3-I03 |
| Reliability | I expect the system to prevent double booking of the same seat. | 新增 Aspect | A-S3-I03 |
| Reliability | I expect booking status to remain consistent if payment fails or the network connection is interrupted. | 新增 Aspect | A-S3-I03 |
| Integration | I expect the platform to integrate with payment gateways for ticket purchases. | 新增 Aspect | A-S3-I04 |
| Integration | I expect the platform to integrate with email and SMS services for booking confirmations. | 新增 Aspect | A-S3-I04 |
| Integration | I expect bus and railway ticket availability to be synchronized with the relevant transport operators. | 新增 Aspect | A-S3-I04 |

# S4. Adult Vocabulary Learning and Quiz System

## 情境

- Application type：`Learning Platforms`
- Primary category：`User Interaction`
- Subcategories：`Form Systems, Data Visualization, AI Integration`
- Initial requirements：I want a website that helps me steadily learn and practice new vocabulary, stay motivated, and track my learning progress over time.

## 原資料集隱性需求

| 原有 Aspect | 原有隱性需求 |
| --- | --- |
| Interaction | I prefer to learn vocabulary through interactive activities such as quizzes, games, and puzzles |
| Interaction | I prefer structured, recurring learning with a fixed pace of 10 new words each week |
| Interaction | I prefer to review and practice vocabulary using multiple activity formats (e.g., flashcards, fill-in-the-blank, word games) to reinforce learning. |
| Interaction | I prefer to personalize my learning experience by choosing an avatar. |
| Content | I prefer to navigate the website through clearly separated pages (home, activity pages, dashboard, blog) |
| Content | I expect the website to focus on adult-level vocabulary rather than general or child-oriented word lists. |
| Content | I expect vocabulary practice content to include crossword puzzles, unjumble-letter games, synonym games, antonym games, flashcards, and fill-in-the-blank exercises. |
| Content | I expect the system to provide a clear progress summary that reflects my ongoing vocabulary learning over time. |
| Content | I expect supplementary learning content to be available through blog pages related to vocabulary learning. |
| Style | I prefer the website’s body background to be light gray. |
| Style | I prefer the main interface components to use a dark red color. |

## 新增至原有 Aspect 的需求

| 原有 Aspect | 新增隱性需求 | 保留理由 |
| --- | --- | --- |
| Interaction | I prefer to retry incorrect questions after receiving feedback. | 此需求描述常見使用流程、操作控制或使用者行為，仍屬於原有 Interaction。 |
| Interaction | I prefer to set reminders or learning sessions to help me maintain a regular study habit. | 此需求描述常見使用流程、操作控制或使用者行為，仍屬於原有 Interaction。 |
| Content | I expect vocabulary entries to include definitions, example sentences, and usage notes. | 此需求描述系統需呈現或保存的常見資訊內容，仍屬於原有 Content。 |

## 新增 Aspect

| 新增 Aspect | 為什麼此情境需要這個 Aspect | 與原有 Aspect 的邊界 | 新增隱性需求 |
| --- | --- | --- | --- |
| Adaptivity | 學習平台常見需求是依使用者進度、弱項與表現調整難度、複習內容與學習節奏。這不是單一互動，而是系統行為的個人化。 | Interaction 關心使用者做哪些活動；Adaptivity 關心系統如何根據學習狀態調整活動與難度。 | 1. I expect the system to adjust vocabulary difficulty based on my learning progress.<br>2. I expect the system to recommend review activities based on words I struggle with.<br>3. I expect the weekly learning pace to be adjustable when my performance suggests it is too easy or too difficult. |
| Assessment | 字彙學習不只需要題目，也需要錯題回饋、掌握度判斷、正確率、練習頻率與弱項分析。 | Content 關心有哪些題目或頁面；Assessment 關心學習成效如何被判斷與回饋。 | 1. I expect the system to show correct answers and brief explanations after I answer incorrectly.<br>2. I expect the system to identify vocabulary words that I have mastered and words that still need practice.<br>3. I expect progress summaries to include accuracy, practice frequency, and weak vocabulary areas. |
| Security | 此情境包含 AI Integration，AI 生成內容需避免不適當、有害、冒犯、誤導或不安全的語言進入學習流程，並允許使用者回報。 | Content 關心學習材料本身；Security 在此情境中關心 AI 生成內容的安全性與風險控制。 | 1. I expect AI-generated vocabulary examples and exercises to be screened for inappropriate or harmful content before being shown to learners.<br>2. I expect AI-generated learning content to avoid offensive, misleading, or unsafe language usage.<br>3. I expect users to be able to report unsafe or inappropriate AI-generated content for review. |

## 需求追溯表

| Aspect | 隱性需求 | 來源類型 | 新增段落 ID |
| --- | --- | --- | --- |
| Interaction | I prefer to learn vocabulary through interactive activities such as quizzes, games, and puzzles | 原有 benchmark 已有 | — |
| Interaction | I prefer structured, recurring learning with a fixed pace of 10 new words each week | 原有 benchmark 已有 | — |
| Interaction | I prefer to review and practice vocabulary using multiple activity formats (e.g., flashcards, fill-in-the-blank, word games) to reinforce learning. | 原有 benchmark 已有 | — |
| Interaction | I prefer to personalize my learning experience by choosing an avatar. | 原有 benchmark 已有 | — |
| Interaction | I prefer to retry incorrect questions after receiving feedback. | 新增至原有 Aspect | A-S4-I01 |
| Interaction | I prefer to set reminders or learning sessions to help me maintain a regular study habit. | 新增至原有 Aspect | A-S4-I01 |
| Content | I prefer to navigate the website through clearly separated pages (home, activity pages, dashboard, blog) | 原有 benchmark 已有 | — |
| Content | I expect the website to focus on adult-level vocabulary rather than general or child-oriented word lists. | 原有 benchmark 已有 | — |
| Content | I expect vocabulary practice content to include crossword puzzles, unjumble-letter games, synonym games, antonym games, flashcards, and fill-in-the-blank exercises. | 原有 benchmark 已有 | — |
| Content | I expect the system to provide a clear progress summary that reflects my ongoing vocabulary learning over time. | 原有 benchmark 已有 | — |
| Content | I expect supplementary learning content to be available through blog pages related to vocabulary learning. | 原有 benchmark 已有 | — |
| Content | I expect vocabulary entries to include definitions, example sentences, and usage notes. | 新增至原有 Aspect | A-S4-I01 |
| Style | I prefer the website’s body background to be light gray. | 原有 benchmark 已有 | — |
| Style | I prefer the main interface components to use a dark red color. | 原有 benchmark 已有 | — |
| Adaptivity | I expect the system to adjust vocabulary difficulty based on my learning progress. | 新增 Aspect | A-S4-I02 |
| Adaptivity | I expect the system to recommend review activities based on words I struggle with. | 新增 Aspect | A-S4-I02 |
| Adaptivity | I expect the weekly learning pace to be adjustable when my performance suggests it is too easy or too difficult. | 新增 Aspect | A-S4-I02 |
| Assessment | I expect the system to show correct answers and brief explanations after I answer incorrectly. | 新增 Aspect | A-S4-I03 |
| Assessment | I expect the system to identify vocabulary words that I have mastered and words that still need practice. | 新增 Aspect | A-S4-I03 |
| Assessment | I expect progress summaries to include accuracy, practice frequency, and weak vocabulary areas. | 新增 Aspect | A-S4-I03 |
| Security | I expect AI-generated vocabulary examples and exercises to be screened for inappropriate or harmful content before being shown to learners. | 新增 Aspect | A-S4-I04 |
| Security | I expect AI-generated learning content to avoid offensive, misleading, or unsafe language usage. | 新增 Aspect | A-S4-I04 |
| Security | I expect users to be able to report unsafe or inappropriate AI-generated content for review. | 新增 Aspect | A-S4-I04 |

# S5. 訂餐外送系統

## 情境

- Application type：`E-commerce Web`
- Primary category：`User Interaction`
- Subcategories：`E-commerce`、`Authentication`、`Real-time Features`
- Initial requirements：我想要一個線上訂餐外送平台，讓顧客可以搜尋餐廳、瀏覽菜單、加入購物車、下單付款並追蹤外送，同時讓餐廳管理菜單與訂單、外送員接收派單並完成配送、平台管理者查看營運狀態。

## Spec 摘要

| Spec | 與本次新增相關的內容 |
| --- | --- |
| 系統概述 | 線上訂餐、餐廳管理、外送員接單與配送，提升點餐便利性、餐廳營運效率與送餐透明度。 |
| UR-01 至 UR-09 | 搜尋餐廳、加入購物車、付款、訂單追蹤、客服退款、餐廳接單、外送員接單、營運報表、尖峰流量。 |
| SR-01 至 SR-08 | 搜尋瀏覽、購物車下單、付款、訂單管理追蹤、餐廳管理、外送員功能、客服後台、安全與稽核。 |
| FR-01 至 FR-23 | 顧客、餐廳、外送員、管理者與客服的完整功能。 |
| NFR-01 | 效能與速度：操作回應、尖峰負載、定位即時性。 |
| NFR-02 | 可用性與可靠性：系統可用性、災難恢復、容錯能力。 |
| NFR-03 | 安全性與隱私性：支付安全、個資保護、身份驗證、傳輸加密、權限控管。 |
| Context Model | 系統與 Payment System、Notification Service、Delivery Management System、Customer Service、Admin Management System 等子系統互動。 |

## 原有 Aspect 設計

新加入的中文情境，不在 benchmark 中。為了維持資料集一致性，保留原有 Aspect：`Interaction`、`Content`、`Style`。

| Aspect | 隱性需求 | 設計理由 |
| --- | --- | --- |
| Interaction | 我偏好可以依地點、關鍵字、餐點類別、評分、外送時間與價格篩選餐廳。 | 規格書明確包含餐廳搜尋與篩選條件，屬於使用者操作方式。 |
| Interaction | 我偏好在結帳前可以確認並修改購物車中的餐點、數量、備註、配送方式、地址與金額明細。 | 對應購物車與下單流程，是顧客在送出訂單前的互動偏好。 |
| Interaction | 我偏好餐廳與外送員能透過明確的按鈕接單、拒單，並更新備餐或配送進度。 | 對應餐廳接單、外送員接單與狀態更新，是平台多角色操作流程。 |
| Content | 我期望餐廳列表能顯示評分、營業時間、外送時段、外送門檻與預估外送時間。 | 對應餐廳搜尋結果與餐廳詳細資訊，屬於顧客做決策所需內容。 |
| Content | 我期望訂單明細包含餐點項目、數量、備註、金額明細、付款狀態、配送地址與訂單狀態。 | 對應購物車、訂單明細、付款與配送追蹤資訊。 |
| Content | 我期望營運報表包含交易量、熱門餐點、使用者留存、營收、訂單數據與外送效率等資訊。 | 對應平台管理者與餐廳的營運報表需求。 |
| Style | 我偏好平台整體背景使用白色或淺色系。 | 原有 benchmark 的 Style 主要是背景色與元件色；此處只做最小化視覺偏好補足。 |
| Style | 我偏好主要操作元件使用橘色或暖色系，以符合餐飲外送平台的視覺風格。 | 延續原有 Style 定義，聚焦主要元件色與整體視覺色調。 |

## 新增 Aspect

新增 Aspect 為：`Performance`、`Reliability`、`Security`、`Integration`。

| 新增 Aspect | 規格書依據 | 為什麼此情境需要這個 Aspect | 與原有 Aspect 的邊界 | 新增隱性需求 |
| --- | --- | --- | --- | --- |
| Performance | NFR-01 效能與速度；SR-02 下單確認；SR-04 即時位置與 ETA。 | 訂餐外送平台高度依賴下單、付款、查詢與追蹤的即時性。此類需求不是操作方式，而是系統回應速度與負載表現。 | Interaction 關心使用者如何下單或查詢；Performance 關心這些操作在尖峰與即時場景下是否足夠快速。 | 1. 我期望下單、付款和查詢操作能快速完成，不會讓顧客在流程中等待太久。<br>2. 我期望用餐尖峰時段仍能順利完成搜尋、下單與付款，不會因流量變大而明顯變慢。<br>3. 我期望外送員位置更新足夠即時，讓顧客能大致掌握外送進度與預估到達時間。 |
| Reliability | NFR-02 可用性與可靠性；SR-04 訂單狀態機制；餐廳接單設備故障備援。 | 此平台的核心交易、付款、餐廳接單與配送追蹤都需要穩定。故障時不能讓訂單卡住或遺失。 | Performance 關心速度；Reliability 關心核心功能是否穩定、異常後是否能恢復，以及狀態與紀錄是否維持正確。 | 1. 我期望主要用餐時段平台的下單、付款與追蹤功能能穩定可用。<br>2. 我期望系統發生故障後能盡快恢復，而且既有訂單與付款紀錄不會遺失。<br>3. 我期望餐廳接單設備出問題時，訂單不會卡住，而是能被轉到備援設備或營運後台處理。 |
| Security | NFR-03 安全性與隱私性；SR-08 安全與遵守法律規範；FR-19 權限管理；FR-21 退款審核。 | 系統包含付款、個資、顧客與外送員聯絡資料、退款與後台權限操作，因此安全是高頻且核心的隱性需求。 | Content 關心保存哪些資料；Security 關心資料與高風險操作如何被保護、限制與授權。 | 1. 我期望付款資料與個人資料在平台上受到安全保護。<br>2. 我期望顧客與外送員的電話等聯絡資訊不會直接互相暴露。<br>3. 我期望退款、帳號修改與權限變更這類高風險操作只有授權人員能執行。 |
| Integration | FR-04 線上付款；FR-05 通知；FR-16 外送導航與更新；Context Model 中的 Payment System、Notification Service、Delivery Management System。 | 訂餐外送平台必須整合金流、通知、地圖與定位服務才能完成付款、狀態通知、外送導航與顧客追蹤。 | Interaction 關心使用者是否收到通知或使用導航；Integration 關心平台是否能與外部或子系統服務連接並同步狀態。 | 1. 我期望平台能支援常見付款服務，並在付款完成後正確更新訂單狀態。<br>2. 我期望訂單的重要狀態能透過應用程式推播、簡訊或電子郵件通知相關使用者。<br>3. 我期望外送導航與顧客追蹤能連接地圖與定位服務。 |

## 需求追溯表

| Aspect | 隱性需求 | 來源類型 | 新增段落 ID |
| --- | --- | --- | --- |
| Interaction | 我偏好可以依地點、關鍵字、餐點類別、評分、外送時間與價格篩選餐廳。 | 中文新情境原有 Aspect | — |
| Interaction | 我偏好在結帳前可以確認並修改購物車中的餐點、數量、備註、配送方式、地址與金額明細。 | 中文新情境原有 Aspect | — |
| Interaction | 我偏好餐廳與外送員能透過明確的按鈕接單、拒單，並更新備餐或配送進度。 | 中文新情境原有 Aspect | — |
| Content | 我期望餐廳列表能顯示評分、營業時間、外送時段、外送門檻與預估外送時間。 | 中文新情境原有 Aspect | — |
| Content | 我期望訂單明細包含餐點項目、數量、備註、金額明細、付款狀態、配送地址與訂單狀態。 | 中文新情境原有 Aspect | — |
| Content | 我期望營運報表包含交易量、熱門餐點、使用者留存、營收、訂單數據與外送效率等資訊。 | 中文新情境原有 Aspect | — |
| Style | 我偏好平台整體背景使用白色或淺色系。 | 中文新情境原有 Aspect | — |
| Style | 我偏好主要操作元件使用橘色或暖色系，以符合餐飲外送平台的視覺風格。 | 中文新情境原有 Aspect | — |
| Performance | 我期望下單、付款和查詢操作能快速完成，不會讓顧客在流程中等待太久。 | 新增 Aspect | A-S5-I01 |
| Performance | 我期望用餐尖峰時段仍能順利完成搜尋、下單與付款，不會因流量變大而明顯變慢。 | 新增 Aspect | A-S5-I01 |
| Performance | 我期望外送員位置更新足夠即時，讓顧客能大致掌握外送進度與預估到達時間。 | 新增 Aspect | A-S5-I01 |
| Reliability | 我期望主要用餐時段平台的下單、付款與追蹤功能能穩定可用。 | 新增 Aspect | A-S5-I02 |
| Reliability | 我期望系統發生故障後能盡快恢復，而且既有訂單與付款紀錄不會遺失。 | 新增 Aspect | A-S5-I02 |
| Reliability | 我期望餐廳接單設備出問題時，訂單不會卡住，而是能被轉到備援設備或營運後台處理。 | 新增 Aspect | A-S5-I02 |
| Security | 我期望付款資料與個人資料在平台上受到安全保護。 | 新增 Aspect | A-S5-I03 |
| Security | 我期望顧客與外送員的電話等聯絡資訊不會直接互相暴露。 | 新增 Aspect | A-S5-I03 |
| Security | 我期望退款、帳號修改與權限變更這類高風險操作只有授權人員能執行。 | 新增 Aspect | A-S5-I03 |
| Integration | 我期望平台能支援常見付款服務，並在付款完成後正確更新訂單狀態。 | 新增 Aspect | A-S5-I04 |
| Integration | 我期望訂單的重要狀態能透過應用程式推播、簡訊或電子郵件通知相關使用者。 | 新增 Aspect | A-S5-I04 |
| Integration | 我期望外送導航與顧客追蹤能連接地圖與定位服務。 | 新增 Aspect | A-S5-I04 |

