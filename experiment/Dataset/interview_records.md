# ReqElicitBench 需求訪談

## 說明

本文件提供每個情境的訪談段落與需求追溯。

## 全體摘要

| 情境 | 受訪者角色 | 原始需求數 | 新增至原有 Aspect 的需求數 | 新增 Aspect | 新增至新的 Aspect 的需求數 |
| --- | --- | ---: | ---: | --- | ---: |
| Stock Report Generation System | Investment research user / stock report requester | 5 | 3 | Data Quality, Integration, Performance | 9 |
| Hospital Management and Information System | Hospital operations manager / hospital information system requester | 9 | 3 | Security, Auditability, Integration | 9 |
| Bus and Railway Ticket Booking System | General traveler / ticket booking platform user | 11 | 3 | Security, Reliability, Integration | 9 |
| Adult Vocabulary Learning and Quiz System | Adult vocabulary learner / learning platform user | 11 | 3 | Adaptivity, Assessment, Security | 9 |
| 訂餐外送系統 | 顧客、餐廳營運者、外送員與平台營運方的綜合代表 | 0（新情境） | 不適用 | Performance, Reliability, Security, Integration | 12 |

# S1. Stock Report Generation System

## 情境

| 欄位 | 內容 |
| --- | --- |
| 受訪者角色 | Investment research user / stock report requester |
| Application type | Dashboards |
| Primary category | Data Management |
| Subcategories | CRUD Operations, API Integration, Data Visualization |
| Initial requirements | I need a website that helps me search for stocks and automatically generate stock analysis reports. |

## 擴增訪談紀錄

### A-S1-I01 — workflow and report presentation additions

**Interviewer:** Besides the original report options, what common workflow or report-output needs should the system support?

**Stakeholder:** Before generating the report, I prefer to choose the analysis time range. After the report is created, I prefer to download or export it. I also expect the generated report to include charts or tables that summarize key stock indicators.

### A-S1-I02 — data quality

**Interviewer:** How should the system help you judge whether the stock data in the generated report is trustworthy?

**Stakeholder:** I expect stock prices, market trends, and financial data in the report to be based on current data. I expect the report to show when the stock data was last updated. If stock data is missing, delayed, or inconsistent, I expect the system to warn me.

### A-S1-I03 — market data integration

**Interviewer:** Where should the stock information come from, and what should happen around the external data connection?

**Stakeholder:** I expect the system to retrieve stock information from external market data APIs. I expect the system to use a configurable external market data provider for retrieving stock information. I also expect the system to show the connection status of the external market data provider before generating a report.

### A-S1-I04 — report generation performance

**Interviewer:** What performance expectations do you have when the system generates reports?

**Stakeholder:** I expect stock analysis reports to be generated within an acceptable amount of time after I submit my choices. I expect the system to remain responsive while generating stock analysis reports. I also expect the system to support multiple users generating stock reports without noticeable slowdown.

## 需求抽取對照

| 訪談段落 ID | Aspect | 隱性需求 | 來源類型 |
| --- | --- | --- | --- |
| A-S1-I01 | Interaction | I prefer to choose the analysis time range before generating the report. | 新增至原有 Aspect |
| A-S1-I01 | Interaction | I prefer to download or export the generated stock report after it is created. | 新增至原有 Aspect |
| A-S1-I01 | Content | I expect the generated report to include charts or tables that summarize key stock indicators. | 新增至原有 Aspect |
| A-S1-I02 | Data Quality | I expect stock prices, market trends, and financial data in the report to be based on current data. | 新增 Aspect |
| A-S1-I02 | Data Quality | I expect the report to show when the stock data was last updated. | 新增 Aspect |
| A-S1-I02 | Data Quality | I expect the system to warn me when stock data is missing, delayed, or inconsistent. | 新增 Aspect |
| A-S1-I03 | Integration | I expect the system to retrieve stock information from external market data APIs. | 新增 Aspect |
| A-S1-I03 | Integration | I expect the system to use a configurable external market data provider for retrieving stock information. | 新增 Aspect |
| A-S1-I03 | Integration | I expect the system to show the connection status of the external market data provider before generating a report. | 新增 Aspect |
| A-S1-I04 | Performance | I expect stock analysis reports to be generated within an acceptable amount of time after I submit my choices. | 新增 Aspect |
| A-S1-I04 | Performance | I expect the system to remain responsive while generating stock analysis reports. | 新增 Aspect |
| A-S1-I04 | Performance | I expect the system to support multiple users generating stock reports without noticeable slowdown. | 新增 Aspect |

# S2. Hospital Management and Information System

## 情境

| 欄位 | 內容 |
| --- | --- |
| 受訪者角色 | Hospital operations manager / hospital information system requester |
| Application type | Enterprise Management |
| Primary category | Data Management |
| Subcategories | CRUD Operations, API Integration, Big Data |
| Initial requirements | I want a website that helps manage hospital operations, including clinical, administrative, and operational activities, and provides a clear overview of the hospital’s overall performance. |

## 擴增訪談紀錄

### A-S2-I01 — report filtering and module content additions

**Interviewer:** What additional common reporting or module-content needs should be included?

**Stakeholder:** I prefer users to filter hospital reports by department, date range, and report type. I expect claim records to include patient information, service details, claim status, and supporting notes. I also expect laboratory management information to include test requests, test results, and related patient details.

### A-S2-I02 — security for sensitive hospital data

**Interviewer:** How should access to sensitive patient and hospital information be controlled?

**Stakeholder:** I expect patient electronic files to be accessible only to authorized hospital staff. I expect different hospital roles to have different permissions for patient, financial, inventory, and claim records. I also expect sensitive patient and financial information to be protected from unauthorized access.

### A-S2-I03 — auditability

**Interviewer:** What should the system record for audit review?

**Stakeholder:** I expect changes to patient records, financial records, and claims to be logged for audit purposes. I expect audit logs to include the user, time, and action performed. I also expect exports of sensitive patient or financial data to be recorded for audit review.

### A-S2-I04 — cross-module integration

**Interviewer:** How should the hospital modules work together?

**Stakeholder:** I expect patient, pharmacy, financial, claim, laboratory, and theater information to be synchronized across modules. I expect claim formulation to exchange relevant data with financial and patient record modules. I also expect laboratory and theater records to be linked to relevant patient electronic files.

## 需求抽取對照

| 訪談段落 ID | Aspect | 隱性需求 | 來源類型 |
| --- | --- | --- | --- |
| A-S2-I01 | Interaction | I prefer users to filter hospital reports by department, date range, and report type. | 新增至原有 Aspect |
| A-S2-I01 | Content | I expect claim records to include patient information, service details, claim status, and supporting notes. | 新增至原有 Aspect |
| A-S2-I01 | Content | I expect laboratory management information to include test requests, test results, and related patient details. | 新增至原有 Aspect |
| A-S2-I02 | Security | I expect patient electronic files to be accessible only to authorized hospital staff. | 新增 Aspect |
| A-S2-I02 | Security | I expect different hospital roles to have different permissions for patient, financial, inventory, and claim records. | 新增 Aspect |
| A-S2-I02 | Security | I expect sensitive patient and financial information to be protected from unauthorized access. | 新增 Aspect |
| A-S2-I03 | Auditability | I expect changes to patient records, financial records, and claims to be logged for audit purposes. | 新增 Aspect |
| A-S2-I03 | Auditability | I expect audit logs to include the user, time, and action performed. | 新增 Aspect |
| A-S2-I03 | Auditability | I expect exports of sensitive patient or financial data to be recorded for audit review. | 新增 Aspect |
| A-S2-I04 | Integration | I expect patient, pharmacy, financial, claim, laboratory, and theater information to be synchronized across modules. | 新增 Aspect |
| A-S2-I04 | Integration | I expect claim formulation to exchange relevant data with financial and patient record modules. | 新增 Aspect |
| A-S2-I04 | Integration | I expect laboratory and theater records to be linked to relevant patient electronic files. | 新增 Aspect |

# S3. Bus and Railway Ticket Booking System

## 情境

| 欄位 | 內容 |
| --- | --- |
| 受訪者角色 | General traveler / ticket booking platform user |
| Application type | E-commerce Web |
| Primary category | User Interaction |
| Subcategories | E-commerce, Authentication, Real-time Features |
| Initial requirements | I want a platform that helps me look up and book bus and train tickets, complete payments, and manage my trips and past bookings in one place. |

## 擴增訪談紀錄

### A-S3-I01 — search, modification, and trip-result additions

**Interviewer:** What additional common booking interactions or result details should the platform support?

**Stakeholder:** I prefer to search trips by origin, destination, travel date, and transport type. I prefer to cancel or modify a booking from my account when allowed. I also expect trip results to include departure time, arrival time, duration, operator, and route information.

### A-S3-I02 — payment and account security

**Interviewer:** What information needs to be protected on the ticket booking platform?

**Stakeholder:** I expect my payment information to be protected during ticket purchases. I expect only logged-in users to access their own booking history. I also expect the system to protect personal trip and account information from unauthorized access.

### A-S3-I03 — booking reliability

**Interviewer:** What should the system do to keep bookings correct during payment or failure cases?

**Stakeholder:** I expect the selected seat to be temporarily reserved while payment is being processed. I expect the system to prevent double booking of the same seat. I also expect booking status to remain consistent if payment fails or the network connection is interrupted.

### A-S3-I04 — external service integration

**Interviewer:** What external services or operators should the platform connect with?

**Stakeholder:** I expect the platform to integrate with payment gateways for ticket purchases. I expect the platform to integrate with email and SMS services for booking confirmations. I also expect bus and railway ticket availability to be synchronized with the relevant transport operators.

## 需求抽取對照

| 訪談段落 ID | Aspect | 隱性需求 | 來源類型 |
| --- | --- | --- | --- |
| A-S3-I01 | Interaction | I prefer to search trips by origin, destination, travel date, and transport type. | 新增至原有 Aspect |
| A-S3-I01 | Interaction | I prefer to cancel or modify a booking from my account when allowed. | 新增至原有 Aspect |
| A-S3-I01 | Content | I expect trip results to include departure time, arrival time, duration, operator, and route information. | 新增至原有 Aspect |
| A-S3-I02 | Security | I expect my payment information to be protected during ticket purchases. | 新增 Aspect |
| A-S3-I02 | Security | I expect only logged-in users to access their own booking history. | 新增 Aspect |
| A-S3-I02 | Security | I expect the system to protect personal trip and account information from unauthorized access. | 新增 Aspect |
| A-S3-I03 | Reliability | I expect the selected seat to be temporarily reserved while payment is being processed. | 新增 Aspect |
| A-S3-I03 | Reliability | I expect the system to prevent double booking of the same seat. | 新增 Aspect |
| A-S3-I03 | Reliability | I expect booking status to remain consistent if payment fails or the network connection is interrupted. | 新增 Aspect |
| A-S3-I04 | Integration | I expect the platform to integrate with payment gateways for ticket purchases. | 新增 Aspect |
| A-S3-I04 | Integration | I expect the platform to integrate with email and SMS services for booking confirmations. | 新增 Aspect |
| A-S3-I04 | Integration | I expect bus and railway ticket availability to be synchronized with the relevant transport operators. | 新增 Aspect |

# S4. Adult Vocabulary Learning and Quiz System

## 情境

| 欄位 | 內容 |
| --- | --- |
| 受訪者角色 | Adult vocabulary learner / learning platform user |
| Application type | Learning Platforms |
| Primary category | User Interaction |
| Subcategories | Form Systems, Data Visualization, AI Integration |
| Initial requirements | I want a website that helps me steadily learn and practice new vocabulary, stay motivated, and track my learning progress over time. |

## 擴增訪談紀錄

### A-S4-I01 — study workflow and vocabulary-entry additions

**Interviewer:** What additional common study workflow or content details should be supported?

**Stakeholder:** I prefer to retry incorrect questions after receiving feedback. I prefer to set reminders or learning sessions to help me maintain a regular study habit. I also expect vocabulary entries to include definitions, example sentences, and usage notes.

### A-S4-I02 — adaptivity

**Interviewer:** How should the system adapt to your learning progress?

**Stakeholder:** I expect the system to adjust vocabulary difficulty based on my learning progress. I expect the system to recommend review activities based on words I struggle with. I also expect the weekly learning pace to be adjustable when my performance suggests it is too easy or too difficult.

### A-S4-I03 — assessment and feedback

**Interviewer:** What kind of feedback and assessment should the system provide?

**Stakeholder:** I expect the system to show correct answers and brief explanations after I answer incorrectly. I expect the system to identify vocabulary words that I have mastered and words that still need practice. I also expect progress summaries to include accuracy, practice frequency, and weak vocabulary areas.

### A-S4-I04 — security for AI-generated learning content

**Interviewer:** What should the system do to prevent unsafe or inappropriate AI-generated learning content?

**Stakeholder:** I expect AI-generated vocabulary examples and exercises to avoid inappropriate or harmful content. I expect AI-generated learning content to avoid offensive, misleading, or unsafe language usage. I also expect users to be able to report unsafe or inappropriate AI-generated content for review.

## 需求抽取對照

| 訪談段落 ID | Aspect | 隱性需求 | 來源類型 |
| --- | --- | --- | --- |
| A-S4-I01 | Interaction | I prefer to retry incorrect questions after receiving feedback. | 新增至原有 Aspect |
| A-S4-I01 | Interaction | I prefer to set reminders or learning sessions to help me maintain a regular study habit. | 新增至原有 Aspect |
| A-S4-I01 | Content | I expect vocabulary entries to include definitions, example sentences, and usage notes. | 新增至原有 Aspect |
| A-S4-I02 | Adaptivity | I expect the system to adjust vocabulary difficulty based on my learning progress. | 新增 Aspect |
| A-S4-I02 | Adaptivity | I expect the system to recommend review activities based on words I struggle with. | 新增 Aspect |
| A-S4-I02 | Adaptivity | I expect the weekly learning pace to be adjustable when my performance suggests it is too easy or too difficult. | 新增 Aspect |
| A-S4-I03 | Assessment | I expect the system to show correct answers and brief explanations after I answer incorrectly. | 新增 Aspect |
| A-S4-I03 | Assessment | I expect the system to identify vocabulary words that I have mastered and words that still need practice. | 新增 Aspect |
| A-S4-I03 | Assessment | I expect progress summaries to include accuracy, practice frequency, and weak vocabulary areas. | 新增 Aspect |
| A-S4-I04 | Security | I expect AI-generated vocabulary examples and exercises to be screened for inappropriate or harmful content before being shown to learners. | 新增 Aspect |
| A-S4-I04 | Security | I expect AI-generated learning content to avoid offensive, misleading, or unsafe language usage. | 新增 Aspect |
| A-S4-I04 | Security | I expect users to be able to report unsafe or inappropriate AI-generated content for review. | 新增 Aspect |

# S5. 訂餐外送系統

## 情境

| 欄位 | 內容 |
| --- | --- |
| 受訪者角色 | 顧客、餐廳營運者、外送員與平台營運方的綜合代表 |
| Application type | 訂餐外送平台 |
| Primary category | User Interaction |
| Subcategories | E-commerce、Authentication、Real-time Features |
| Initial requirements | 我想要一個線上訂餐外送平台，讓顧客可以搜尋餐廳、瀏覽菜單、加入購物車、下單付款並追蹤外送，同時讓餐廳管理菜單與訂單、外送員接收派單並完成配送、平台管理者查看營運狀態。 |

## 擴增 Aspect 訪談紀錄

### A-S5-I01 — Performance

**訪談者：** 對訂餐外送平台來說，你對速度和即時性有什麼期待？

**受訪者：** 我期望下單、付款和查詢操作能快速完成，不會讓顧客在流程中等待太久。用餐尖峰時段也應該能順利完成搜尋、下單與付款，不會因為流量變大而明顯變慢。另外，外送員位置更新要足夠即時，讓顧客能大致掌握外送進度與預估到達時間。

### A-S5-I02 — Reliability

**訪談者：** 如果平台遇到高流量、設備故障或系統異常，你希望哪些核心服務仍然被保障？

**受訪者：** 我期望主要用餐時段平台的下單、付款與追蹤功能能穩定可用。系統發生故障後，也應該能盡快恢復，而且既有訂單與付款紀錄不會遺失。如果餐廳接單設備出問題，訂單不應該卡住，而是要能被轉到備援設備或營運後台處理。

### A-S5-I03 — Security

**訪談者：** 在付款、個人資料和後台操作上，你希望平台怎麼保護使用者和營運方？

**受訪者：** 我期望付款資料與個人資料在平台上受到安全保護。顧客與外送員的電話等聯絡資訊也不應該直接互相暴露。另外，退款、帳號修改與權限變更這類高風險操作，應該只有授權人員能執行。

### A-S5-I04 — Integration

**訪談者：** 這個平台需要和哪些外部服務或子系統連接，才算支援完整的訂餐外送流程？

**受訪者：** 我期望平台能支援常見付款服務，並在付款完成後正確更新訂單狀態。訂單的重要狀態也要能透過應用程式推播、簡訊或電子郵件通知相關使用者。外送導航與顧客追蹤則需要能連接地圖與定位服務。

## 需求抽取對照

| 訪談段落 ID | Aspect | 隱性需求 | 來源類型 |
| --- | --- | --- | --- |
| A-S5-I01 | Performance | 我期望下單、付款和查詢操作能快速完成，不會讓顧客在流程中等待太久。 | 新增 Aspect |
| A-S5-I01 | Performance | 我期望用餐尖峰時段仍能順利完成搜尋、下單與付款，不會因流量變大而明顯變慢。 | 新增 Aspect |
| A-S5-I01 | Performance | 我期望外送員位置更新足夠即時，讓顧客能大致掌握外送進度與預估到達時間。 | 新增 Aspect |
| A-S5-I02 | Reliability | 我期望主要用餐時段平台的下單、付款與追蹤功能能穩定可用。 | 新增 Aspect |
| A-S5-I02 | Reliability | 我期望系統發生故障後能盡快恢復，而且既有訂單與付款紀錄不會遺失。 | 新增 Aspect |
| A-S5-I02 | Reliability | 我期望餐廳接單設備出問題時，訂單不會卡住，而是能被轉到備援設備或營運後台處理。 | 新增 Aspect |
| A-S5-I03 | Security | 我期望付款資料與個人資料在平台上受到安全保護。 | 新增 Aspect |
| A-S5-I03 | Security | 我期望顧客與外送員的電話等聯絡資訊不會直接互相暴露。 | 新增 Aspect |
| A-S5-I03 | Security | 我期望退款、帳號修改與權限變更這類高風險操作只有授權人員能執行。 | 新增 Aspect |
| A-S5-I04 | Integration | 我期望平台能支援常見付款服務，並在付款完成後正確更新訂單狀態。 | 新增 Aspect |
| A-S5-I04 | Integration | 我期望訂單的重要狀態能透過應用程式推播、簡訊或電子郵件通知相關使用者。 | 新增 Aspect |
| A-S5-I04 | Integration | 我期望外送導航與顧客追蹤能連接地圖與定位服務。 | 新增 Aspect |
