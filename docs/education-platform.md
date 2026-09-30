# 教育智能体与数字人融合说明

## 项目结构

- `education/`：从本机 DeepTutor 源码并入的主应用，保留 Python API、Next.js 前端、教学 Agent、知识库、记忆和学习功能，以及原 Apache-2.0 许可证与第三方声明。
- `education/web/app/(workspace)/digital-human/`：主应用中的“数字人讲解”页面。
- 根目录 `app.py`、`server/`、`avatars/`、`tts/`：LiveTalking 数字人服务。
- `education/deeptutor/api/routers/digital_human.py`：在 DeepTutor 身份与会话作用域内运行教学 Agent，取最终答案并拆成短播报段。
- `education/deeptutor/api/routers/teacher.py` 与 `education/deeptutor/services/teacher_classes.py`：当前账号学情报告、学生主动加入的班级与班级汇总。
- `data/avatars/teacher-tutor/`：教师形象的单帧 Wav2Lip Avatar 数据；原始生成图在 `web/assets/teacher-avatar.png`。

教师 Avatar 使用单帧图像驱动口型，形象本身没有预制的眨眼或身体动作。算力云上如需更丰富的动作，可替换为按 LiveTalking 格式制作的视频 Avatar。

## 用户流程

1. 学生在 DeepTutor 左侧选择“数字人讲解”，输入或录音转写学习问题，选择互动答疑或深入讲解，可指定已创建的知识库名称。语音提问使用 DeepTutor 原有 `/api/voice/stt` 接口，由学生确认文字后提交。
2. 页面请求 DeepTutor 的 `/api/chat/digital-human/ask`，在主应用的身份作用域内调用教学 Agent，并沿用 `session_id`。
3. 最终答案显示在页面中。若 WebRTC 已连接，页面按标点和长度顺序将答案片段提交到 `/human`，由 TTS 和数字人播报。
   若 Agent 需要补充信息，桥接层会释放等待中的回合，将问题显示在页面并保留学习会话，学生在输入框继续回答；长时间无响应的回合会超时释放。
4. 数字人未连接时仍可显示教学答案；连接前的教师图明确标记为预览。
5. “个性化学习”主页显示已到期复习、今日完成与错题数量，继续进入原有 Practice 流程。教师或学生可在“教学分析”查看本账号记录；班级创建者生成邀请码，学生主动加入后，创建者可查看这些成员的练习统计、已测评且掌握度低于 60% 的知识点、尚未结案的结构化错误类型。学生退出后，班级报告不再读取其数据。
6. 学生可在提问前自选“题意、方法、计算或推理、不确定”卡点并补充自述。智能体将此作为教学引导信息，不将学生自述当作已核实的错因。答案下方展示本轮真实检索到的资料标题、页码、片段或安全的网页链接；没有可核对来源时不显示来源卡片。
7. 讲解完成后，学生可主动点击“生成一题检验”。`/api/learning-checks` 使用本次问题和答案调用 DeepQuestion 生成单道选择题，标准答案在作答前只保存在当前账号的私有 SQLite 数据中；提交后按现有题本与 Practice 规则记录作答，错题进入复习。该检验题不会伪装成 Mastery Path 的正式掌握度测评。
8. “教学分析”的下一步建议依照已到期题目、已测评且低掌握的知识点和未结案的结构化错误记录确定性生成；班级成员建议只提供给教师查看的文字，不生成跨账号访问学生私有路径的链接。资料读取不完整时页面标记结果可能遗漏。

## 算力云部署准备

本次只交付代码，不安装本机依赖、下载模型或配置算力云。部署机需分别准备 `requirements.txt` 与 `education/pyproject.toml` 的 Python 依赖，以及 `education/web/package.json` 的 Node 依赖。DeepTutor 数据目录为 `education/data/`，需持久化；数字人模型权重按 LiveTalking 原说明放入 `models/`，当前仓库没有 Wav2Lip 权重。

同机部署时，Qwen 使用 8000、DeepTutor API 使用 8001、BGE-M3 使用 8002、SenseVoice 使用 8003、LiveTalking 使用 8010；这些端口只监听 `127.0.0.1`。Next.js 默认监听 `0.0.0.0:6006`，作为 AutoDL “自定义服务”的唯一公网入口。Next.js 服务端通过同源 `/api/*`、`/ws/*` 和 `/digital-api/*` 分别代理 DeepTutor 与数字人，因此浏览器不需要直接访问内部端口。分容器部署时应把数字人 HTTP 端口限制在内部网络，修改代理地址，并按 WebRTC 的部署方式开放媒体网络。
数字人代理只转发同源的 JSON POST 请求，避免第三方网页借登录 Cookie 创建数字人会话。

依赖与模型准备完成后，可在同一台 Linux 算力云主机运行 `bash scripts/start_platform.sh`。脚本首次启动会在缺少构建产物时构建 Next.js，然后在后台启动六个服务，并把 PID 与日志写到 `/root/autodl-tmp/education-platform-runtime/`。Qwen3-8B 使用 BF16、16K 上下文和 70% 显存上限；BGE-M3 与 SenseVoice 默认放在 CPU，给 Wav2Lip 保留显存。可通过 `LLM_GPU_MEMORY_UTILIZATION`、`LLM_MAX_MODEL_LEN`、`EMBEDDING_DEVICE` 和 `STT_DEVICE` 调整资源使用。运行 `bash scripts/status_platform.sh` 查看状态，运行 `bash scripts/stop_platform.sh` 停止全部服务。数字人形象和语音可通过 `DIGITAL_HUMAN_AVATAR`、`DIGITAL_HUMAN_TTS`、`DIGITAL_HUMAN_TTS_SERVER` 调整。

DeepTutor API 管理学习会话和 `education/data/`；LiveTalking 只管理数字人音视频。班级功能需要开启 DeepTutor 多用户模式，并使用其本地身份库里的有效账号；当前没有独立的“教师”角色，班级创建者即为报告查看者。班级邀请码摘要及成员关系保存在 `education/data/system/teacher_classes.sqlite3`，也需随数据目录持久化。多实例部署 DeepTutor 时应配置其自身支持的 Redis 协调后端，并为这个 SQLite 班级库使用共享存储或迁移到集中式数据库。模型供应商、知识库、STT 与 TTS 按两个上游项目原有配置方式填写；不要把 API Key 或用户数据提交到仓库。

## 与简历截图的对应

| 能力 | 当前代码依据 |
| --- | --- |
| 教学 Agent、多步骤解题、知识库、记忆与练习 | `education/deeptutor/` 原有模块，当前页面已接入 chat/deep_solve 与可选知识库 |
| 数字人 WebRTC、TTS、打断与分段播报 | LiveTalking 原有模块及本次桥接；当前在教学答案完成后开始分段播报，尚未做可撤回 Agent 内容的边生成边播报 |
| 教师形象与教育页面 | 本次新增教师 Avatar 数据、DeepTutor 数字人页面及 LiveTalking 教育调试页 |
| 学习与班级报告 | 已有复习/练习数据加本次班级主动加入、授权汇总；低掌握点只统计 Mastery Path 已测评目标，错误类型只统计该路径尚未结案的结构化记录 |
| 诊断引导、检验题、来源与下一步建议 | 学生自选卡点提示、真实来源事件、DeepQuestion 单题检验与 Practice 记录、基于已有学情的规则化建议；检验题不会直接改写 Mastery Path 评分 |
| LangGraph Supervisor、Milvus、PostgreSQL、BGE-M3、图中全部多 Agent 细节 | 目前并非这两份源码的已验证实现，不能作为本次交付或简历的已完成技术点 |

## 验证范围

`python -m pytest tests -q` 覆盖 DeepTutor 最终答案提取、会话透传、失败不播报、分段及来源事件；DeepTutor 的单题检验、卡点提示、教师建议和班级权限另有专门测试。由于本机缺少 Wav2Lip 模型权重、完整前端依赖且本次不配置环境，真实 GPU 口型渲染、云端模型问答、DeepQuestion 出题质量、语音转写与完整 Next.js 构建需在算力云部署时验证。
