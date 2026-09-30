import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import DigitalHumanPage from "@/app/(workspace)/digital-human/page";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
}));

const stopTrack = vi.fn();
const getUserMedia = vi.fn();
const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");

class TestMediaRecorder {
  state: RecordingState = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onstop: (() => void) | null = null;

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["spoken question"]) } as BlobEvent);
    this.onstop?.();
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  getUserMedia.mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
  vi.stubGlobal("MediaRecorder", TestMediaRecorder);
  vi.mocked(apiFetch).mockResolvedValue({
    ok: true,
    json: async () => ({ text: "为什么要先通分？" }),
  } as Response);
});

afterEach(() => {
  vi.unstubAllGlobals();
  if (originalMediaDevices) Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
  else Reflect.deleteProperty(navigator, "mediaDevices");
});

it("transcribes a recorded question into the editable field without submitting it", async () => {
  render(<DigitalHumanPage />);
  fireEvent.change(screen.getByRole("textbox", { name: "输入学习问题" }), {
    target: { value: "数学题：" },
  });

  fireEvent.click(screen.getByRole("button", { name: "开始语音提问" }));
  fireEvent.click(await screen.findByRole("button", { name: "停止录音并转写" }));

  await waitFor(() => expect(screen.getByRole("textbox", { name: "输入学习问题" })).toHaveValue("数学题： 为什么要先通分？"));
  expect(screen.getByRole("button", { name: "提问并讲解" })).toBeEnabled();
  expect(apiFetch).toHaveBeenCalledTimes(1);
  expect(apiFetch).toHaveBeenCalledWith("/api/voice/stt", expect.objectContaining({ method: "POST" }));
  expect(stopTrack).toHaveBeenCalledTimes(1);
});

it("does not request microphone permission twice while a request is pending", async () => {
  let grantMicrophone!: (stream: { getTracks: () => { stop: typeof stopTrack }[] }) => void;
  getUserMedia.mockImplementation(() => new Promise((resolve) => { grantMicrophone = resolve; }));
  const view = render(<DigitalHumanPage />);
  const button = screen.getByRole("button", { name: "开始语音提问" });

  fireEvent.click(button);
  fireEvent.click(button);
  expect(getUserMedia).toHaveBeenCalledTimes(1);

  await act(async () => {
    grantMicrophone({ getTracks: () => [{ stop: stopTrack }] });
  });
  await screen.findByRole("button", { name: "停止录音并转写" });
  view.unmount();
  expect(stopTrack).toHaveBeenCalledTimes(1);
});

it("shows microphone permission errors near the voice control", async () => {
  getUserMedia.mockRejectedValue(new Error("denied"));
  render(<DigitalHumanPage />);

  fireEvent.click(screen.getByRole("button", { name: "开始语音提问" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("无法访问麦克风，请检查浏览器权限。");
});
