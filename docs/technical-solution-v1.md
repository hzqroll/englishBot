# English Learning QQ Bot 第一版技术方案

## 文档说明

- 文档定位：第一版技术方案
- 当前版本：V1
- 最后更新：2026-04-06
- 适用范围：`/Users/roll/code/github/englishBot`

## 1. 总体技术目标

第一版目标是在现有 `NoneBot2 + NapCat + FastAPI + SQLite` 单体项目基础上，扩展出完整的英语学习群闭环能力：

- 07:30 生成并推送每日学习包
- 次日对前一天内容进行定向回捞
- 白天全量采集群聊并做学习分析
- `@机器人` 继续承担翻译/纠错/润色能力
- 18:00 自动推送个人错误整理卡
- 20:00 自动推送个人学习进度与掌握度卡
- 周期性输出周报和周测

该方案保持单体部署，不引入新的独立服务。

## 2. 总体架构

### 2.1 运行形态

- `NoneBot2`
  - 群消息接入
  - 命令处理
  - `@机器人` 处理
- `FastAPI`
  - 后台管理
  - 手动触发任务
  - 调试与运维接口
- `APScheduler`
  - 每日和每周定时任务
- `SQLite`
  - 全部业务数据持久化
- `NapCat`
  - QQ 协议接入层

### 2.2 启动结构

主入口继续使用：

- [`src/main.py`](/Users/roll/code/github/englishBot/src/main.py)

依赖注入继续使用全局容器：

- [`src/infrastructure/settings/container.py`](/Users/roll/code/github/englishBot/src/infrastructure/settings/container.py)

## 3. 模块划分

第一版采用“按业务域分模块”的组织方式，在现有分层基础上逐步收拢到业务域。

### 3.1 模块列表

- `identity`
  - 用户、群、报名关系、等级、积分、连续学习
- `curriculum`
  - 词库、主题、每日学习包、对话和任务生成
- `conversation`
  - 群聊全量采集、语言识别、学习证据提取、按日会话分析
- `language_coach`
  - `@机器人` 翻译、纠错、表达润色、错误沉淀
- `review`
  - 错误点、复习项、错题回捞、次日回捞、间隔复习
- `assessment`
  - 晚间总结、周报、周测、掌握度评估
- `delivery`
  - 图片卡片渲染、消息投递、推送审计

### 3.2 模块依赖规则

- `plugins` 与 `admin` 只调用 application service
- 模块之间只通过 application service 或公开接口依赖
- 不允许跨模块直接操作对方的表或 ORM
- `infrastructure` 提供数据库、配置、Provider、消息发送等公共能力

主要依赖关系如下：

- `curriculum` -> `identity`
- `conversation` -> `curriculum`
- `language_coach` -> `review`
- `assessment` -> `conversation` + `review` + `curriculum` + `identity`
- `delivery` -> `assessment` / `curriculum`

## 4. 包结构建议

在保留当前 `src/application`、`src/domain`、`src/infrastructure` 的前提下，逐步按业务域重组：

- `src/modules/identity/`
- `src/modules/curriculum/`
- `src/modules/conversation/`
- `src/modules/language_coach/`
- `src/modules/review/`
- `src/modules/assessment/`
- `src/modules/delivery/`

每个模块内部建议统一为：

- `application/`
- `domain/`
- `persistence/`
- `providers/`（按需）

第一阶段允许与现有目录并存，逐步迁移。

## 5. 模型设计

### 5.1 领域模型

- `UserProfile`
  - 表示用户的学习身份
- `GroupSpace`
  - 表示一个启用的学习群
- `Enrollment`
  - 报名关系
- `LexiconEntry`
  - 静态词库中的单词或词块
- `ThemeScenario`
  - 每日主题，如改会、催进度、同步状态
- `DailyLearningPackage`
  - 当日学习包聚合根
- `ReviewCandidate`
  - 次日回捞候选项
- `ConversationMessage`
  - 群内原始发言
- `ConversationEvidence`
  - 从消息中抽取的学习证据
- `CorrectionRecord`
  - 一次纠错行为结果
- `ErrorPoint`
  - 长期错误聚合点
- `ReviewItem`
  - 可进入间隔复习的项目
- `DailyLearningSnapshot`
  - 某用户某日的学习快照
- `WeeklyAssessment`
  - 周报、周测相关聚合
- `MessageEnvelope`
  - 统一消息输出模型

### 5.2 模型依赖关系

- `DailyLearningPackage`
  - 由 `ThemeScenario + LexiconEntry[] + 对话/任务生成结果` 组成
- `ConversationEvidence`
  - 来源于 `ConversationMessage + DailyLearningPackage + CorrectionRecord`
- `ReviewCandidate`
  - 来源于前一日 `ErrorOccurrence + DailyLearningSnapshot + DailyTargetItems`
- `DailyLearningSnapshot`
  - 来源于 `ConversationEvidence + ErrorOccurrence + TaskSubmission + Quiz/Review Stats`
- `ReviewItem`
  - 来源于 `ErrorPoint` 或错题
- `WeeklyAssessment`
  - 来源于 `DailyLearningSnapshot + QuizSession + ErrorPoint`

## 6. 数据库设计

### 6.1 保留的现有表

- `users`
- `groups`
- `enrollments`
- `message_events`
- `interaction_results`
- `error_points`
- `error_occurrences`
- `review_items`
- `content_items`
- `daily_lessons`
- `daily_tasks`
- `task_submissions`
- `quiz_sessions`
- `quiz_questions`
- `quiz_answers`
- `weekly_reports`
- `user_levels`
- `points_ledger`
- `streaks`
- `runtime_settings`
- `admin_users`
- `job_runs`

### 6.2 扩展现有表

#### `message_events`

在现有结构上新增以下字段：

- `source_type`
  - `passive_group_message`
  - `at_message`
  - `learning_command`
  - `system_push`
- `is_to_bot`
- `is_command`
- `language_guess`
- `analysis_status`
  - `pending`
  - `tagged`
  - `summarized`
- `biz_date_local`

目的：

- 支持普通群聊全量采集
- 支持后续按日分析

#### `daily_lessons`

升级为“每日学习包根表”，建议增加：

- `theme_key`
- `title`
- `package_snapshot_json`

### 6.3 新增表

#### `conversation_evidences`

记录从群聊中抽取的学习证据。

核心字段：

- `message_event_id`
- `user_id`
- `group_id`
- `biz_date`
- `evidence_type`
- `evidence_score`
- `payload_json`
- `created_at`

#### `daily_learning_snapshots`

记录每人每天的学习聚合快照。

核心字段：

- `biz_date`
- `user_id`
- `group_id`
- `lesson_id`
- `summary_json`
- `mastery_level`
- `mastery_reason`
- `model_summary`
- `activity_score`
- `evidence_score`
- `generated_at`

唯一约束：

- `(biz_date, user_id, group_id)`

#### `daily_card_snapshots`

保存每天实际发送的卡片快照。

核心字段：

- `biz_date`
- `user_id`
- `group_id`
- `card_type`
  - `daily_package`
  - `error_digest`
  - `progress`
- `card_document_json`
- `plain_text`
- `image_paths_json`
- `created_at`

#### `message_delivery_logs`

记录实际投递情况。

核心字段：

- `group_id`
- `user_id`
- `job_name`
- `card_snapshot_id`
- `delivery_mode`
- `success`
- `provider_response`
- `created_at`

#### `daily_target_items`

保存当天学习包中的目标词和词块快照。

核心字段：

- `lesson_id`
- `entry_key`
- `entry_type`
- `text`
- `phonetic`
- `meaning_zh`
- `usage_scene`
- `example`
- `target_role`
  - `core_chunk`
  - `support_word`
- `sort_order`

#### `review_candidates`

保存前一天为次日学习包准备的回捞候选项。

核心字段：

- `biz_date`
- `user_id`
- `group_id`
- `lesson_id`
- `source_type`
  - `error_point`
  - `core_chunk`
  - `low_mastery_item`
- `source_ref_id`
- `content_text`
- `correct_text`
- `priority_score`
- `selected_for_next_day`
- `used_in_next_day_task`
- `recalled_successfully`
- `created_at`

### 6.4 关系设计

- `users 1-N enrollments`
- `groups 1-N enrollments`
- `users 1-N message_events`
- `message_events 1-N interaction_results`
- `message_events 1-N error_occurrences`
- `message_events 1-N conversation_evidences`
- `error_points 1-N review_items`
- `groups 1-N daily_lessons`
- `daily_lessons 1-N daily_target_items`
- `daily_lessons 1-N review_candidates`
- `daily_lessons 1-N daily_tasks`
- `daily_tasks 1-N task_submissions`
- `daily_lessons 1-N daily_learning_snapshots`
- `daily_learning_snapshots 1-N daily_card_snapshots`
- `daily_card_snapshots 1-N message_delivery_logs`

### 6.5 索引与 SQLite 策略

建议新增索引：

- `message_events(group_id, user_id, biz_date_local)`
- `conversation_evidences(user_id, group_id, biz_date, evidence_type)`
- `daily_learning_snapshots(user_id, group_id, biz_date)`
- `daily_card_snapshots(user_id, group_id, biz_date, card_type)`
- `review_candidates(user_id, group_id, biz_date, selected_for_next_day)`

SQLite 继续使用，但默认开启：

- `WAL`
- `busy_timeout`

Schema 升级建议从自动建表切换到 `Alembic` 显式迁移。

## 7. 可插拔能力设计

### 7.1 LLM Provider

继续采用统一 Provider 抽象，可替换实现，底层默认用 OpenAI 兼容接口。

建议按能力拆接口：

- `LanguageCoachProvider`
  - 英文纠错
  - 中文转英文优化
  - 表达润色
- `ConversationAnalysisProvider`
  - 单条消息学习证据提取
  - 按人按日对话总结
  - 掌握度判断
- `CurriculumGenerationProvider`
  - 基于主题和词包生成办公室情景对话
  - 生成输出任务
- `SummaryGenerationProvider`
  - 晚间卡片总结文案
  - 周报文案

所有输出必须走结构化 JSON，并做 schema 校验。

### 7.2 翻译 Provider

翻译接口独立抽象：

- `detect_language(text)`
- `translate(text, source_lang, target_lang)`

当前默认实现保持为腾讯翻译。

翻译主要服务于：

- `@机器人` 中文转英文
- `@机器人` 语言识别
- 纠错链路中的辅助翻译

### 7.3 词库与主题内容源

词库来源采用仓库内静态文件维护。

建议目录：

- `resources/lexicon/`
- `resources/themes/`

词库字段至少包含：

- `entry_key`
- `entry_type`
- `text`
- `phonetic`
- `meaning_zh`
- `usage_scene`
- `example`
- `difficulty`
- `tags`

主题字段至少包含：

- `theme_key`
- `title`
- `scene_type`
- `tags`
- `recommended_targets`

## 8. 每日内容生成方案

### 8.1 目标词与词块

每日学习包固定为：

- 昨日回顾 3 条
- 5 个核心词块
- 5 个支持词汇

规则如下：

- 从静态词库中按当天主题筛选候选集
- 优先选核心商务词块
- 再补支持词汇
- 避免与近 3 天完全重复
- 若用户近期高频错误与候选集相关，可提高优先级
- 学习包中的“昨日回顾”固定来自 `review_candidates`

### 8.2 对话与任务生成

生成流程固定为：

- `theme + targets -> LLM 生成办公室情景对话`
- `theme + targets + dialogue -> LLM 生成 2-3 个输出任务`
- `yesterday review candidates + new targets -> LLM 生成至少 1 个带回捞要求的任务`

生成结果保存到：

- `daily_lessons.package_snapshot_json`
- `daily_tasks`
- `daily_target_items`
- `review_candidates`

## 9. 关键流程设计

### 9.1 07:30 学习包推送

流程：

- 从前一天数据中选出 3 个回捞点
- 读取主题和词库
- 选出当天词包
- 生成对话与任务，其中至少 1 题嵌入昨日回捞点
- 保存学习包快照
- 生成学习包图片卡并发群

次日回捞选点规则固定为：

- 高频错误优先
- 昨日核心词块次之
- 掌握度偏低表达再次优先
- 每日只选 3 个，避免负担过重

### 9.2 白天群聊采集

新增一个低优先级被动监听插件：

- 监听所有群文本消息
- 不主动回复
- 把原始发言写入 `message_events`
- 做基础标注：
  - 是否英语尝试
  - 是否命中今日目标词
  - 是否命令
  - 是否 `@机器人`
- 写入 `conversation_evidences`

### 9.3 `@机器人` 实时能力

保留现有职责：

- 翻译
- 英文纠错
- 表达润色
- 语法解释

同时把纠错结果继续写入：

- `interaction_results`
- `error_points`
- `error_occurrences`
- `review_items`

### 9.4 18:00 错误整理

只针对报名用户。

输入数据：

- 当日 `error_occurrences`
- 当日英语相关 `conversation_evidences`

输出：

- 错词/表达
- 语法问题
- 修正方式
- 今晚建议

结果保存到：

- `daily_card_snapshots(card_type=error_digest)`

### 9.5 20:00 学习进度与掌握度

只针对报名用户。

输入数据：

- 当日 `message_events`
- `conversation_evidences`
- `interaction_results`
- `error_occurrences`
- `task_submissions`
- `points_ledger`
- `review` 与 `quiz` 统计

流程：

- 先做行为与证据聚合
- 再由模型做掌握度判断和文案总结
- 生成 `daily_learning_snapshots`
- 再生成 `daily_card_snapshots(card_type=progress)`

输出固定包含：

- 今日参与概览
- 学习证据摘要
- 昨日回捞表现
- 掌握度判断
- 典型错误或进步
- 明日建议

### 9.6 周报与周测

周报直接读取 `daily_learning_snapshots` 聚合，不再从零扫描全部消息。

周测题源优先级：

- 本周核心词块
- 本周高频错误
- 本周场景表达

周测结果继续回流 `review_items` 和周报统计。

## 10. 配置与非功能设计

### 10.1 配置

继续沿用：

- `.env`
- `config.yaml`
- `runtime_settings`

建议新增配置项：

- 07:30 学习包 cron
- 词包数量
- 次日回捞数量
- 主题轮换顺序
- 是否启用被动群聊采集
- 晚间总结模板版本

### 10.2 后台管理

后台管理需要覆盖学习群配置，而不是继续依赖手改 `config.yaml`。

第一版后台需新增以下能力：

- 学习群管理
  - 查看当前启用群
  - 新增群号
  - 修改群号
  - 启用/停用群
  - 设置群显示名称
- 管理群配置
  - 设置是否为管理员群
  - 设置该群是否启用学习功能
- 内容运营
  - 手动触发 07:30 学习包
  - 手动触发 18:00/20:00 卡片
  - 预览当天学习包与次日回捞点

群号管理的数据来源固定为数据库 `groups` 表，而不是 `config.yaml`。

配置读取策略固定为：

- `config.yaml` 只提供初始群列表和默认值
- 后台修改后，以数据库中的 `groups` 状态为运行时唯一事实来源
- `RuntimeConfigService.enabled_group_ids()` 和 `admin_group_ids()` 优先读取数据库，再回退到静态配置

为支持后台直接管理群号，`groups` 表建议扩展：

- `is_admin_group`
- `updated_at`
- `notes`（可选）

### 10.3 幂等与快照

所有定时任务继续写 `job_runs`：

- 每日任务用 `YYYY-MM-DD`
- 每周任务用 `YYYY-WW`

保存完整快照：

- 学习包快照
- 晚间卡片快照
- 日学习快照

便于：

- 重发
- 排查
- 历史复盘

### 10.4 可观测性

需要持续记录：

- 任务执行状态
- 卡片渲染结果
- 消息发送结果
- LLM 调用失败与降级

### 10.5 降级策略

- 学习包生成失败：
  - 回退到静态模板对话和基础任务
- 晚间总结失败：
  - 回退到规则统计版卡片
- LLM 失败：
  - 不阻断原始消息采集
- 翻译失败：
  - 返回明确提示，不阻断会话记录

## 11. V1 边界

第一版明确不做：

- 多群租户隔离优化
- 每人单独难度路径
- 音频发音链路
- 词库后台运营编辑器
- 独立消息分析服务
- Redis / MQ / 独立 worker

第一版默认：

- 单群试点
- 全群统一难度
- 静态词库维护
- 群聊全量采集
- 晚间个性化总结只给报名用户

## 12. 实施顺序建议

### 阶段 1

- 扩展 `message_events`
- 新增被动群聊采集插件
- 新增 `conversation_evidences`

### 阶段 2

- 引入静态词库与主题库
- 生成 07:30 学习包
- 新增 `daily_target_items`

### 阶段 3

- 新增 `daily_learning_snapshots`
- 重构 20:00 学习进度为对话驱动总结
- 打通 18:00 错误整理与全量群聊证据

### 阶段 4

- 周报改为读取日快照
- 周测与本周场景回捞联动
- 后台增加学习快照和投递日志查看
