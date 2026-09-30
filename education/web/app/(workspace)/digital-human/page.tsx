"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { BookOpen, Mic2, Play, Square, Volume2 } from "lucide-react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import { scopedUrl } from "@/lib/workspace-scope";
import LearningCheckPanel from "./LearningCheckPanel";
import LearningSources from "./LearningSources";

type ApiResponse<T> = { code: number; msg: string; data?: T };
type TutorAnswer = { session_id: string; turn_id: string; answer: string; sources: unknown[]; speech_segments: string[]; needs_input?: boolean };
type OfferAnswer = { sdp: string; type: string; sessionid: string };
type Difficulty = "" | "understand_problem" | "choose_method" | "calculation_or_reasoning" | "unsure";
type AnsweredLesson = { turnId: string; sessionId: string; question: string; answer: string; kbName: string };

async function post<T>(path: string, body: object, digital = true, keepalive = false, signal?: AbortSignal): Promise<T> {
  const response = await fetch(digital ? `/digital-api${path}` : scopedUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive,
    signal,
  });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`服务未返回可用结果（HTTP ${response.status}）`);
  }
  const envelope = payload as Partial<ApiResponse<T>>;
  if (!response.ok || (envelope.code !== undefined && envelope.code !== 0)) {
    const detail = (payload as { detail?: unknown }).detail;
    throw new Error(envelope.msg || (typeof detail === "string" ? detail : `请求失败（HTTP ${response.status}）`));
  }
  return (envelope.code === 0 ? envelope.data : payload) as T;
}

function releaseAvatarSession(sessionid: string) {
  void post<object>("/close", { sessionid }, true, true).catch(() => {});
}

async function waitForIce(peer: RTCPeerConnection): Promise<void> {
  if (peer.iceGatheringState === "complete") return;
  await new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => {
      peer.removeEventListener("icegatheringstatechange", check);
      reject(new Error("数字人连接超时，请检查 WebRTC 网络配置"));
    }, 12000);
    function check() {
      if (peer.iceGatheringState === "complete") {
        clearTimeout(timeout);
        peer.removeEventListener("icegatheringstatechange", check);
        resolve();
      }
    }
    peer.addEventListener("icegatheringstatechange", check);
  });
}

export default function DigitalHumanPage() {
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const avatarSessionRef = useRef("");
  const tutorSessionRef = useRef("");
  const speechGenerationRef = useRef(0);
  const speechAbortRef = useRef<AbortController | null>(null);
  const askInFlightRef = useRef(false);
  const voiceStartPendingRef = useRef(false);
  const mountedRef = useRef(true);
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [connection, setConnection] = useState<"idle" | "connecting" | "connected">("idle");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<unknown[]>([]);
  const [answeredLesson, setAnsweredLesson] = useState<AnsweredLesson | null>(null);
  const [difficulty, setDifficulty] = useState<Difficulty>("");
  const [studentNote, setStudentNote] = useState("");
  const [mode, setMode] = useState<"chat" | "deep_solve">("chat");
  const [knowledgeBases, setKnowledgeBases] = useState("");
  const [busy, setBusy] = useState(false);
  const [voiceStarting, setVoiceStarting] = useState(false);
  const [voiceTranscriptReady, setVoiceTranscriptReady] = useState(false);
  const [voiceStartError, setVoiceStartError] = useState("");
  const [message, setMessage] = useState("可以先文字提问，也可以连接数字人听语音讲解。");
  const recorder = useVoiceRecorder((text) => {
    if (!mountedRef.current) return;
    setQuestion((current) => current.trim() ? `${current.trimEnd()} ${text}` : text);
    setVoiceTranscriptReady(true);
  });

  function toggleVoiceRecording() {
    if (recorder.state === "recording") {
      recorder.stop();
      return;
    }
    if (recorder.state !== "idle" || voiceStartPendingRef.current) return;
    voiceStartPendingRef.current = true;
    setVoiceStarting(true);
    setVoiceTranscriptReady(false);
    setVoiceStartError("");
    void recorder.start().catch((error: unknown) => {
      if (mountedRef.current) setVoiceStartError(error instanceof Error ? error.message : "录音启动失败，请重试。");
    }).finally(() => {
      voiceStartPendingRef.current = false;
      if (mountedRef.current) setVoiceStarting(false);
      else recorder.stop();
    });
  }

  function disconnect() {
    speechGenerationRef.current += 1;
    speechAbortRef.current?.abort();
    const peer = peerRef.current;
    peerRef.current = null;
    peer?.close();
    if (videoRef.current) videoRef.current.srcObject = null;
    if (audioRef.current) audioRef.current.srcObject = null;
    const sessionid = avatarSessionRef.current;
    avatarSessionRef.current = "";
    if (sessionid) releaseAvatarSession(sessionid);
    setConnection("idle");
  }

  useEffect(() => {
    mountedRef.current = true;
    const onPageHide = () => {
      speechGenerationRef.current += 1;
      speechAbortRef.current?.abort();
      const peer = peerRef.current;
      peerRef.current = null;
      peer?.close();
      const sessionid = avatarSessionRef.current;
      avatarSessionRef.current = "";
      if (sessionid) releaseAvatarSession(sessionid);
      setConnection("idle");
    };
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      mountedRef.current = false;
      speechGenerationRef.current += 1;
      speechAbortRef.current?.abort();
      const peer = peerRef.current;
      peerRef.current = null;
      peer?.close();
      const sessionid = avatarSessionRef.current;
      avatarSessionRef.current = "";
      if (sessionid) releaseAvatarSession(sessionid);
    };
  }, []);

  async function connect() {
    if (peerRef.current) return;
    setConnection("connecting");
    setMessage("正在连接教育数字人…");
    const peer = new RTCPeerConnection();
    peerRef.current = peer;
    peer.addTransceiver("video", { direction: "recvonly" });
    peer.addTransceiver("audio", { direction: "recvonly" });
    peer.ontrack = (event) => {
      if (peerRef.current !== peer) return;
      if (event.track.kind === "video" && videoRef.current) {
        videoRef.current.srcObject = event.streams[0] ?? new MediaStream([event.track]);
      }
      if (event.track.kind === "audio" && audioRef.current) {
        audioRef.current.srcObject = event.streams[0] ?? new MediaStream([event.track]);
      }
    };
    peer.onconnectionstatechange = () => {
      if (peerRef.current !== peer) return;
      if (peer.connectionState === "connected") {
        setConnection("connected");
        setMessage("数字人已连接，可以开始语音讲解。");
      } else if (["failed", "closed", "disconnected"].includes(peer.connectionState)) {
        disconnect();
        setMessage("数字人连接已断开，文字答疑仍可继续。");
      }
    };
    try {
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      await waitForIce(peer);
      if (peerRef.current !== peer) return;
      const result = await post<OfferAnswer>("/offer", {
        sdp: peer.localDescription?.sdp,
        type: peer.localDescription?.type,
      });
      if (peerRef.current !== peer) {
        releaseAvatarSession(result.sessionid);
        return;
      }
      avatarSessionRef.current = result.sessionid;
      await peer.setRemoteDescription({ type: result.type as RTCSdpType, sdp: result.sdp });
    } catch (error) {
      if (peerRef.current === peer) {
        disconnect();
        setMessage(error instanceof Error ? error.message : "连接数字人失败");
      }
    }
  }

  async function speak(segments: string[], sessionid: string, generation: number, previousSpeechStopped: Promise<unknown>) {
    const controller = new AbortController();
    speechAbortRef.current = controller;
    try {
      await previousSpeechStopped;
      for (const [index, segment] of segments.entries()) {
        if (speechGenerationRef.current !== generation || avatarSessionRef.current !== sessionid) return;
        await post<object>("/human", {
          sessionid,
          text: segment,
          type: "echo",
          interrupt: index === 0,
        }, true, false, controller.signal);
      }
      if (mountedRef.current && speechGenerationRef.current === generation) {
        setMessage("答案已生成，数字人正在讲解。");
      }
    } catch (error) {
      if (mountedRef.current && speechGenerationRef.current === generation) {
        setMessage(`文字答案已生成，语音讲解失败：${error instanceof Error ? error.message : "请重新连接数字人"}`);
      }
    } finally {
      if (speechAbortRef.current === controller) speechAbortRef.current = null;
    }
  }

  async function ask() {
    const text = question.trim();
    if (!text || askInFlightRef.current || voiceStarting || recorder.state !== "idle") return;
    askInFlightRef.current = true;
    const generation = ++speechGenerationRef.current;
    speechAbortRef.current?.abort();
    const activeAvatar = avatarSessionRef.current;
    const previousSpeechStopped = activeAvatar
      ? post<object>("/interrupt_talk", { sessionid: activeAvatar }).catch(() => {})
      : Promise.resolve();
    setBusy(true);
    setAnswer("");
    setSources([]);
    setAnsweredLesson(null);
    setMessage("教学智能体正在分析问题…");
    try {
      const selectedKnowledgeBases = knowledgeBases.split(",").map((name) => name.trim()).filter(Boolean);
      const result = await post<TutorAnswer>("/api/chat/digital-human/ask", {
        text,
        session_id: tutorSessionRef.current || undefined,
        capability: mode,
        knowledge_bases: selectedKnowledgeBases,
        difficulty: difficulty || undefined,
        student_note: difficulty ? studentNote.trim() || undefined : undefined,
      }, false);
      if (!mountedRef.current) return;
      tutorSessionRef.current = result.session_id;
      setAnswer(result.answer);
      setSources(Array.isArray(result.sources) ? result.sources : []);
      setQuestion("");
      setVoiceTranscriptReady(false);
      if (result.needs_input) {
        setMessage("智能体需要补充信息，请在输入框回答后提交。");
        return;
      }
      setAnsweredLesson({ turnId: result.turn_id, sessionId: result.session_id, question: text, answer: result.answer, kbName: selectedKnowledgeBases[0] || "" });
      const sessionid = avatarSessionRef.current;
      if (generation === speechGenerationRef.current && sessionid && peerRef.current?.connectionState === "connected" && result.speech_segments.length) {
        setMessage("答案已生成，正在发送语音讲解。");
        void speak(result.speech_segments, sessionid, generation, previousSpeechStopped);
      } else {
        setMessage("答案已生成。连接数字人后可以听语音讲解。");
      }
    } catch (error) {
      if (mountedRef.current) setMessage(error instanceof Error ? error.message : "教学请求失败");
    } finally {
      askInFlightRef.current = false;
      if (mountedRef.current) setBusy(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-[var(--background)] px-4 py-6 md:px-8 md:py-8">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-teal-700"><BookOpen size={17} /> 个性化学习 · 数字人讲解</div>
            <h1 className="text-2xl font-semibold tracking-tight text-[var(--foreground)] md:text-3xl">和 AI 教师一起，把难题讲明白</h1>
            <p className="mt-2 text-sm text-[var(--muted-foreground)]">从问题出发，先理解知识点，再看解题思路。文字答疑与语音讲解共用同一段学习会话。</p>
          </div>
          <span className="rounded-full border border-[var(--border)] px-3 py-1 text-xs text-[var(--muted-foreground)]">{connection === "connected" ? "● 实时讲解中" : connection === "connecting" ? "连接中…" : "数字人未连接"}</span>
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(280px,0.9fr)_minmax(0,1.1fr)]">
          <section className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)]">
            <div className="relative aspect-[4/5] max-h-[590px] overflow-hidden bg-[#e9f2ef]">
              <Image src="/teacher-avatar.png" alt="AI 教师形象预览" fill priority className="object-cover object-top" />
              <video ref={videoRef} autoPlay playsInline muted className={`absolute inset-0 h-full w-full object-cover ${connection === "connected" ? "" : "hidden"}`} aria-label="教育数字人实时视频" />
              <audio ref={audioRef} autoPlay />
              <div className="absolute bottom-4 left-4 rounded-xl bg-white/90 px-4 py-2 text-sm text-slate-800 shadow-sm backdrop-blur-sm">
                <strong className="block">AI 教师 · 小知</strong>
                <span className="text-xs text-slate-600">{connection === "connected" ? "实时音视频" : "形象预览"}</span>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]"><Volume2 size={16} /> 连接后可听答案播报</div>
              {connection === "idle" ? (
                <button onClick={connect} className="inline-flex items-center gap-2 rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800"><Play size={15} /> 连接数字人</button>
              ) : (
                <button onClick={disconnect} className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium hover:bg-[var(--muted)]"><Square size={14} /> 断开连接</button>
              )}
            </div>
          </section>

          <section className="flex min-h-[500px] flex-col rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 md:p-6">
            <div className="flex items-center gap-2 text-lg font-semibold"><Mic2 size={19} className="text-teal-700" /> 互动答疑</div>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">可以追问同一个问题。选择“深入讲解”时，智能体会展开解题过程。</p>
            <div className="mt-5 flex flex-wrap gap-2">
              {["分数的分母表示什么？", "怎样理解一元一次方程？", "光合作用为什么需要阳光？"].map((sample) => (
                <button key={sample} type="button" onClick={() => setQuestion(sample)} className="rounded-full border border-[var(--border)] px-3 py-1.5 text-xs hover:border-teal-600 hover:text-teal-700">{sample}</button>
              ))}
            </div>
            <div className="mt-5 min-h-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
              {answer ? <MarkdownRenderer content={answer} className="text-sm leading-7" /> : <p className="text-sm text-[var(--muted-foreground)]">答案会显示在这里。先选一个示例，或输入自己的学习问题。</p>}
            </div>
            <LearningSources sources={sources} />
            {answeredLesson && <LearningCheckPanel key={answeredLesson.turnId} sessionId={answeredLesson.sessionId} lessonQuestion={answeredLesson.question} lessonAnswer={answeredLesson.answer} kbName={answeredLesson.kbName} />}
            <div role="status" aria-live="polite" className="my-3 min-h-5 text-sm text-[var(--muted-foreground)]">{message}</div>
            <label htmlFor="tutor-difficulty" className="mb-2 text-sm font-medium">你卡在哪一步？（可选）</label>
            <select id="tutor-difficulty" value={difficulty} onChange={(event) => setDifficulty(event.target.value as Difficulty)} className="mb-3 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm">
              <option value="">直接提问</option>
              <option value="understand_problem">读不懂题意</option>
              <option value="choose_method">不知道用什么方法</option>
              <option value="calculation_or_reasoning">计算或推理时卡住</option>
              <option value="unsure">暂时说不清楚</option>
            </select>
            {difficulty && <label htmlFor="tutor-difficulty-note" className="mb-3 text-xs text-[var(--muted-foreground)]">补充说明卡点（可选）
              <input id="tutor-difficulty-note" value={studentNote} maxLength={200} onChange={(event) => setStudentNote(event.target.value)} className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm" placeholder="例如：我列出了方程，但不知道下一步怎么移项" />
            </label>}
            <label htmlFor="tutor-question" className="mb-2 text-sm font-medium">输入学习问题</label>
            <textarea id="tutor-question" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) void ask(); }} className="min-h-24 w-full resize-y rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-3 text-sm outline-none focus:border-teal-600" placeholder="例如：这道题为什么要先通分？" />
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <button type="button" onClick={toggleVoiceRecording} disabled={voiceStarting || recorder.state === "transcribing" || (busy && recorder.state !== "recording")} aria-label={recorder.state === "recording" ? "停止录音并转写" : "开始语音提问"} className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${recorder.state === "recording" ? "border-red-500 text-red-600" : "border-[var(--border)] hover:border-teal-600 hover:text-teal-700"}`}>
                {recorder.state === "recording" ? <Square size={15} /> : <Mic2 size={16} />}
                {recorder.state === "recording" ? "停止录音并转写" : "开始语音提问"}
              </button>
              <span role="status" aria-live="polite" className="text-xs text-[var(--muted-foreground)]">
                {voiceStarting ? "正在请求麦克风权限…" : recorder.state === "recording" ? "正在录音，请说出问题。" : recorder.state === "transcribing" ? "正在转写语音…" : voiceTranscriptReady ? "语音已转写，请检查文字后提问。" : "语音会转成文字供您确认。"}
              </span>
            </div>
            {(recorder.error || voiceStartError) && <p role="alert" className="mt-2 text-xs text-red-600">{recorder.error === "Microphone permission denied." ? "无法访问麦克风，请检查浏览器权限。" : recorder.error === "Recording is not supported in this browser." ? "当前浏览器不支持录音。" : recorder.error || voiceStartError}</p>}
            <label htmlFor="tutor-kb" className="mb-2 mt-3 text-xs text-[var(--muted-foreground)]">知识库名称（可选，多个用英文逗号分隔）</label>
            <input id="tutor-kb" value={knowledgeBases} onChange={(event) => setKnowledgeBases(event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-teal-600" placeholder="例如：七年级数学" />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <select aria-label="教学模式" value={mode} onChange={(event) => setMode(event.target.value as "chat" | "deep_solve")} className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm">
                <option value="chat">互动答疑</option>
                <option value="deep_solve">深入讲解</option>
              </select>
              <button onClick={ask} disabled={!question.trim() || busy || voiceStarting || recorder.state !== "idle"} className="rounded-lg bg-teal-700 px-5 py-2.5 text-sm font-medium text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50">{busy ? "正在思考…" : "提问并讲解"}</button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
