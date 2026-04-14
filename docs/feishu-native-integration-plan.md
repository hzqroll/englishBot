# EnglishBot 飞书原生化增强方案

## 文档目标

这份文档专门回答一个问题：

`在不破坏现有 DailySession 学习状态机的前提下，如何把 EnglishBot 和飞书结合得更深、更顺。`

这不是一份“迁移到飞书”的方案，而是一份“把飞书做成主前台，把后端继续保留为学习真源”的实施方案。

适用范围：

- 当前主线产品：`B2 Sprint OS`
- 当前主渠道：飞书群
- 当前核心用户：双人学习群

---

## 当前状态

### 已经有的飞书能力

1. `飞书机器人`
   - 消息入口已经接通，见 [feishu_bot.py](/Users/roll/code/github/englishBot/src/infrastructure/channels/feishu_bot.py:128)
   - 支持固定命令、`@bot` 分析/纠错、白天被动消息观察

2. `飞书互动卡片`
   - 主线卡片发送已经走飞书 `interactive` 消息，见 [feishu.py](/Users/roll/code/github/englishBot/src/infrastructure/channels/feishu.py:68)
   - 已有专用卡片 renderer：
     - `daily_session`
     - `session_reminder`
     - `progress`
     - `error_digest`
     - `weekly_report`

3. `CardKit 流式卡片`
   - `@bot` 翻译/纠错已经接入 CardKit 流式输出，见 [feishu.py](/Users/roll/code/github/englishBot/src/infrastructure/channels/feishu.py:169)

4. `飞书文档归档`
   - `FeishuDocsService` 已存在，见 [feishu_docs_service.py](/Users/roll/code/github/englishBot/src/infrastructure/docs/feishu_docs_service.py:14)
   - 定时任务发送后会自动把内容 append 到飞书文档，见 [scheduler.py](/Users/roll/code/github/englishBot/src/plugins/scheduler.py:353)

### 还没有做深的飞书能力

1. `卡片按钮回调`
   - 目前卡片主要是展示，没有形成按钮交互闭环

2. `飞书文档作为主学习档案`
   - 当前文档更像归档层，不像用户主动访问的学习入口

3. `多维表格镜像看板`
   - 当前完全未接入

4. `飞书工作流/自动化`
   - 当前外围提醒和编排主要由后端 scheduler 完成

---

## 总体原则

### 1. 后端继续做唯一真源

以下状态继续以本地后端和数据库为准，不迁到飞书做主真源：

- `DailySession`
- A/B 角色分配
- session 状态推进
- rescue mode 判定
- voice-required 判定
- 回捞与 benchmark 逻辑

原因：

- 当前主链已经围绕 `DailySession` 建立
- 白天消息证据、纠错、回捞、晚间汇总都依赖同一状态机
- 如果飞书工作流或多维表格参与主写，会出现双写和状态漂移

### 2. 飞书负责前台体验和轻编排

飞书后续承担 4 个角色：

- `群聊执行面`
- `卡片交互面`
- `文档档案面`
- `轻量看板和外围自动化`

### 3. 不把学习闭环拆成多个真源

推荐的边界：

- 后端：判断
- 飞书：展示、触发、通知、浏览

不推荐的边界：

- 飞书工作流判断用户是否完成今天任务
- 多维表格判断谁该接棒
- 卡片按钮直接越权修改复杂状态而不经过后端校验

---

## 目标架构

```text
飞书群
  -> 机器人入口
  -> 执行卡 / 提醒卡 / 晚间卡 / 周卡
  -> 卡片按钮交互

后端状态机
  -> DailySession
  -> evidence / error / recall / report
  -> card callback 处理
  -> docs / bitable / workflow webhook

飞书文档
  -> 本周冲刺文档
  -> 错误回捞文档
  -> benchmark 文档

飞书多维表格
  -> daily_sessions 镜像
  -> repair_points 镜像
  -> weekly checkpoints 镜像

飞书工作流
  -> 定时提醒
  -> HTTP webhook 调用
  -> 文档/卡片/消息联动
```

---

## Phase 1：卡片原生化

### 目标

让卡片从“展示今天内容”升级成“推动今天动作”。

### 范围

第一批只做轻交互，不做复杂表单。

建议增加的按钮：

1. `我先发起`
   - 用于执行卡
   - 作用：把卡片聚焦到 A 的动作，并返回一条简短提示

2. `查看本周文档`
   - 用于执行卡、晚间卡、周卡
   - 作用：跳转到本周冲刺文档

3. `切到保底版`
   - 用于提醒卡或执行卡
   - 作用：请求后端将当天 session 切换到 rescue 风格任务

4. `今晚再提醒我`
   - 用于中午提醒卡
   - 作用：记录一条轻量 defer 标记，晚间再补提醒一次

### 设计原则

- 按钮只触发轻动作
- 所有状态修改都经过后端
- 卡片点击结果要有明确反馈

### 实施建议

#### 新增 callback 入口

建议新增一个飞书卡片回调 HTTP 入口，例如：

- `/api/feishu/card-callback`

现有项目已经使用 FastAPI driver，见 [main.py](/Users/roll/code/github/englishBot/src/main.py:8)，并已有 API 路由体系，见 [routes.py](/Users/roll/code/github/englishBot/src/admin/routes.py:431)。

建议新增模块：

- `src/infrastructure/channels/feishu_card_callbacks.py`
- 或直接在 [routes.py](/Users/roll/code/github/englishBot/src/admin/routes.py:431) 下增加一组独立 API

#### 按钮动作建议映射

- `action=open_week_doc`
- `action=claim_baton`
- `action=enter_rescue`
- `action=remind_later`

回调处理流程：

```text
飞书卡片按钮
  -> callback endpoint
  -> 校验签名 / 解析 action
  -> 调用 DailySessionUseCase / FeishuDocsService
  -> 返回卡片 toast / 二次卡片 / 跳转链接
```

### 涉及模块

- [feishu.py](/Users/roll/code/github/englishBot/src/infrastructure/channels/feishu.py:68)
- [daily_session_usecases.py](/Users/roll/code/github/englishBot/src/application/daily_session_usecases.py:18)
- [routes.py](/Users/roll/code/github/englishBot/src/admin/routes.py:431)

### 测试用例

1. 点击 `查看本周文档` 后，返回有效 doc 链接
2. 点击 `切到保底版` 后，当天 session 标记为 rescue 风格
3. 非本群成员触发按钮时，不越权修改状态
4. 重复点击同一按钮，不会重复写脏状态

### 边界

- 第一版不做复杂多选表单
- 第一版不做按钮级别的完整权限系统
- 第一版不在按钮里直接推进 A/B 完成状态

---

## Phase 2：飞书文档升级为学习档案

### 目标

让飞书文档从“推送后的附带归档”升级成“用户会主动打开的学习档案”。

### 文档类型

建议固定为 3 类文档：

1. `本周冲刺文档`
2. `错误回捞文档`
3. `月度 benchmark 文档`

### 当前能力

现有 `FeishuDocsService` 已支持：

- 周文档 append，见 [feishu_docs_service.py](/Users/roll/code/github/englishBot/src/infrastructure/docs/feishu_docs_service.py:32)
- Friends 按集文档 append，见 [feishu_docs_service.py](/Users/roll/code/github/englishBot/src/infrastructure/docs/feishu_docs_service.py:84)

### 要扩展的能力

#### 本周冲刺文档

固定结构建议：

1. 周主题
2. 本周 7 天执行卡摘要
3. 高频错误
4. 必须回捞表达
5. 周复盘摘要

#### 错误回捞文档

按周或按月组织：

1. 错误表达
2. 正确表达
3. 场景说明
4. 最近复发时间
5. 是否已稳定

#### benchmark 文档

结构建议：

1. speaking prompt
2. writing prompt
3. rubric
4. 本月结果
5. 与上月变化

### 实施建议

#### 扩展 `FeishuDocsService`

建议新增方法：

- `ensure_weekly_sprint_doc(...)`
- `append_daily_session_summary(...)`
- `append_repair_points(...)`
- `append_benchmark_result(...)`

#### 卡片直接带文档入口

下列卡片统一加入文档入口：

- `daily_session`
- `progress`
- `error_digest`
- `weekly_report`

### 涉及模块

- [feishu_docs_service.py](/Users/roll/code/github/englishBot/src/infrastructure/docs/feishu_docs_service.py:14)
- [scheduler.py](/Users/roll/code/github/englishBot/src/plugins/scheduler.py:413)
- [report_usecases.py](/Users/roll/code/github/englishBot/src/application/report_usecases.py:48)

### 测试用例

1. 晨间执行卡发送后，周文档追加一段当天摘要
2. 晚间修正卡发送后，错误回捞文档追加重点错误
3. 重复发送同一天卡片时，不重复 append 同一段内容
4. 文档创建失败时，不影响群里卡片发送

### 边界

- 文档仍然不是主状态机
- 文档内容允许最终一致，不要求强实时

---

## Phase 3：多维表格作为镜像看板

### 目标

在飞书里直接看到学习状态，而不必进管理后台。

### 原则

多维表格只做镜像，不做真源。

### 建议表结构

#### 表 1：`daily_sessions`

字段建议：

- `biz_date`
- `group_chat_id`
- `session_status`
- `role_a_name`
- `role_a_status`
- `role_b_name`
- `role_b_status`
- `voice_required`
- `rescue_mode`
- `required_chunks`
- `doc_url`

#### 表 2：`repair_points`

字段建议：

- `biz_date`
- `expression_wrong`
- `expression_right`
- `error_type`
- `source_card`
- `is_recalled`
- `last_seen_at`

#### 表 3：`weekly_checkpoints`

字段建议：

- `week_key`
- `theme`
- `completed_days`
- `voice_days_completed`
- `high_frequency_errors`
- `next_week_focus`

### 实施建议

建议新增一个 bitable 同步层，不把多维表格写进 usecase 里。

新增模块建议：

- `src/infrastructure/bitable/feishu_bitable_client.py`
- `src/infrastructure/bitable/feishu_bitable_sync_service.py`

同步方式建议：

- 晨间创建/更新 session 后同步一次
- 晚间 progress / error_digest 后同步一次
- 周报后同步 checkpoint 一次

### 涉及模块

- [daily_session_usecases.py](/Users/roll/code/github/englishBot/src/application/daily_session_usecases.py:18)
- [report_usecases.py](/Users/roll/code/github/englishBot/src/application/report_usecases.py:48)
- [scheduler.py](/Users/roll/code/github/englishBot/src/plugins/scheduler.py:376)

### 测试用例

1. 新建当天 session 后，多维表格新增一条镜像记录
2. A/B 状态变化后，同步更新对应字段
3. 同一天重复同步时，正确 upsert，而不是新增重复行
4. 多维表格接口失败时，不阻塞主学习流程

### 边界

- 第一版不做多维表格双向编辑
- 不允许用户在多维表格里直接改主状态

---

## Phase 4：飞书工作流承接外围自动化

### 目标

把“提醒、延迟、消息联动”这种外围流程逐步从后端定时器中解耦一部分出来，但不动主判断。

### 适合放到工作流的事情

1. 中午未接棒提醒
2. 晚间补发保底版提醒
3. 文档更新后发送链接消息
4. benchmark 前一日提醒

### 不适合放到工作流的事情

1. 判断用户今天的英文是否算完成
2. 推导 A/B 是否完成
3. 生成错误点和掌握判断
4. rescue mode 主判定

### 推荐接法

工作流只做两类触发：

1. `定时触发`
2. `HTTP webhook 触发`

后端提供轻量接口，例如：

- `/api/feishu/hooks/reminder`
- `/api/feishu/hooks/doc-updated`
- `/api/feishu/hooks/benchmark-reminder`

### 实施建议

#### 第一阶段

先保留 APScheduler 为主调度器，只把一个非核心提醒迁给飞书工作流验证。

推荐第一个试点：

- `benchmark 前一日提醒`

因为它：

- 与主学习链路耦合低
- 对时序要求清晰
- 即使失败也不影响当天学习主线

#### 第二阶段

再考虑把：

- `中午接棒提醒`
- `晚间补发保底卡`

迁出部分触发逻辑给工作流。

### 涉及模块

- [scheduler.py](/Users/roll/code/github/englishBot/src/plugins/scheduler.py:376)
- [routes.py](/Users/roll/code/github/englishBot/src/admin/routes.py:704)

### 测试用例

1. 工作流调用 reminder webhook 后，后端成功生成提醒卡
2. 同一个 webhook 重复触发，不会重复发多次卡
3. webhook 缺少必要参数时，后端返回明确错误
4. 工作流故障时，后端现有 scheduler 仍可兜底

### 边界

- 不做“全量调度器迁移”
- 不把 APScheduler 一次性换掉

---

## 推荐实施顺序

按 ROI 和风险排序，推荐这样做：

1. `Phase 1`
   - 卡片按钮与 callback
   - 成本低，用户感知最强

2. `Phase 2`
   - 文档升级为学习档案
   - 能显著提升“系统感”和可回看性

3. `Phase 3`
   - 多维表格镜像看板
   - 强化运营可见性

4. `Phase 4`
   - 工作流承接外围自动化
   - 最后做，避免过早把逻辑拆散

---

## 代码落点清单

### 必改

- [src/infrastructure/channels/feishu.py](/Users/roll/code/github/englishBot/src/infrastructure/channels/feishu.py:68)
  - 卡片按钮定义
  - 文档链接入口

- [src/application/daily_session_usecases.py](/Users/roll/code/github/englishBot/src/application/daily_session_usecases.py:18)
  - callback 可触发的轻动作
  - rescue / defer / open-doc 数据组装

- [src/application/report_usecases.py](/Users/roll/code/github/englishBot/src/application/report_usecases.py:48)
  - 晚间卡和周卡文档入口
  - 文档摘要输出

- [src/infrastructure/docs/feishu_docs_service.py](/Users/roll/code/github/englishBot/src/infrastructure/docs/feishu_docs_service.py:14)
  - 学习档案结构化 append

### 新增建议

- `src/infrastructure/channels/feishu_card_callbacks.py`
- `src/infrastructure/bitable/feishu_bitable_client.py`
- `src/infrastructure/bitable/feishu_bitable_sync_service.py`

---

## 验收标准

### 第一阶段完成标准

1. 执行卡、提醒卡、晚间卡都能打开相关文档入口
2. 至少 2 个按钮动作可用，并经过后端校验
3. 文档不再只是被动归档，而有固定学习档案结构

### 第二阶段完成标准

1. 飞书里能直接看到 session 镜像看板
2. 不进入管理后台，也能知道今天是否完成、谁没接棒、最近在反复错什么

### 第三阶段完成标准

1. 至少有 1 个外围提醒由飞书工作流触发
2. 主学习状态机仍然保持在后端

---

## 参考

飞书官方能力参考：

- 消息发送 API  
  https://open.feishu.cn/document/server-docs/im-v1/message/create

- 事件订阅  
  https://open.feishu.cn/document/server-docs/event-subscription-guide/event-list

- 多维表格自动化  
  https://www.feishu.cn/content/article/7581775868524104882

- 多维表格工作流  
  https://www.feishu.cn/content/article/7595146589556788441

---

## 一句话结论

`更好地和飞书结合，不是把逻辑搬进飞书，而是把飞书做成这个系统的原生前台。`
